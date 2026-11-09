"""Daily cost series, forecasts, budgets and cost-anomaly detection.

Scopes: ``cluster`` (allocated + idle = the bill), ``namespace:<ns>``,
``label:<key>=<value>`` (via workload labels; shared namespaces excluded).
"""

import calendar
import datetime
import logging
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.platform_models import (
    Budget,
    BudgetAlert,
    Cluster,
    CostAllocation,
    CostAnomaly,
    NodeCost,
    Workload,
    utcnow,
)
from app.engines import forecast as fc
from app.services import notify

logger = logging.getLogger("finance")
DAY = datetime.timedelta(days=1)


def day_floor(ts: datetime.datetime) -> datetime.datetime:
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_scope(scope: str) -> tuple[str, str | None, str | None]:
    if scope == "cluster":
        return "cluster", None, None
    if scope.startswith("namespace:") and len(scope) > 10:
        return "namespace", None, scope[10:]
    if scope.startswith("label:") and "=" in scope[6:]:
        key, value = scope[6:].split("=", 1)
        if key and value:
            return "label", key, value
    raise HTTPException(422, "scope must be cluster, namespace:<ns> or label:<key>=<value>")


def costs_by_day(db: Session, cluster: Cluster, kind: str, key: str | None, value: str | None,
                 start: datetime.datetime, end: datetime.datetime) -> dict[datetime.datetime, float]:
    """Cost per UTC day in [start, end) for one scope."""
    C = CostAllocation
    out: dict[datetime.datetime, float] = defaultdict(float)
    base = [C.cluster_id == cluster.id, C.window_start >= start, C.window_start < end]
    if kind == "cluster":
        for ts, cost in db.query(C.window_start, func.sum(C.total_cost)).filter(*base).group_by(C.window_start):
            out[day_floor(ts)] += cost or 0.0
        for ts, idle in db.query(NodeCost.window_start, func.sum(NodeCost.idle_cpu_cost + NodeCost.idle_ram_cost)) \
                .filter(NodeCost.cluster_id == cluster.id, NodeCost.window_start >= start,
                        NodeCost.window_start < end).group_by(NodeCost.window_start):
            out[day_floor(ts)] += idle or 0.0
    elif kind == "namespace":
        for ts, cost in db.query(C.window_start, func.sum(C.total_cost)).filter(*base, C.namespace == value) \
                .group_by(C.window_start):
            out[day_floor(ts)] += cost or 0.0
    else:
        matching = {(w.namespace, w.kind, w.name) for w in db.query(Workload).filter(Workload.cluster_id == cluster.id)
                    if (w.labels or {}).get(key) == value}
        rows = db.query(C.window_start, C.namespace, C.workload_kind, C.workload_name, func.sum(C.total_cost)) \
            .filter(*base, C.shared.is_(False)).group_by(C.window_start, C.namespace, C.workload_kind, C.workload_name)
        for ts, ns, wkind, wname, cost in rows:
            if (ns, wkind, wname) in matching:
                out[day_floor(ts)] += cost or 0.0
    return out


def daily_history(db: Session, cluster: Cluster, scope: str, days: int, now: datetime.datetime | None = None
                  ) -> list[tuple[datetime.datetime, float]]:
    """Complete UTC days only (today is still accruing), zero-filled from the
    first day with data."""
    now = now or utcnow()
    end = day_floor(now)
    kind, key, value = parse_scope(scope)
    by_day = costs_by_day(db, cluster, kind, key, value, end - days * DAY, end)
    if not by_day:
        return []
    # Drop leading partial days (e.g. the agent was installed at 14:00): a
    # half day looks like a cost drop and skews forecasts and baselines.
    hours = defaultdict(int)
    for (ts,) in db.query(CostAllocation.window_start).filter(
            CostAllocation.cluster_id == cluster.id, CostAllocation.window_start >= end - days * DAY,
            CostAllocation.window_start < end).distinct():
        hours[day_floor(ts)] += 1
    complete = sorted(d for d in by_day if hours.get(d, 0) >= 20)
    if not complete:
        return []
    first = complete[0]
    out, d = [], first
    while d < end:
        out.append((d, round(by_day.get(d, 0.0), 4)))
        d += DAY
    return out


