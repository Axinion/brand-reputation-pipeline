import warnings
warnings.filterwarnings("ignore")

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

import sqlite_utils
from groq import Groq


# ── Data extraction ───────────────────────────────────────────────────

def build_data_summary(db_path, brand_name, days_back=7):
    """
    Pull all relevant data from the DB and return as a structured dict.
    This dict becomes the factual basis for the LLM report.
    """
    db = sqlite_utils.Database(db_path)

    cutoff = (datetime.now(tz=timezone.utc)
              - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # current health score
    try:
        score_row = next(db.execute('''
            SELECT date, health_score, smoothed_score, dominant_aspect
            FROM brand_health_scores
            WHERE brand = ?
            ORDER BY date DESC LIMIT 1
        ''', [brand_name]))
        current_score   = round(score_row[1], 1)
        smoothed_score  = round(score_row[2], 1)
        dominant_aspect = score_row[3]
        latest_date     = score_row[0]
    except StopIteration:
        current_score   = 50.0
        smoothed_score  = 50.0
        dominant_aspect = "unknown"
        latest_date     = datetime.now().strftime("%Y-%m-%d")

    # week-over-week trend
    try:
        prev_row = next(db.execute('''
            SELECT smoothed_score
            FROM brand_health_scores
            WHERE brand = ?
            ORDER BY date DESC LIMIT 1 OFFSET 7
        ''', [brand_name]))
        health_trend = round(smoothed_score - prev_row[0], 1)
    except StopIteration:
        health_trend = 0.0

    # aspect breakdown for last 7 days
    aspect_rows = list(db.execute('''
        SELECT aspect,
               ROUND(AVG(avg_score), 3)    AS avg_score,
               SUM(mention_count)          AS total_n,
               ROUND(AVG(positive_pct), 1) AS pos_pct,
               ROUND(AVG(negative_pct), 1) AS neg_pct
        FROM brand_health_daily
        WHERE brand = ? AND date >= ?
        GROUP BY aspect
        ORDER BY avg_score DESC
    ''', [brand_name, cutoff]).fetchall())

    aspect_scores = {
        r[0]: {
            "avg_score":    r[1],
            "mentions":     int(r[2]),
            "positive_pct": r[3],
            "negative_pct": r[4],
        }
        for r in aspect_rows
        if r[0] != "overall"
    }

    # recent alerts
    alert_rows = list(db.execute('''
        SELECT alert_type, aspect, date, z_score, severity
        FROM alerts
        WHERE brand = ? AND date >= ?
        ORDER BY ABS(z_score) DESC LIMIT 5
    ''', [brand_name, cutoff]).fetchall())

    top_alerts = [
        {
            "type":     r[0],
            "aspect":   r[1],
            "date":     r[2],
            "z_score":  round(r[3], 2),
            "severity": r[4],
        }
        for r in alert_rows
    ]

    # top negative mentions
    neg_rows = list(db.execute('''
        SELECT original_text, aspect
        FROM scored_mentions
        WHERE brand = ? AND sentiment = "NEGATIVE"
        AND aspect != "overall"
        AND DATE(timestamp) >= ?
        ORDER BY confidence DESC LIMIT 5
    ''', [brand_name, cutoff]).fetchall())
    top_negative = [
        f"[{r[1]}] {r[0][:150]}" for r in neg_rows
    ]

    # top positive mentions
    pos_rows = list(db.execute('''
        SELECT original_text, aspect
        FROM scored_mentions
        WHERE brand = ? AND sentiment = "POSITIVE"
        AND aspect != "overall"
        AND DATE(timestamp) >= ?
        ORDER BY confidence DESC LIMIT 5
    ''', [brand_name, cutoff]).fetchall())
    top_positive = [
        f"[{r[1]}] {r[0][:150]}" for r in pos_rows
    ]

    # mention counts by source
    source_rows = list(db.execute('''
        SELECT source, COUNT(*) as n
        FROM raw_mentions
        WHERE brand = ?
        GROUP BY source
    ''', [brand_name]).fetchall())
    mention_counts = {r[0]: r[1] for r in source_rows}

    return {
        "brand":           brand_name,
        "date_range":      {"start": cutoff, "end": latest_date},
        "current_score":   current_score,
        "smoothed_score":  smoothed_score,
        "health_trend":    health_trend,
        "dominant_aspect": dominant_aspect,
        "aspect_scores":   aspect_scores,
        "top_alerts":      top_alerts,
        "top_negative":    top_negative,
        "top_positive":    top_positive,
        "mention_counts":  mention_counts,
    }


# ── Prompt builder ────────────────────────────────────────────────────

def build_prompt(data, brand_name):
    """
    Build the LLM prompt from the data summary dict.
    Structured to produce a consistent, actionable report.
    """
    trend_word = (
        "improving" if data["health_trend"] > 1
        else "declining" if data["health_trend"] < -1
        else "stable"
    )
    trend_str = (
        f"{data['health_trend']:+.1f} points week-over-week ({trend_word})"
    )

    # format aspect scores — worst first so the LLM leads with problems
    aspect_lines = []
    for aspect, vals in sorted(
        data["aspect_scores"].items(),
        key=lambda x: x[1]["avg_score"]
    ):
        aspect_lines.append(
            f"  - {aspect.upper():10}: score {vals['avg_score']:+.3f} | "
            f"{vals['mentions']} mentions | "
            f"{vals['positive_pct']}% positive / "
            f"{vals['negative_pct']}% negative"
        )
    aspects_block = "\n".join(aspect_lines) if aspect_lines \
        else "  No aspect data available"

    # format alerts
    if data["top_alerts"]:
        alert_lines = [
            f"  - {a['type']} on {a['aspect'].upper()} "
            f"({a['date']}, z={a['z_score']:+.2f}, {a['severity']} severity)"
            for a in data["top_alerts"]
        ]
        alerts_block = "\n".join(alert_lines)
    else:
        alerts_block = "  No significant alerts this period"

    # format mentions
    neg_block = "\n".join(
        f"  {i+1}. {m}" for i, m in enumerate(data["top_negative"])
    ) if data["top_negative"] else "  None recorded"

    pos_block = "\n".join(
        f"  {i+1}. {m}" for i, m in enumerate(data["top_positive"])
    ) if data["top_positive"] else "  None recorded"

    prompt = f"""You are a brand intelligence analyst. Write a concise, professional weekly brand health report based on the following data. Use the actual numbers. Be specific. Do not invent data that is not in the input.

BRAND: {brand_name}
REPORT PERIOD: {data['date_range']['start']} to {data['date_range']['end']}

OVERALL HEALTH SCORE: {data['current_score']:.1f}/100
7-DAY SMOOTHED SCORE: {data['smoothed_score']:.1f}/100
TREND: {trend_str}
DOMINANT CONCERN: {data['dominant_aspect'].upper()}

ASPECT SCORES (last 7 days):
{aspects_block}

STATISTICAL ALERTS DETECTED:
{alerts_block}

REPRESENTATIVE NEGATIVE MENTIONS:
{neg_block}

REPRESENTATIVE POSITIVE MENTIONS:
{pos_block}

MENTION VOLUME BY SOURCE:
{chr(10).join(f"  - {src}: {n} mentions" for src, n in data['mention_counts'].items())}

---

Write the report in exactly this structure:

## Executive Summary
One paragraph (3-4 sentences). State the overall health score, the trend direction, and the single most important issue this week. Reference the score number directly.

## Aspect Analysis
For each aspect that appears in the data above, write 2-3 sentences covering: the score, what the positive and negative mentions reveal, and whether this is better or worse than expected.

## Alerts and Anomalies
Describe each statistical alert detected. Explain what a z-score spike means in plain English for a non-technical reader.

## Recommended Actions
List exactly 3 specific, actionable recommendations. Each must reference the data directly. Format as:
1. [Action]: [Rationale with specific number]
2. [Action]: [Rationale with specific number]
3. [Action]: [Rationale with specific number]

## Outlook
One sentence predicting the brand health trajectory for next week based on current trends.

Write in a professional but direct tone. No filler phrases like "it is worth noting" or "it is important to consider". Every sentence should contain information."""

    return prompt


# ── Groq API call ─────────────────────────────────────────────────────

def call_groq(prompt, model, api_key, max_tokens=1500):
    """
    Call the Groq API and return the response text.
    Handles rate limits and API errors gracefully.
    """
    import time
    from groq import RateLimitError

    client = Groq(api_key=api_key)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role":    "system",
                        "content": (
                            "You are a professional brand intelligence analyst. "
                            "Write clear, data-driven reports. "
                            "Always reference specific numbers from the data provided. "
                            "Never invent data."
                        ),
                    },
                    {
                        "role":    "user",
                        "content": prompt,
                    },
                ],
                max_tokens=max_tokens,
                temperature=0.3,   # low temperature = more factual, less creative
            )
            return response.choices[0].message.content.strip()

        except RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"  Rate limited — waiting {wait}s before retry {attempt+1}/3")
            time.sleep(wait)

        except Exception as e:
            print(f"  Groq API error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return f"Report generation failed after 3 attempts: {e}"
            time.sleep(5)

    return "Report generation failed — all retries exhausted"


# ── Report saving ─────────────────────────────────────────────────────

def save_report(report_text, brand_name, output_dir="reports/output"):
    """
    Save the report as plain text and wrapped HTML.
    Returns paths to both files.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    date_str  = datetime.now().strftime("%Y-%m-%d")
    safe_name = brand_name.lower().replace(" ", "_")

    # plain text
    txt_path = out / f"{safe_name}_report_{date_str}.txt"
    txt_path.write_text(report_text, encoding="utf-8")

    # HTML wrap — Day 17 will replace this with a full Jinja2 template
    html_body = report_text.replace("\n\n", "</p><p>").replace("\n", "<br>")
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{brand_name} Brand Health Report — {date_str}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      max-width: 800px; margin: 40px auto; padding: 0 24px;
      color: #1a1a1a; line-height: 1.7;
    }}
    h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 4px; }}
    .meta {{ color: #666; font-size: 14px; margin-bottom: 32px; }}
    h2 {{ font-size: 18px; font-weight: 600; margin-top: 32px;
          border-bottom: 1px solid #eee; padding-bottom: 8px; }}
    p {{ margin: 12px 0; }}
    .footer {{ margin-top: 48px; padding-top: 16px;
               border-top: 1px solid #eee; color: #999; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>{brand_name} Brand Health Report</h1>
  <div class="meta">Generated: {date_str} &nbsp;|&nbsp;
       Powered by Brand Reputation Pipeline</div>
  <p>{html_body}</p>
  <div class="footer">
    Data sources: Reddit, NewsAPI, Google Play &nbsp;|&nbsp;
    NLP: PyABSA + distilBERT &nbsp;|&nbsp;
    LLM: Groq ({os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")})
  </div>
</body>
</html>"""

    html_path = out / f"{safe_name}_report_{date_str}.html"
    html_path.write_text(html_content, encoding="utf-8")

    return {"txt": str(txt_path), "html": str(html_path)}


# ── Main orchestrator ─────────────────────────────────────────────────

def run_report_generator(db_path, brand_name, output_dir="outputs"):
    """Full report generation pipeline."""
    import warnings
    warnings.filterwarnings("ignore")

    from config import GROQ_API_KEY, GROQ_MODEL

    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY not set in .env")
        return None

    print(f"Building data summary for {brand_name}...")
    data = build_data_summary(db_path, brand_name, days_back=7)

    print(f"  Health score : {data['current_score']:.1f}/100")
    print(f"  Trend        : {data['health_trend']:+.1f} pts")
    print(f"  Alerts       : {len(data['top_alerts'])}")
    print(f"  Neg mentions : {len(data['top_negative'])}")

    print(f"\nBuilding prompt...")
    prompt = build_prompt(data, brand_name)
    print(f"  Prompt length: {len(prompt)} chars")

    print(f"\nCalling Groq API ({GROQ_MODEL})...")
    report_text = call_groq(prompt, GROQ_MODEL, GROQ_API_KEY)
    print(f"  Report length: {len(report_text)} chars")

    print(f"\nSaving report...")
    paths = save_report(report_text, brand_name, output_dir)
    print(f"  Text : {paths['txt']}")
    print(f"  HTML : {paths['html']}")

    print(f"\n{'='*60}")
    print(f"GENERATED REPORT")
    print(f"{'='*60}")
    print(report_text)
    print(f"{'='*60}")

    return paths


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    from config import BRAND_NAME, DB_PATH

    print("=" * 60)
    print(f"Report Generator | Brand: {BRAND_NAME}")
    print("=" * 60)

    paths = run_report_generator(
        db_path=DB_PATH,
        brand_name=BRAND_NAME,
        output_dir="outputs",
    )
    if paths:
        print(f"\nOpen your report:")
        print(f"  open {paths['html']}")
