import warnings
warnings.filterwarnings("ignore")

import sys
import os
import re
import html
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinja2 import Environment, FileSystemLoader
from reports.chart_generator import (
    chart_health_trend,
    chart_aspect_bars,
    chart_sentiment_donut,
)


ASPECT_COLORS = {
    "quality":  "#1D9E75",
    "ux":       "#534AB7",
    "price":    "#D85A30",
    "support":  "#BA7517",
    "delivery": "#185FA5",
    "overall":  "#888780",
}


def _score_color(score):
    """Return a hex color based on health score value."""
    if score >= 65:
        return "#1D9E75"   # green
    elif score >= 45:
        return "#BA7517"   # amber
    else:
        return "#D85A30"   # red


def _trend_class(trend):
    if trend > 1:
        return "trend-up"
    elif trend < -1:
        return "trend-down"
    return "trend-flat"


def _trend_arrow(trend):
    if trend > 1:
        return "↑"
    elif trend < -1:
        return "↓"
    return "→"


def load_score_history(db_path, brand_name):
    """Load full score history for the trend chart."""
    import sqlite_utils
    db   = sqlite_utils.Database(db_path)
    rows = list(db.execute('''
        SELECT date, health_score, smoothed_score
        FROM brand_health_scores
        WHERE brand = ?
        ORDER BY date ASC
    ''', [brand_name]).fetchall())
    return [
        {"date": r[0], "health_score": r[1], "smoothed_score": r[2]}
        for r in rows
    ]


def compute_sentiment_totals(db_path, brand_name, days_back=7):
    """Compute positive/negative/neutral totals for the donut chart."""
    import sqlite_utils
    from datetime import timedelta
    db     = sqlite_utils.Database(db_path)
    cutoff = (datetime.now(tz=timezone.utc)
              - timedelta(days=days_back)).strftime("%Y-%m-%d")

    rows = list(db.execute('''
        SELECT sentiment, COUNT(*) as n
        FROM scored_mentions
        WHERE brand = ? AND DATE(timestamp) >= ?
        GROUP BY sentiment
    ''', [brand_name, cutoff]).fetchall())

    counts = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    for r in rows:
        counts[r[0]] = r[1]
    return counts


def markdown_to_html(md_text):
    """
    Convert a constrained markdown subset to safe HTML.
    Supports: ## headings, bold (**text**), ordered and unordered lists.
    """
    if not md_text:
        return "<p>No analysis generated.</p>"

    def _inline(text):
        escaped = html.escape(text)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)

    lines = md_text.splitlines()
    out = []
    in_ol = False
    in_ul = False
    para = []

    def flush_para():
        nonlocal para
        if para:
            out.append(f"<p>{_inline(' '.join(para).strip())}</p>")
            para = []

    def close_lists():
        nonlocal in_ol, in_ul
        if in_ol:
            out.append("</ol>")
            in_ol = False
        if in_ul:
            out.append("</ul>")
            in_ul = False

    for raw in lines:
        line = raw.strip()

        if not line:
            flush_para()
            close_lists()
            continue

        if line.startswith("## "):
            flush_para()
            close_lists()
            out.append(f"<h2>{_inline(line[3:].strip())}</h2>")
            continue

        ol_match = re.match(r"^(\d+)\.\s+(.*)$", line)
        if ol_match:
            flush_para()
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(ol_match.group(2))}</li>")
            continue

        if line.startswith("- "):
            flush_para()
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(line[2:].strip())}</li>")
            continue

        para.append(line)

    flush_para()
    close_lists()
    return "\n".join(out)


def render_report(data_summary, llm_report, db_path,
                  brand_name, output_dir="outputs"):
    """
    Render the full HTML report using the Jinja2 template.
    Returns path to the output HTML file.
    """
    from dotenv import load_dotenv
    load_dotenv()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # register helper as a global function in the template
    env.globals["aspect_color"] = lambda a: ASPECT_COLORS.get(a, "#888780")

    template = env.get_template("weekly.html")

    # generate charts
    print("  Generating charts...")
    score_history  = load_score_history(db_path, brand_name)
    sent_totals    = compute_sentiment_totals(db_path, brand_name)

    chart_trend    = chart_health_trend(score_history)
    chart_aspects  = chart_aspect_bars(data_summary["aspect_scores"])
    chart_donut    = chart_sentiment_donut(
        sent_totals["POSITIVE"],
        sent_totals["NEGATIVE"],
        sent_totals["NEUTRAL"],
    )
    print(f"    Trend chart  : {'OK' if chart_trend   else 'SKIPPED'}")
    print(f"    Aspect chart : {'OK' if chart_aspects else 'SKIPPED'}")
    print(f"    Donut chart  : {'OK' if chart_donut   else 'SKIPPED'}")

    # compute template variables
    score        = data_summary["current_score"]
    trend        = data_summary["health_trend"]
    total_ment   = sum(data_summary["mention_counts"].values())
    generated_at = datetime.now(tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    context = {
        "brand_name":      brand_name,
        "report_date":     data_summary["date_range"]["end"],
        "date_range":      data_summary["date_range"],
        "current_score":   f"{score:.1f}",
        "score_color":     _score_color(score),
        "health_trend":    trend,
        "trend_class":     _trend_class(trend),
        "trend_arrow":     _trend_arrow(trend),
        "aspect_scores":   data_summary["aspect_scores"],
        "top_alerts":      data_summary["top_alerts"],
        "top_negative":    data_summary["top_negative"],
        "top_positive":    data_summary["top_positive"],
        "mention_counts":  data_summary["mention_counts"],
        "total_mentions":  total_ment,
        "llm_report_html": markdown_to_html(llm_report),
        "chart_trend":     chart_trend,
        "chart_aspects":   chart_aspects,
        "chart_donut":     chart_donut,
        "generated_at":    generated_at,
        "groq_model":      os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    }

    # render
    html = template.render(**context)

    # save
    date_str  = data_summary["date_range"]["end"]
    safe_name = brand_name.lower().replace(" ", "_")
    out_path  = output_dir / f"{safe_name}_report_{date_str}.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"  Report saved: {out_path}")
    return str(out_path)


if __name__ == "__main__":
    from config import BRAND_NAME, DB_PATH
    from reports.report_generator import build_data_summary, build_prompt, call_groq
    from config import GROQ_API_KEY, GROQ_MODEL

    print("=" * 60)
    print(f"Full Report Render | Brand: {BRAND_NAME}")
    print("=" * 60)

    print("\nBuilding data summary...")
    data = build_data_summary(DB_PATH, BRAND_NAME)

    print("Calling Groq API...")
    prompt     = build_prompt(data, BRAND_NAME)
    llm_report = call_groq(prompt, GROQ_MODEL, GROQ_API_KEY)

    print("\nRendering HTML report...")
    out_path = render_report(data, llm_report, DB_PATH, BRAND_NAME)

    print(f"\nDone. Open with:")
    print(f"  open {out_path}")
