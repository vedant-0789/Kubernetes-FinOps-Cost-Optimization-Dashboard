"""Alibaba cluster-trace-v2018 loader (containers).

The per-container usage file is a single ~29 GB ``container_usage.tar.gz``.
Instead of downloading it, ``fetch_subset`` streams it over HTTP, decompresses
on the fly and stops after a byte budget, then aggregates the raw samples
(~10 s apart) into the same 5-minute windows (mean and peak) the KubeFinOps
agent produces. Requests come from ``container_meta`` (cpu_request: 100 =
1 core; mem_size: normalised memory units).

Units (documented assumptions, checked by ``sanity_report`` on the data):
* ``cpu_util_percent`` is taken relative to the container's CPU request
  (``CPU_RELATIVE_TO = "request"``); switch to ``"machine"`` if the report
  shows values that only make sense as machine-relative.
* memory is kept in the trace's normalised units: savings ratios and OOM
  comparisons are scale-free, so no machine-size guess is needed.

Dataset & licence: https://github.com/alibaba/clusterdata (cluster-trace-v2018).
"""

import csv
import gzip
import io
import tarfile
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from kfo_research.simulate import Trace
from app.engines.rightsizing import ContainerSpec, UsagePoint

BASE_URL = "http://aliopentrace.oss-cn-beijing.aliyuncs.com/v2018Traces"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SLOT = 300
CPU_RELATIVE_TO = "request"
MEM_UNIT = 2**30   # one normalised memory unit is treated as 1 "GiB" for reporting only


class _CountingReader(io.RawIOBase):
    """Wraps the HTTP response to stop after ``budget`` compressed bytes."""

    def __init__(self, raw, budget: int):
        self.raw, self.budget, self.read_bytes = raw, budget, 0

    def readable(self):
        return True

    def readinto(self, b):
        if self.read_bytes >= self.budget:
            return 0
        chunk = self.raw.read(min(len(b), self.budget - self.read_bytes))
        n = len(chunk)
        b[:n] = chunk
        self.read_bytes += n
        return n


def _open_member(name: str, budget: int | None):
    resp = urllib.request.urlopen(urllib.request.Request(f"{BASE_URL}/{name}.tar.gz",
                                                         headers={"User-Agent": "kubefinops-research/1.0"}),
                                  timeout=60)
    stream = io.BufferedReader(_CountingReader(resp, budget)) if budget else resp
    tar = tarfile.open(fileobj=stream, mode="r|gz")
    for member in tar:
        if member.isfile():
            return tar, io.TextIOWrapper(tar.extractfile(member), encoding="utf-8", errors="replace")
    raise RuntimeError(f"no file inside {name}.tar.gz")


def fetch_meta(dest: Path = DATA_DIR) -> Path:
    """container_meta (~2.4 MB compressed): container -> requests."""
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "container_meta.csv.gz"
    if out.exists():
        return out
    _, text = _open_member("container_meta", None)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for line in text:
            f.write(line)
    return out


def fetch_subset(budget_mb: int = 300, dest: Path = DATA_DIR) -> Path:
    """Stream the first ``budget_mb`` compressed MB of container_usage and keep
    5-minute aggregates per container (a few MB on disk)."""
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"container_usage_5min_{budget_mb}mb.csv.gz"
    if out.exists():
        return out
    _, text = _open_member("container_usage", budget_mb * 2**20)
    agg: dict[tuple[str, int], list[float]] = {}
    try:
        for row in csv.reader(text):
            if len(row) < 5 or not row[2]:
                continue
            try:
                cid, ts, cpu, mem = row[0], int(row[2]), float(row[3] or 0), float(row[4] or 0)
            except ValueError:
                continue
            slot = ts // SLOT * SLOT
            a = agg.get((cid, slot))
            if a is None:
                agg[(cid, slot)] = [cpu, cpu, mem, mem, 1]
            else:
                a[0] += cpu
                a[1] = max(a[1], cpu)
                a[2] += mem
                a[3] = max(a[3], mem)
                a[4] += 1
    except (EOFError, tarfile.ReadError, OSError):
        pass   # budget reached mid-stream: everything read so far is valid
    with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["container_id", "slot", "cpu_mean", "cpu_peak", "mem_mean", "mem_peak", "samples"])
        for (cid, slot), (cs, cmax, ms, mmax, k) in sorted(agg.items()):
            w.writerow([cid, slot, round(cs / k, 3), cmax, round(ms / k, 3), mmax, k])
    return out


@dataclass
class Meta:
    cpu_request: float   # cores
    cpu_limit: float | None
    mem_size: float      # normalised units


def load_meta(path: Path) -> dict[str, Meta]:
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for row in csv.reader(f):
            try:   # container_id, machine_id, time_stamp, app_du, status, cpu_request, cpu_limit, mem_size
                out[row[0]] = Meta(float(row[5]) / 100, float(row[6]) / 100 if row[6] else None, float(row[7]))
            except (ValueError, IndexError):
                continue
    return out


def load_traces(usage_path: Path, meta_path: Path, min_days: float = 8.0, max_containers: int | None = None
                ) -> list[Trace]:
    """Containers with at least ``min_days`` of contiguous-enough 5-minute data."""
    meta = load_meta(meta_path)
    rows: dict[str, list[list[float]]] = defaultdict(list)
    with gzip.open(usage_path, "rt", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        for cid, slot, cm, cp, mm, mp, _ in r:
            rows[cid].append([int(slot), float(cm), float(cp), float(mm), float(mp)])
    traces = []
    for cid, series in sorted(rows.items()):
        m = meta.get(cid)
        if m is None or m.cpu_request <= 0 or m.mem_size <= 0:
            continue
        series.sort()
        span_days = (series[-1][0] - series[0][0]) / 86400
        if span_days < min_days or len(series) < 0.8 * span_days * 288:
            continue
        scale = m.cpu_request / 100 if CPU_RELATIVE_TO == "request" else 1 / 100
        # Memory: mem_util_percent and mem_size are both % of machine memory,
        # so keep both in the same (normalised) unit.
        pts = [UsagePoint(ts=float(s), cpu_mean=cm * scale, cpu_peak=cp * scale, mem_mean=mm * MEM_UNIT / 100,
                          mem_peak=mp * MEM_UNIT / 100, duration_seconds=SLOT) for s, cm, cp, mm, mp in series]
        original = ContainerSpec(m.cpu_request, m.mem_size * MEM_UNIT / 100, m.cpu_limit, m.mem_size * MEM_UNIT / 100)
        traces.append(Trace(cid, "alibaba", pts, original, meta={"span_days": span_days}))
        if max_containers and len(traces) >= max_containers:
            break
    return traces


def sanity_report(traces: list[Trace]) -> dict:
    """Quick checks of the unit assumptions on real data."""
    import statistics as st

    util = [max(p.cpu_peak for p in t.points) / t.original.cpu_request for t in traces if t.original.cpu_request]
    mem = [max(p.mem_peak for p in t.points) / t.original.mem_request for t in traces if t.original.mem_request]
    return {"containers": len(traces),
            "cpu_peak_over_request_median": st.median(util) if util else None,
            "cpu_peak_over_request_p95": sorted(util)[int(0.95 * len(util))] if util else None,
            "mem_peak_over_request_median": st.median(mem) if mem else None,
            "share_cpu_peak_above_request": sum(u > 1 for u in util) / len(util) if util else None}
