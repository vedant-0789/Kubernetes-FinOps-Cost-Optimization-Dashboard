"""Alert delivery to Slack, generic webhooks and email.

Delivery never raises into the caller: every attempt is logged in the
``notifications`` table with its outcome, so a broken Slack URL can't stop a
budget evaluation or a rollback.
"""

import logging
import smtplib
from email.message import EmailMessage

import httpx
from prometheus_client import Counter
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.platform_models import Notification, NotificationChannel

logger = logging.getLogger("notify")
SENT = Counter("finops_notifications_total", "Notification attempts", ["type", "status"])
EVENT_TYPES = ("budget", "anomaly", "remediation")

_http = httpx.Client(timeout=10.0)  # replaced in tests


def _slack(url: str, subject: str, text: str, fields: dict) -> None:
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": subject[:150]}},
              {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]
    if fields:
        blocks.append({"type": "section", "fields": [{"type": "mrkdwn", "text": f"*{k}*\n{v}"}
                                                    for k, v in list(fields.items())[:10]]})
    r = _http.post(url, json={"text": f"{subject}\n{text}", "blocks": blocks})
    r.raise_for_status()


def _webhook(url: str, event_type: str, subject: str, text: str, fields: dict) -> None:
    r = _http.post(url, json={"source": "kubefinops", "event": event_type, "subject": subject, "text": text,
                              "data": fields})
    r.raise_for_status()


def _email(to: list[str], subject: str, text: str, fields: dict) -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP is not configured (FINOPS_SMTP_HOST)")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = f"[KubeFinOps] {subject}", settings.smtp_from, ", ".join(to)
    msg.set_content(text + ("\n\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) if fields else ""))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)


def deliver(db: Session, channel: NotificationChannel, event_type: str, subject: str, text: str,
            fields: dict | None = None, cluster_id: str | None = None) -> Notification:
    fields = fields or {}
    status, error = "sent", None
    try:
        if channel.type == "slack":
            _slack(channel.config["url"], subject, text, fields)
        elif channel.type == "webhook":
            _webhook(channel.config["url"], event_type, subject, text, fields)
        elif channel.type == "email":
            _email(channel.config["to"], subject, text, fields)
        else:
            raise ValueError(f"unknown channel type {channel.type}")
    except Exception as exc:
        status, error = "failed", f"{exc.__class__.__name__}: {exc}"[:1000]
        logger.warning("Notification via %s failed: %s", channel.name, error)
    SENT.labels(channel.type, status).inc()
    n = Notification(channel_id=channel.id, event_type=event_type, cluster_id=cluster_id, subject=subject,
                     payload={"text": text, "fields": fields}, status=status, error=error)
    db.add(n)
    db.flush()
    return n


def dispatch(db: Session, event_type: str, subject: str, text: str, fields: dict | None = None,
             cluster_id: str | None = None) -> list[Notification]:
    """Send to every enabled channel subscribed to this event (and cluster)."""
    q = db.query(NotificationChannel).filter(NotificationChannel.enabled.is_(True))
    if cluster_id:
        q = q.filter(or_(NotificationChannel.cluster_id.is_(None), NotificationChannel.cluster_id == cluster_id))
    return [deliver(db, ch, event_type, subject, text, fields, cluster_id)
            for ch in q.all() if event_type in (ch.events or [])]


def masked_config(channel: NotificationChannel) -> dict:
    """Webhook URLs are credentials: never return them in full."""
    cfg = dict(channel.config or {})
    if "url" in cfg:
        url = cfg["url"]
        cfg["url"] = url[:24] + "..." + url[-4:] if len(url) > 32 else "***"
    return cfg
