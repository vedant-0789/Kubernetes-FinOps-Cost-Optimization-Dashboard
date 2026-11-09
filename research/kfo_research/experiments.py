"""Run every strategy and ablation on a trace population; write results,
LaTeX tables and figures for the paper.

    python -m kfo_research.experiments                 # synthetic population (default)
    python -m kfo_research.experiments --alibaba data/container_usage_15min_300mb.csv.gz
"""

import argparse
import csv
import json
import multiprocessing as mp
import time
from dataclasses import asdict
from pathlib import Path

from kfo_research.simulate import Outcome, Trace, replay, static, strategy, summarize
from app.engines.rightsizing import Policy

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
GENERATED = ROOT / "paper" / "generated"
FIGURES = ROOT / "paper" / "figures"

D = Policy()
STRATEGIES = {
    # name: (engine strategy, policy or None, label)
    "static": (None, None, "Original requests"),
    "p95_buffer": ("p95_buffer", None, "p95 + 20\\%"),
    "vpa": ("vpa", None, "VPA-style"),
    "slo_aware": ("slo_aware", None, "SLO-aware (ours)"),
}
ABLATIONS = {
    "slo_no_censoring": ("slo_aware", Policy(throttle_threshold=1e9), "-- censoring correction"),
    "slo_no_oom_feedback": ("slo_aware", Policy(oom_step=0.0), "-- OOM feedback"),
    "slo_no_decay": ("slo_aware", Policy(half_life_hours=1e7), "-- recency weighting"),
    "slo_no_peak_cv": ("slo_aware", Policy(cpu_cv_factor=0.0), "-- daily-peak headroom"),
    "slo_no_step_cap": ("slo_aware", Policy(max_reduction=1.0), "-- step cap (one-shot)"),
}
EPSILON_SWEEP = {f"slo_eps_{e}": ("slo_aware", Policy(cpu_slo_exceedance=e / 100), f"SLO-aware, $\\varepsilon$={e}\\%")
                 for e in (0.5, 2, 5)}
ALL = {**STRATEGIES, **ABLATIONS, **EPSILON_SWEEP}
LABEL_OFFSETS = {"slo_aware": (8, -3), "slo_eps_0.5": (8, -11), "slo_eps_2": (-30, 6), "slo_eps_5": (7, 0)}


def _fn(name: str):
    engine, policy, _ = ALL[name]
    return static if engine is None else strategy(engine, policy)


def _run_one(args) -> list[Outcome]:
    trace, names, warmup, history = args
    return [replay(trace, n, _fn(n), warmup_days=warmup, history_days=history) for n in names]


