# KubeFinOps research: SLO-aware right-sizing

Trace-driven evaluation of the right-sizing strategies in `backend/app/engines/rightsizing.py`
(the exact code that runs in the product) and the paper draft built from it.

```
research/
  kfo_research/simulate.py     replay simulator (daily re-recommendation, OOM feedback, re-observation under new limits)
  kfo_research/workloads.py    8 synthetic archetypes with ground truth (fixed seed)
  kfo_research/alibaba.py      streaming loader for Alibaba cluster-trace-v2018 containers
  kfo_research/experiments.py  all strategies + ablations + epsilon sweep -> results/, paper/generated/, paper/figures/
  paper/main.tex, refs.bib     IEEE conference draft (tables/figures are generated)
  tests/                       simulator and workload tests
```

## Reproduce

```bash
cd research
pip install -r requirements.txt pytest
pytest
python -m kfo_research.experiments                 # 200 containers x 12 strategies, ~2 min on 28 cores
latexmk -pdf -cd paper/main.tex                    # or upload paper/ to Overleaf
```

## Real traces (Alibaba cluster-trace-v2018)

`container_usage.tar.gz` is ~29 GB. The loader streams it and stops after a byte budget, keeping 5-minute
aggregates in 15-minute windows (samples are ~10 min apart), ~136 MB for a 300 MB budget:

```bash
python -c "from kfo_research.alibaba import fetch_meta, fetch_subset; fetch_meta(); fetch_subset(budget_mb=300)"
python -m kfo_research.experiments --alibaba data/container_usage_15min_300mb.csv.gz --sample 0.05   # ~2 min
```

`--sample` keeps a deterministic hash-based fraction of containers (5 % -> 2,037 containers). `sanity_report`
prints the unit checks: CPU % is relative to the request (peak never exceeds it; median peak/request 0.30).
Memory % is relative to the container's memory size and includes page cache (70 % of containers reach it,
some exceed it without being killed), so the original memory allocation is treated as safe: only a limit
lowered below it can produce a memory (OOM) event.

## Current results (Alibaba v2018, 2,037 production containers, ~5 evaluated days)

| Strategy | Savings | CPU under-provisioned windows | Containers with memory events |
| :--- | ---: | ---: | ---: |
| p95 + 20 % | 77.5 % | 3.20 % | 38 |
| VPA-style | 80.0 % | 7.92 % | 69 |
| **SLO-aware (ε = 1 %)** | **63.8 %** | **0.39 %** | **28** |

ε = 0.5 / 1 / 2 / 5 % gives 0.25 / 0.39 / 0.60 / 1.05 % realised under-provisioning: always below target.

## Current results (synthetic, 200 containers)

| Strategy | Savings | CPU under-provisioned windows | OOM events |
| :--- | ---: | ---: | ---: |
| p95 + 20 % | 55.1 % | 11.39 % | 0 |
| VPA-style | 63.9 % | 18.77 % | 67 |
| **SLO-aware (ε = 1 %)** | **41.4 %** | **0.47 %** | **0** |
