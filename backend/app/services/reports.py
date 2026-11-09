"""Showback / chargeback reports for a calendar month (CSV and PDF).

The totals are exactly the allocation report's: rows + shared + idle = bill,
so finance can reconcile a chargeback invoice with the cloud bill.
"""

import csv
import datetime
import io
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.platform_models import Cluster, RightsizingRecommendation, WasteFinding, utcnow
from app.services.allocation_query import IDLE, SHARED, allocation_report

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def month_period(month: str | None, now: datetime.datetime | None = None) -> tuple[datetime.datetime,
                                                                                    datetime.datetime, str]:
    now = now or utcnow()
    if month is None:
        month = now.strftime("%Y-%m")
    m = _MONTH.match(month)
    if not m:
        raise HTTPException(422, "month must be YYYY-MM")
    start = datetime.datetime(int(m.group(1)), int(m.group(2)), 1)
    end = datetime.datetime(start.year + (start.month == 12), start.month % 12 + 1, 1)
    if start > now:
        raise HTTPException(422, "month is in the future")
    return start, min(end, now.replace(minute=0, second=0, microsecond=0)), month


def showback(db: Session, cluster: Cluster, month: str | None, aggregate: str, shared: str,
             include_idle: bool, now: datetime.datetime | None = None) -> dict:
    start, end, label = month_period(month, now)
    rep = allocation_report(db, cluster, "", aggregate, shared, include_idle, period=(start, end))
    rows = []
    for i in rep.items:
        rows.append({"name": i.name, "cpu_cost": round(i.cpu_cost, 2), "ram_cost": round(i.ram_cost, 2),
                     "shared_cost": round(i.shared_cost_added, 2), "total_cost": round(i.total_cost, 2),
                     "share_pct": round(i.total_cost / rep.total_cost * 100, 2) if rep.total_cost else 0.0,
                     "cpu_core_hours": i.cpu_core_hours, "ram_gib_hours": i.ram_gib_hours,
                     "efficiency_pct": round(i.efficiency * 100, 1)})
    return {"cluster": cluster.name, "month": label, "period_start": start, "period_end": end,
            "aggregate": aggregate, "shared_mode": shared, "total_cost": round(rep.total_cost, 2),
            "allocated_cost": round(rep.allocated_cost, 2), "idle_cost": round(rep.idle_cost, 2),
            "shared_cost": round(rep.shared_cost, 2), "efficiency_pct": round(rep.efficiency * 100, 1), "rows": rows}


CSV_COLUMNS = ["name", "cpu_cost", "ram_cost", "shared_cost", "total_cost", "share_pct", "cpu_core_hours",
               "ram_gib_hours", "efficiency_pct"]


def showback_csv(report: dict) -> str:
    buf = io.StringIO()
    buf.write(f"# KubeFinOps showback - cluster {report['cluster']} - {report['month']} "
              f"({report['period_start']:%Y-%m-%d} to {report['period_end']:%Y-%m-%d %H:%M} UTC)\n")
    buf.write(f"# grouped by {report['aggregate']}; shared costs: {report['shared_mode']}; USD\n")
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in report["rows"]:
        w.writerow(r)
    w.writerow({"name": "TOTAL", "total_cost": report["total_cost"], "share_pct": 100.0})
    return buf.getvalue()


def showback_pdf(db: Session, cluster: Cluster, report: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"KubeFinOps showback {report['month']}")
    money = "${:,.2f}".format
    story = [
        Paragraph(f"Kubernetes cost report - {report['cluster']}", styles["Title"]),
        Paragraph(f"{report['month']} &nbsp;|&nbsp; {report['period_start']:%d %b %Y} - "
                  f"{report['period_end']:%d %b %Y %H:%M} UTC &nbsp;|&nbsp; grouped by "
                  f"<b>{report['aggregate']}</b>, shared costs {report['shared_mode']}d", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    summary = [["Total bill", "Allocated", "Shared", "Idle", "Efficiency"],
               [money(report["total_cost"]), money(report["allocated_cost"]), money(report["shared_cost"]),
                money(report["idle_cost"]), f"{report['efficiency_pct']:.0f}%"]]
    t = Table(summary, hAlign="LEFT")
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 1), (-1, 1), 13),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [t, Spacer(1, 6 * mm), Paragraph("Cost by " + report["aggregate"], styles["Heading2"])]

    def label(name: str) -> str:
        return {IDLE: "Idle capacity", SHARED: "Shared (platform)"}.get(name, name)

    rows = [["", "CPU", "Memory", "Shared", "Total", "Share", "Efficiency"]]
    for r in report["rows"]:
        rows.append([label(r["name"]), money(r["cpu_cost"]), money(r["ram_cost"]), money(r["shared_cost"]),
                     money(r["total_cost"]), f"{r['share_pct']:.1f}%", f"{r['efficiency_pct']:.0f}%"])
    rows.append(["Total", "", "", "", money(report["total_cost"]), "100%", ""])
    t = Table(rows, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.whitesmoke]),
    ]))
    story += [t, Spacer(1, 6 * mm)]

    recs = db.query(RightsizingRecommendation).filter(
        RightsizingRecommendation.cluster_id == cluster.id, RightsizingRecommendation.status == "open",
        RightsizingRecommendation.action == "downsize").order_by(
        RightsizingRecommendation.monthly_savings.desc()).limit(8).all()
    waste = db.query(WasteFinding).filter(WasteFinding.cluster_id == cluster.id, WasteFinding.status == "open") \
        .order_by(WasteFinding.monthly_savings.desc()).limit(8).all()
    if recs or waste:
        story.append(Paragraph("Top savings opportunities", styles["Heading2"]))
        opp = [["Opportunity", "Target", "Saving / month"]]
        opp += [["Right-size", f"{r.namespace}/{r.workload_name}", money(r.monthly_savings)] for r in recs]
        opp += [[w.kind.replace("_", " ").title(), f"{w.namespace + '/' if w.namespace else ''}{w.name}",
                 money(w.monthly_savings)] for w in waste]
        t = Table(opp, hAlign="LEFT", repeatRows=1)
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black)]))
        story.append(t)
    story += [Spacer(1, 8 * mm), Paragraph(
        "Costs follow the OpenCost model: containers pay for max(request, usage) at their node's unit prices; "
        "unreserved node capacity is idle cost. Generated by KubeFinOps.", styles["Italic"])]
    doc.build(story)
    return buf.getvalue()
