import json
import os
import smtplib
import sys
import warnings
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
import sqlite_utils
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from database import init_alert_log, get_unfired_alerts, log_alert_fired

# ── emoji / colour maps ───────────────────────────────────────────────────────
ALERT_EMOJI = {
    "sentiment_drop": "🔴",
    "sentiment_rise": "🟢",
    "volume_spike":   "🟡",
}
ALERT_LABEL = {
    "sentiment_drop": "Sentiment Drop",
    "sentiment_rise": "Sentiment Rise",
    "volume_spike":   "Volume Spike",
}
HEADER_COLOUR = {
    "sentiment_drop": "#C0392B",
    "sentiment_rise": "#27AE60",
    "volume_spike":   "#E67E22",
}


def get_top_mentions(db, alert: dict, n: int = 3) -> list:
    """
    Find the most relevant mentions for an alert.
    Looks within 3 days of the alert date for the matching aspect.
    """
    try:
        alert_date = datetime.strptime(alert["date"], "%Y-%m-%d")
    except Exception:
        return []

    date_from = (alert_date - timedelta(days=1)).strftime("%Y-%m-%d")
    date_to   = (alert_date + timedelta(days=2)).strftime("%Y-%m-%d")

    aspect = alert.get("aspect", "overall")

    try:
        if aspect == "overall":
            rows = list(db.execute(
                """
                SELECT sm.original_text, sm.sentiment, sm.confidence
                FROM scored_mentions sm
                WHERE sm.brand   = ?
                  AND DATE(sm.timestamp) BETWEEN ? AND ?
                  AND sm.sentiment IN ('NEGATIVE', 'POSITIVE')
                ORDER BY sm.confidence DESC
                LIMIT ?
                """,
                [alert["brand"], date_from, date_to, n],
            ).fetchall())
        else:
            rows = list(db.execute(
                """
                SELECT sm.original_text, sm.sentiment, sm.confidence
                FROM scored_mentions sm
                WHERE sm.brand  = ?
                  AND sm.aspect = ?
                  AND DATE(sm.timestamp) BETWEEN ? AND ?
                ORDER BY sm.confidence DESC
                LIMIT ?
                """,
                [alert["brand"], aspect, date_from, date_to, n],
            ).fetchall())
    except Exception as e:
        print(f"  get_top_mentions error: {e}")
        return []

    return [
        f"{row[1]}: {row[0][:120]}{'...' if len(row[0]) > 120 else ''}"
        for row in rows
    ]