def forecast_report(db: Session, cluster: Cluster, scope: str = "cluster", horizon: int = 30,
                    now: datetime.datetime | None = None) -> dict:
    now = now or utcnow()
    hist = daily_history(db, cluster, scope, 56, now)
    values = [v for _, v in hist]
    f = fc.forecast(values, horizon) if values else None
    today = day_floor(now)
    points = [] if f is None else [{"day": (today + (p["h"] - 1) * DAY).date().isoformat(), **p} for p in f.points]
    return {"scope": scope, "history": [{"day": d.date().isoformat(), "cost": v} for d, v in hist],
            "forecast": points, "method": f.method if f else None, "sigma": f.sigma if f else None,
            "backtest_mape_7d": fc.backtest_mape(values, 7) if values else None,
            "month_end": month_projection(db, cluster, scope, now, hist)}


def month_projection(db: Session, cluster: Cluster, scope: str, now: datetime.datetime,
                     hist: list | None = None) -> dict:
    """Actual month-to-date (all allocated hours, incl. today so far) plus the
    forecast for the rest of today and the remaining days."""
    kind, key, value = parse_scope(scope)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    actual_by_day = costs_by_day(db, cluster, kind, key, value, month_start, now)
    actual = sum(actual_by_day.values())
    hist = hist if hist is not None else daily_history(db, cluster, scope, 56, now)
    values = [v for _, v in hist]
    remaining_days = days_in_month - now.day          # whole days after today
    # Hours of today already allocated (allocation runs per completed hour).
    today_hours = len({ts for (ts,) in db.query(CostAllocation.window_start).filter(
        CostAllocation.cluster_id == cluster.id, CostAllocation.window_start >= day_floor(now),
        CostAllocation.window_start < now).distinct()})
    f = fc.forecast(values, remaining_days + 1) if values else None
    fc_points = f.points if f else []
    rest_of_today = fc_points[0]["value"] * (24 - today_hours) / 24 if fc_points else 0.0
    future = sum(p["value"] for p in fc_points[1:])
    half = sum(p["hi80"] - p["value"] for p in fc_points[1:])
    projected = actual + rest_of_today + future
    return {"month": month_start.strftime("%Y-%m"), "days_in_month": days_in_month,
            "actual_to_date": round(actual, 2), "forecast_remaining": round(rest_of_today + future, 2),
            "projected": round(projected, 2), "lo80": round(max(actual, projected - half), 2),
            "hi80": round(projected + half, 2), "method": f.method if f else None}


# --- budgets -------------------------------------------------------------------------


def budget_scope(b: Budget) -> str:
    if b.scope == "cluster":
        return "cluster"
    if b.scope == "namespace":
        return f"namespace:{b.scope_value}"
    return f"label:{b.scope_key}={b.scope_value}"


def budget_status(db: Session, b: Budget, now: datetime.datetime | None = None) -> dict:
    now = now or utcnow()
    cluster = db.get(Cluster, b.cluster_id)
    p = month_projection(db, cluster, budget_scope(b), now)
    pct_actual = p["actual_to_date"] / b.monthly_amount * 100 if b.monthly_amount else 0.0
    pct_projected = p["projected"] / b.monthly_amount * 100 if b.monthly_amount else 0.0
    state = "exceeded" if pct_actual >= 100 else "at_risk" if pct_projected >= 100 else "ok"
    return {"budget_id": b.id, "name": b.name, "scope": budget_scope(b), "monthly_amount": b.monthly_amount,
            **p, "pct_actual": round(pct_actual, 1), "pct_projected": round(pct_projected, 1), "state": state}


