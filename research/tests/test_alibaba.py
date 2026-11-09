import csv
import gzip

import pytest

from kfo_research import alibaba


def write_gz(path, rows):
    with gzip.open(path, "wt", newline="") as f:
        csv.writer(f).writerows(rows)


def test_units_and_filters(tmp_path):
    meta = tmp_path / "meta.csv.gz"
    write_gz(meta, [["c_1", "m_1", "0", "app_1", "started", "400", "400", "1.56"],
                    ["c_2", "m_1", "0", "app_2", "started", "200", "200", "3.0"]])
    usage = tmp_path / "usage.csv.gz"
    rows = [["container_id", "slot", "cpu_mean", "cpu_peak", "mem_mean", "mem_peak", "samples"]]
    for i in range(8 * 96):                                   # 8 days of 15-min windows
        rows.append(["c_1", i * 900, "25", "50", "40", "60", "2"])
    for i in range(96):                                       # c_2: only one day -> filtered out
        rows.append(["c_2", i * 900, "10", "10", "10", "10", "1"])
    write_gz(usage, rows)

    traces = alibaba.load_traces(usage, meta, min_days=7.5)
    assert [t.name for t in traces] == ["c_1"]
    t = traces[0]
    # CPU % is relative to the request (4 cores): 50 % peak -> 2 cores.
    assert t.points[0].cpu_peak == pytest.approx(2.0)
    # Memory % is relative to the container's mem_size: 60 % of 1.56 units.
    assert t.points[0].mem_peak / t.original.mem_request == pytest.approx(0.60)
    assert t.points[0].duration_seconds == alibaba.SLOT

    report = alibaba.sanity_report(traces)
    assert report["cpu_peak_over_request_median"] == pytest.approx(0.5)
    assert report["mem_peak_over_request_median"] == pytest.approx(0.6)


def test_streaming_line_reader_handles_chunk_boundaries():
    import io

    data = b"a,1\nbb,22\nccc,333"            # no trailing newline
    lines = list(alibaba._lines(io.BytesIO(data), chunk=4))
    assert lines == ["a,1\n", "bb,22\n", "ccc,333"]