def format_slack_message(alert: dict, top_mentions: list, health_score_info: dict | None) -> dict:
    """Build a Slack Block Kit message dict for an alert."""
    type_config = {
        "sentiment_drop": {"emoji": "🔴", "label": "Sentiment Drop"},
        "sentiment_rise": {"emoji": "🟢", "label": "Sentiment Rise"},
        "volume_spike":   {"emoji": "🟡", "label": "Volume Spike"},
    }
    cfg    = type_config.get(alert["alert_type"], {"emoji": "⚪", "label": alert["alert_type"]})
    sev    = (alert.get("severity") or "medium").upper()
    aspect = (alert.get("aspect") or "overall").upper()
    z      = alert.get("z_score", 0)
    score  = alert.get("score", 0)
    mean   = alert.get("baseline_mean", 0)
    n      = alert.get("mention_count", 0)

    hs_text = ""
    if health_score_info:
        hs      = health_score_info.get("health_score", 0)
        hs_text = f"  |  Brand health: *{hs:.0f}/100*"

    mentions_text = "\n".join(f"• {m}" for m in top_mentions) \
        if top_mentions else "_No mentions found for this period_"

    blocks = [
        {
            "type": "header",
            "text": {
                "type":  "plain_text",
                "text":  f"{cfg['emoji']} {cfg['label']} — {alert['brand']} / {aspect}  [{sev}]",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Date*\n{alert['date']}"},
                {"type": "mrkdwn", "text": f"*Aspect*\n{aspect}"},
                {"type": "mrkdwn", "text": f"*Score*\n{score:+.3f} (baseline {mean:+.3f})"},
                {"type": "mrkdwn", "text": f"*Z-score*\n{z:+.2f}  |  N={n}{hs_text}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top mentions around this date:*\n{mentions_text}"},
        },
    ]

    return {"blocks": blocks}


def send_slack(webhook_url: str, message_dict: dict) -> bool:
    """Post a Block Kit message to Slack. Returns True on success."""
    if not webhook_url:
        print("  Slack: no webhook URL configured — skipping")
        return False
    try:
        r = requests.post(webhook_url, json=message_dict, timeout=10)
        if r.status_code == 200:
            print("  Slack: sent OK")
            return True
        print(f"  Slack: failed {r.status_code} — {r.text[:80]}")
        return False
    except Exception as e:
        print(f"  Slack: exception — {e}")
        return False


def format_email(alert: dict, top_mentions: list, health_score_info: dict | None) -> str:
    """Build an HTML email body for an alert."""
    color_map = {
        "sentiment_drop": "#D32F2F",
        "sentiment_rise": "#388E3C",
        "volume_spike":   "#F57C00",
    }
    color  = color_map.get(alert["alert_type"], "#555555")
    aspect = (alert.get("aspect") or "overall").upper()
    z      = alert.get("z_score", 0)
    score  = alert.get("score", 0)
    mean   = alert.get("baseline_mean", 0)
    n      = alert.get("mention_count", 0)
    sev    = (alert.get("severity") or "medium").upper()

    hs_row = ""
    if health_score_info:
        hs     = health_score_info.get("health_score", 0)
        hs_row = f"<tr><td><b>Brand health</b></td><td>{hs:.0f}/100</td></tr>"

    mentions_html = "".join(
        f"<li style='margin-bottom:8px'>{m}</li>"
        for m in top_mentions
    ) if top_mentions else "<li>No mentions found for this period</li>"

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <div style="background:{color};color:white;padding:16px 20px;border-radius:6px 6px 0 0">
        <h2 style="margin:0">
          {alert['alert_type'].replace('_', ' ').title()} —
          {alert['brand']} / {aspect}
        </h2>
        <p style="margin:4px 0 0;opacity:0.9">Severity: {sev}</p>
      </div>
      <div style="border:1px solid #ddd;border-top:none;padding:20px;border-radius:0 0 6px 6px">
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
          <tr><td style="padding:6px 0;color:#555"><b>Date</b></td>
              <td>{alert['date']}</td></tr>
          <tr><td style="padding:6px 0;color:#555"><b>Aspect</b></td>
              <td>{aspect}</td></tr>
          <tr><td style="padding:6px 0;color:#555"><b>Score</b></td>
              <td>{score:+.3f} &nbsp;(baseline {mean:+.3f})</td></tr>
          <tr><td style="padding:6px 0;color:#555"><b>Z-score</b></td>
              <td>{z:+.2f} &nbsp;(N={n})</td></tr>
          {hs_row}
        </table>
        <h3 style="color:#333;margin-bottom:8px">Top mentions</h3>
        <ul style="padding-left:20px;color:#444;line-height:1.6">
          {mentions_html}
        </ul>
        <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
        <p style="color:#999;font-size:12px;margin:0">
          Brand Reputation Pipeline — automated alert
        </p>
      </div>
    </body></html>
    """


def send_email(alert: dict, html_body: str, cfg: dict) -> bool:
    """Send an HTML email alert via SMTP. Returns True on success."""
    if not cfg.get("email_from") or not cfg.get("email_password"):
        return False  # silently skip — email is optional channel

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"[{(alert.get('severity') or '').upper()}] "
            f"{alert['alert_type'].replace('_', ' ').title()} — "
            f"{alert['brand']} / {(alert.get('aspect') or '').upper()}"
        )
        msg["From"] = cfg["email_from"]
        msg["To"]   = cfg["email_to"]
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["email_from"], cfg["email_password"])
            server.sendmail(cfg["email_from"], cfg["email_to"], msg.as_string())

        print("  Email: sent OK")
        return True

    except Exception as e:
        print(f"  Email: failed — {e}")
        return False


def run_alert_engine(db_path: str, brand_name: str) -> None:
    """
    Main alert pipeline:
    1. Get unfired alerts from DB
    2. Enrich with mentions and health score
    3. Fire Slack + email
    4. Log results for deduplication
    """
    from analytics.health_score import get_current_score
    from config import (SLACK_WEBHOOK_URL, ALERT_EMAIL_FROM,
                        ALERT_EMAIL_TO, ALERT_EMAIL_PASSWORD,
                        SMTP_HOST, SMTP_PORT)

    db = sqlite_utils.Database(db_path)
    init_alert_log(db)

    unfired = get_unfired_alerts(db, brand_name, lookback_hours=24)
    print(f"Unfired alerts: {len(unfired)}")

    if not unfired:
        print("  Nothing to send — all alerts already fired "
              "within the last 24 hours")
        return

    health_info = get_current_score(db_path, brand_name)
    email_cfg   = {
        "email_from":     ALERT_EMAIL_FROM,
        "email_to":       ALERT_EMAIL_TO,
        "email_password": ALERT_EMAIL_PASSWORD,
        "smtp_host":      SMTP_HOST,
        "smtp_port":      SMTP_PORT,
    }

    sent_slack = sent_email = failed = 0

    for alert in unfired:
        print(f"\nProcessing: {alert['alert_type']} / "
              f"{alert['aspect']} / {alert['date']} "
              f"[{alert['severity']}]")

        top_mentions = get_top_mentions(db, alert, n=3)
        print(f"  Found {len(top_mentions)} example mentions")

        # Slack
        slack_msg = format_slack_message(alert, top_mentions, health_info)
        slack_ok  = send_slack(SLACK_WEBHOOK_URL, slack_msg)
        log_alert_fired(
            db, alert["id"], brand_name, "slack",
            "sent" if slack_ok else "failed",
        )
        if slack_ok:
            sent_slack += 1

        # Email
        email_html = format_email(alert, top_mentions, health_info)
        email_ok   = send_email(alert, email_html, email_cfg)
        log_alert_fired(
            db, alert["id"], brand_name, "email",
            "sent" if email_ok else "failed",
            error_msg="" if email_ok else "check credentials",
        )
        if email_ok:
            sent_email += 1

        if not slack_ok and not email_ok:
            failed += 1

    print(f"\nAlert engine complete:")
    print(f"  Alerts processed : {len(unfired)}")
    print(f"  Slack sent       : {sent_slack}")
    print(f"  Email sent       : {sent_email}")
    print(f"  Failed (both)    : {failed}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    from config import BRAND_NAME, DB_PATH

    print("=" * 60)
    print(f"Alert Engine | Brand: {BRAND_NAME}")
    print("=" * 60)

    run_alert_engine(DB_PATH, BRAND_NAME)