def run(traces: list[Trace], names: list[str], workers: int | None = None, warmup_days: int = 7,
        history_days: int = 14) -> dict[str, list[Outcome]]:
    with mp.Pool(workers or max(1, mp.cpu_count() - 2)) as pool:
        per_trace = pool.map(_run_one, [(t, names, warmup_days, history_days) for t in traces],
                             chunksize=max(1, len(traces) // 200))
    by_strategy: dict[str, list[Outcome]] = {n: [] for n in names}
    for outs in per_trace:
        for o in outs:
            by_strategy[o.strategy].append(o)
    return by_strategy


# --- outputs ---------------------------------------------------------------------------


def write_results(by_strategy: dict[str, list[Outcome]], tag: str) -> dict:
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary = {n: asdict(summarize(o)) for n, o in by_strategy.items()}
    archetypes = sorted({o.archetype for outs in by_strategy.values() for o in outs})
    per_arch = {a: {n: asdict(summarize([o for o in outs if o.archetype == a])) for n, outs in by_strategy.items()}
                for a in archetypes}
    (RESULTS / f"summary_{tag}.json").write_text(json.dumps({"overall": summary, "by_archetype": per_arch}, indent=2))
    with (RESULTS / f"per_container_{tag}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "trace", "archetype", "savings_pct", "cpu_under_rate", "cpu_deficit_core_hours",
                    "oom_events", "orig_oom_events", "final_cpu", "final_mem"])
        for n, outs in by_strategy.items():
            for o in outs:
                w.writerow([n, o.trace, o.archetype, round(o.savings_pct, 3), round(o.cpu_under_rate, 5),
                            round(o.cpu_deficit_core_hours, 4), o.oom_events, o.orig_oom_events,
                            round(o.final_cpu, 4), round(o.final_mem)])
    return {"overall": summary, "by_archetype": per_arch}


def _row(label, s) -> str:
    return (f"{label} & {s['savings_pct']:.1f} & {s['cpu_under_rate'] * 100:.2f} & {s['cpu_deficit_share'] * 100:.2f}"
            f" & {s['oom_events']} & {s['containers_with_oom']} \\\\")


def write_tables(res: dict, tag: str) -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    o = res["overall"]
    head = ("\\begin{tabular}{lrrrrr}\\toprule\n"
            "Strategy & Savings (\\%) & CPU under (\\%) & CPU deficit (\\%) & OOM events & Containers w/ OOM \\\\"
            "\\midrule\n")
    main = head + "\n".join(_row(ALL[n][2], o[n]) for n in STRATEGIES if n in o) + "\n\\bottomrule\\end{tabular}\n"
    (GENERATED / f"table_main_{tag}.tex").write_text(main)
    abl_names = ["slo_aware", *[n for n in ABLATIONS if n in o], *[n for n in EPSILON_SWEEP if n in o]]
    abl = head + "\n".join(_row(ALL[n][2], o[n]) for n in abl_names) + "\n\\bottomrule\\end{tabular}\n"
    (GENERATED / f"table_ablation_{tag}.tex").write_text(abl)
    arch = res["by_archetype"]
    lines = ["\\begin{tabular}{l" + "rr" * 3 + "}\\toprule",
             " & \\multicolumn{2}{c}{p95+20\\%} & \\multicolumn{2}{c}{VPA-style} & \\multicolumn{2}{c}{SLO-aware} \\\\",
             "Archetype & Sav.\\% & Under\\% / OOM & Sav.\\% & Under\\% / OOM & Sav.\\% & Under\\% / OOM \\\\\\midrule"]
    for a, s in arch.items():
        cells = []
        for n in ("p95_buffer", "vpa", "slo_aware"):
            if n in s:
                cells.append(f"{s[n]['savings_pct']:.0f} & {s[n]['cpu_under_rate'] * 100:.1f} / {s[n]['oom_events']}")
        lines.append(f"{a.replace('_', ' ')} & " + " & ".join(cells) + " \\\\")
    lines.append("\\bottomrule\\end{tabular}")
    (GENERATED / f"table_archetypes_{tag}.tex").write_text("\n".join(lines) + "\n")


def write_figures(res: dict, by_strategy: dict[str, list[Outcome]], tag: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIGURES.mkdir(parents=True, exist_ok=True)
    o = res["overall"]
    colors = {"static": "#64748b", "p95_buffer": "#f59e0b", "vpa": "#3b82f6", "slo_aware": "#10b981"}

    # 1. Savings vs CPU under-provisioning (Pareto view), incl. the epsilon sweep.
    fig, ax = plt.subplots(figsize=(4.2, 3.0))
    for n, s in o.items():
        if n in ABLATIONS:
            continue
        c = colors.get(n, "#10b981")
        marker = "o" if n in STRATEGIES else "^"
        ax.scatter(s["cpu_under_rate"] * 100, s["savings_pct"], color=c, marker=marker, s=46, zorder=3,
                   alpha=1 if n in STRATEGIES else 0.6)
        offset = LABEL_OFFSETS.get(n, (5, 3))
        label = ALL[n][2].replace("\\%", "%").replace("$\\varepsilon$", "ε")
        if n.startswith("slo_eps_"):
            label = label.split(", ")[-1]          # "ε=2%": the marker colour already says SLO-aware
        ax.annotate(label, (s["cpu_under_rate"] * 100, s["savings_pct"]), textcoords="offset points", xytext=offset,
                    fontsize=7)
    ax.set_xlabel("CPU under-provisioned windows (%)")
    ax.set_ylabel("Cost savings vs. original (%)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / f"pareto_{tag}.pdf")
    fig.savefig(FIGURES / f"pareto_{tag}.png", dpi=160)
    plt.close(fig)

    # 2. CDF of per-container under-provisioning rate.
    fig, ax = plt.subplots(figsize=(4.2, 3.0))
    for n in ("p95_buffer", "vpa", "slo_aware"):
        if n not in by_strategy:
            continue
        v = sorted(x.cpu_under_rate * 100 for x in by_strategy[n])
        ax.plot(v, [(i + 1) / len(v) for i in range(len(v))], label=ALL[n][2].replace("\\%", "%"), color=colors[n])
    ax.set_xscale("symlog", linthresh=0.1)
    ax.set_xlabel("Per-container CPU under-provisioned windows (%)")
    ax.set_ylabel("CDF of containers")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / f"cdf_under_{tag}.pdf")
    fig.savefig(FIGURES / f"cdf_under_{tag}.png", dpi=160)
    plt.close(fig)

    # 3. Savings and OOM events per archetype.
    arch = res["by_archetype"]
    names = [n for n in ("p95_buffer", "vpa", "slo_aware") if n in o]
    if len(arch) > 1:
        fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.0))
        xs = list(range(len(arch)))
        w = 0.8 / len(names)
        for k, n in enumerate(names):
            axes[0].bar([x + k * w for x in xs], [arch[a][n]["savings_pct"] for a in arch], w,
                        label=ALL[n][2].replace("\\%", "%"), color=colors[n])
            axes[1].bar([x + k * w for x in xs], [arch[a][n]["oom_events"] for a in arch], w, color=colors[n])
        for axx, title in zip(axes, ("Savings (%)", "OOM events"), strict=True):
            axx.set_xticks([x + w for x in xs])
            axx.set_xticklabels([a.replace("_", "\n") for a in arch], fontsize=6)
            axx.set_title(title, fontsize=9)
            axx.grid(axis="y", alpha=0.3)
        axes[0].legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(FIGURES / f"archetypes_{tag}.pdf")
        fig.savefig(FIGURES / f"archetypes_{tag}.png", dpi=160)
        plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-archetype", type=int, default=25)
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--alibaba", type=Path, help="5-minute container_usage subset (from alibaba.fetch_subset)")
    ap.add_argument("--meta", type=Path, default=ROOT / "data" / "container_meta.csv.gz")
    ap.add_argument("--max-containers", type=int, default=None)
    ap.add_argument("--sample", type=float, default=0.05, help="hash-sampled fraction of Alibaba containers")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--warmup-days", type=int, default=None, help="default 7 (synthetic) / 3 (Alibaba: 8-day trace)")
    args = ap.parse_args()

    started = time.time()
    if args.alibaba:
        from kfo_research.alibaba import load_traces, sanity_report

        traces = load_traces(args.alibaba, args.meta, max_containers=args.max_containers,
                             sample=args.sample)
        print("sanity:", sanity_report(traces))
        tag, names = "alibaba", [*STRATEGIES, *ABLATIONS, *EPSILON_SWEEP]
        warmup = args.warmup_days or 3
    else:
        from kfo_research.workloads import population

        traces = population(args.per_archetype, args.days, args.seed)
        tag, names = "synthetic", list(ALL)
        warmup = args.warmup_days or 7
    print(f"{len(traces)} containers x {len(names)} strategies ({tag})")
    by_strategy = run(traces, names, args.workers, warmup_days=warmup)
    res = write_results(by_strategy, tag)
    write_tables(res, tag)
    write_figures(res, by_strategy, tag)
    for n in names:
        s = res["overall"][n]
        print(f"{n:22} savings {s['savings_pct']:6.1f}%  cpu-under {s['cpu_under_rate'] * 100:6.2f}%  "
              f"deficit {s['cpu_deficit_share'] * 100:6.2f}%  OOM {s['oom_events']:6} ({s['containers_with_oom']} ctr)")
    print(f"done in {time.time() - started:.0f}s -> {RESULTS}, {GENERATED}, {FIGURES}")


if __name__ == "__main__":
    main()
