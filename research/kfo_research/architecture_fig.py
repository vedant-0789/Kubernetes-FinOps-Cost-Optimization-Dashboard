"""Architecture figure for the paper (paper/figures/architecture.{pdf,png}).

    python -m kfo_research.architecture_fig
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "paper" / "figures"

EDGE, FILL, GROUP, ACCENT = "#334155", "#f8fafc", "#e2e8f0", "#059669"


def box(ax, x, y, w, h, title, sub="", accent=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc="#ecfdf5" if accent else FILL, ec=ACCENT if accent else EDGE, lw=1.1))
    nt, ns = title.count("\n") + 1, (sub.count("\n") + 1) if sub else 0
    # Stack title (8.2 pt lines) and subtitle (6.4 pt lines) as one centred block.
    lt, ls_ = 0.15, 0.12
    total = nt * lt + ns * ls_ + (0.06 if sub else 0)
    top = y + h / 2 + total / 2
    ax.text(x + w / 2, top - nt * lt / 2, title, ha="center", va="center", fontsize=8.2,
            weight="bold", color="#0f172a", linespacing=1.0)
    if sub:
        ax.text(x + w / 2, top - nt * lt - 0.06 - ns * ls_ / 2, sub, ha="center", va="center", fontsize=6.4,
                color="#475569", linespacing=1.1)


def group(ax, x, y, w, h, label):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=GROUP, ec="#94a3b8", lw=0.8, ls="--", alpha=0.55))
    ax.text(x + 0.1, y + h - 0.12, label, ha="left", va="top", fontsize=7.2, style="italic", color="#334155")


def arrow(ax, a, b, label="", both=False, color=EDGE, dy=0.0, rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="<|-|>" if both else "-|>", mutation_scale=8, lw=1.0,
                                 color=color, connectionstyle=f"arc3,rad={rad}"))
    if label:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy, label, ha="center", va="center", fontsize=6.2,
                color=color, bbox=dict(fc="white", ec="none", pad=0.6))


def main() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.1))
    ax.set_xlim(0, 10.6)
    ax.set_ylim(0, 4.4)
    ax.axis("off")

    group(ax, 0.1, 0.15, 3.5, 4.1, "Kubernetes cluster (one agent each)")
    box(ax, 0.35, 3.0, 1.45, 0.75, "K8s API", "inventory, HPAs")
    box(ax, 1.95, 3.0, 1.45, 0.75, "Prometheus", "cAdvisor, KSM")
    box(ax, 0.6, 1.55, 2.5, 0.85, "finops-agent", "read-only RBAC, 5-min push")
    box(ax, 0.6, 0.35, 2.5, 0.8, "executor (opt-in)", "dry-run, patch, rollback")
    arrow(ax, (1.07, 3.0), (1.4, 2.4))
    arrow(ax, (2.67, 3.0), (2.3, 2.4))
    arrow(ax, (1.85, 1.15), (1.85, 1.55), both=True)
    arrow(ax, (0.75, 1.15), (0.75, 3.0), color="#64748b", rad=-0.35)

    group(ax, 4.6, 0.15, 5.9, 4.1, "KubeFinOps server")
    box(ax, 4.85, 2.75, 2.2, 0.95, "API", "auth/RBAC, ingestion,\nqueries, approvals")
    box(ax, 4.85, 0.4, 2.2, 1.55, "Worker", "allocation (OpenCost)\nwaste, forecasts,\nanomalies, verification")
    box(ax, 7.55, 1.95, 1.1, 0.9, "Timescale\nDB")
    box(ax, 8.95, 2.75, 1.35, 0.95, "UI", "React")
    box(ax, 8.95, 0.4, 1.35, 1.55, "SLO-aware\nright-sizing", "same engine as\nsimulator", accent=True)
    arrow(ax, (7.05, 3.2), (7.7, 2.85), both=True)
    arrow(ax, (7.05, 1.2), (7.7, 1.95), both=True)
    arrow(ax, (8.95, 3.25), (7.05, 3.4))
    arrow(ax, (8.95, 1.2), (7.05, 1.0))

    arrow(ax, (3.1, 2.1), (4.85, 3.05), "samples + inventory", dy=0.34)
    arrow(ax, (4.85, 2.9), (3.1, 1.85), "approved actions", color=ACCENT, dy=-0.36)

    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=0.1)
    fig.savefig(OUT / "architecture.pdf")
    fig.savefig(OUT / "architecture.png", dpi=180)
    plt.close(fig)
    print(f"wrote {OUT / 'architecture.pdf'}")


if __name__ == "__main__":
    main()