def evaluate_budgets(db: Session, now: datetime.datetime | None = None) -> int:
    """Fire each threshold at most once per budget per month."""
    now = now or utcnow()
    fired = 0
    for b in db.query(Budget).filter(Budget.enabled.is_(True)).all():
        if db.get(Cluster, b.cluster_id) is None:
            continue   # cluster deleted (cascade normally removes the budget too)
        s = budget_status(db, b, now)
        already = {(a.kind, a.threshold) for a in db.query(BudgetAlert).filter(
            BudgetAlert.budget_id == b.id, BudgetAlert.period == s["month"])}
        due = [("actual", t) for t in sorted(b.thresholds or []) if s["pct_actual"] >= t]
        if s["pct_projected"] >= 100 and s["pct_actual"] < 100:
            due.append(("forecast", 100))
        for kind, t in due:
            if (kind, t) in already:
                continue
            db.add(BudgetAlert(budget_id=b.id, period=s["month"], kind=kind, threshold=t,
                               actual=s["actual_to_date"], projected=s["projected"]))
            if kind == "actual":
                subject = f"Budget '{b.name}' reached {t}% ({s['pct_actual']:.0f}%)"
                text = (f"{s['scope']} has spent ${s['actual_to_date']:,.2f} of its ${b.monthly_amount:,.2f} "
                        f"monthly budget; projected month-end ${s['projected']:,.2f}.")
            else:
                subject = f"Budget '{b.name}' is forecast to be exceeded"
                text = (f"{s['scope']} is projected to spend ${s['projected']:,.2f} "
                        f"(80% range ${s['lo80']:,.2f}-${s['hi80']:,.2f}) against a ${b.monthly_amount:,.2f} budget.")
            notify.dispatch(db, "budget", subject, text,
                            {"Budget": b.name, "Scope": s["scope"], "Month": s["month"],
                             "Spent": f"${s['actual_to_date']:,.2f}", "Projected": f"${s['projected']:,.2f}",
                             "Link": f"{settings.public_url}/clusters/{b.cluster_id}/budgets/{b.id}"},
                            cluster_id=b.cluster_id)
            fired += 1
    db.commit()
    return fired


# --- anomalies -----------------------------------------------------------------------


def detect_cost_anomalies(db: Session, cluster: Cluster, now: datetime.datetime | None = None,
                          top_namespaces: int = 10, notify_days: int = 2) -> list[CostAnomaly]:
    now = now or utcnow()
    scopes = ["cluster"]
    C = CostAllocation
    since = day_floor(now) - 56 * DAY
    ns_rank = db.query(C.namespace, func.sum(C.total_cost)).filter(
        C.cluster_id == cluster.id, C.window_start >= since).group_by(C.namespace) \
        .order_by(func.sum(C.total_cost).desc()).limit(top_namespaces).all()
    scopes += [f"namespace:{ns}" for ns, _ in ns_rank]
    existing = {(a.scope, a.name, a.day) for a in db.query(CostAnomaly).filter(CostAnomaly.cluster_id == cluster.id)}
    new = []
    for scope in scopes:
        hist = daily_history(db, cluster, scope, 56, now)
        values = [v for _, v in hist]
        for an in fc.detect_anomalies(values, threshold=settings.anomaly_threshold,
                                      min_abs_delta=settings.anomaly_min_delta):
            day = hist[an.index][0]
            kind, name = ("cluster", cluster.name) if scope == "cluster" else ("namespace", scope.split(":", 1)[1])
            if (kind, name, day) in existing:
                continue
            row = CostAnomaly(cluster_id=cluster.id, scope=kind, name=name, day=day, actual=an.value,
                              expected=an.expected, delta=an.delta, score=an.score)
            db.add(row)
            new.append(row)
            if day >= day_floor(now) - notify_days * DAY:   # don't page people about last month
                direction = "above" if an.delta > 0 else "below"
                notify.dispatch(db, "anomaly", f"Cost anomaly: {kind} {name} on {day.date()}",
                                f"Spent ${an.value:,.2f}, ${abs(an.delta):,.2f} {direction} the expected "
                                f"${an.expected:,.2f} (robust z = {an.score:.1f}).",
                                {"Cluster": cluster.name, "Scope": f"{kind}/{name}", "Day": str(day.date())},
                                cluster_id=cluster.id)
    db.commit()
    return new


def run_finance(db: Session, now: datetime.datetime | None = None) -> dict:
    anomalies = 0
    for cluster in db.query(Cluster).filter(Cluster.is_active.is_(True)).all():
        try:
            anomalies += len(detect_cost_anomalies(db, cluster, now))
        except Exception:
            db.rollback()
            logger.exception("Anomaly detection failed for %s", cluster.name)
    try:
        alerts = evaluate_budgets(db, now)
    except Exception:
        db.rollback()
        logger.exception("Budget evaluation failed")
        alerts = 0
    return {"anomalies": anomalies, "budget_alerts": alerts}
