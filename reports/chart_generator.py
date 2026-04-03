import warnings
warnings.filterwarnings("ignore")

import io
import base64
import matplotlib
matplotlib.use("Agg")   # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.dates  as mdates
from datetime import datetime


# ── shared style ───────────────────────────────────────────────────────

COLORS = {
    "positive":   "#1D9E75",
    "negative":   "#D85A30",
    "neutral":    "#888780",
    "score_line": "#534AB7",
    "smooth":     "#AFA9EC",
    "grid":       "#F1EFE8",
    "text":       "#2C2C2A",
    "bg":         "#FFFFFF",
}

ASPECT_COLORS = {
    "quality":  "#1D9E75",
    "ux":       "#534AB7",
    "price":    "#D85A30",
    "support":  "#BA7517",
    "delivery": "#185FA5",
    "overall":  "#888780",
}

def _fig_to_base64(fig):
    """Convert a matplotlib figure to a base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150,
                bbox_inches="tight", facecolor=COLORS["bg"])
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return f"data:image/png;base64,{img_b64}"


def _style_axes(ax, title="", ylabel=""):
    """Apply consistent styling to any axes object."""
    ax.set_facecolor(COLORS["bg"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D3D1C7")
    ax.spines["bottom"].set_color("#D3D1C7")
    ax.tick_params(colors=COLORS["text"], labelsize=9)
    ax.yaxis.grid(True, color=COLORS["grid"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, fontsize=11, fontweight="500",
                     color=COLORS["text"], pad=12)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9, color=COLORS["text"])


# ── Chart 1: health score trend ────────────────────────────────────────

def chart_health_trend(score_rows):
    """
    Line chart showing raw and smoothed health score over time.
    score_rows: list of dicts with keys date, health_score, smoothed_score
    """
    if not score_rows:
        return None

    dates   = [datetime.strptime(r["date"], "%Y-%m-%d")
                for r in score_rows]
    raw     = [r["health_score"]    for r in score_rows]
    smooth  = [r["smoothed_score"]  for r in score_rows]

    fig, ax = plt.subplots(figsize=(8, 3))
    fig.patch.set_facecolor(COLORS["bg"])

    # filled area under smoothed line
    ax.fill_between(dates, smooth, alpha=0.12,
                    color=COLORS["score_line"])

    # raw daily score — thin dots
    ax.plot(dates, raw, "o", markersize=3,
            color=COLORS["score_line"], alpha=0.4, zorder=3)

    # smoothed trend — solid line
    ax.plot(dates, smooth, "-", linewidth=2,
            color=COLORS["score_line"], zorder=4, label="7-day smoothed")

    # neutral line at 50
    ax.axhline(50, color="#D3D1C7", linewidth=0.8, linestyle="--")
    ax.text(dates[0], 51, "neutral", fontsize=8,
            color="#888780", va="bottom")

    ax.set_ylim(0, 100)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    plt.xticks(rotation=30, ha="right")

    _style_axes(ax, ylabel="Health score (0–100)")
    ax.legend(fontsize=8, framealpha=0)

    plt.tight_layout()
    return _fig_to_base64(fig)


# ── Chart 2: aspect sentiment bars ─────────────────────────────────────

def chart_aspect_bars(aspect_scores):
    """
    Horizontal bar chart showing avg_score per aspect.
    aspect_scores: dict of aspect → {avg_score, positive_pct, negative_pct}
    Excludes 'overall'.
    """
    data = {
        k: v for k, v in aspect_scores.items()
        if k != "overall"
    }
    if not data:
        return None

    aspects = list(data.keys())
    scores  = [data[a]["avg_score"] for a in aspects]
    colors  = [ASPECT_COLORS.get(a, "#888780") for a in aspects]

    # sort by score ascending so worst is at top
    pairs  = sorted(zip(scores, aspects, colors))
    scores, aspects, colors = zip(*pairs)

    fig, ax = plt.subplots(figsize=(8, max(2.5, len(aspects) * 0.55)))
    fig.patch.set_facecolor(COLORS["bg"])

    bars = ax.barh(aspects, scores, color=colors,
                   alpha=0.85, height=0.5, zorder=3)

    # value labels
    for bar, score in zip(bars, scores):
        x_pos  = score + 0.01 if score >= 0 else score - 0.01
        h_align = "left"  if score >= 0 else "right"
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                f"{score:+.3f}", va="center", ha=h_align,
                fontsize=8, color=COLORS["text"])

    ax.axvline(0, color="#D3D1C7", linewidth=0.8)
    ax.set_xlim(-1.1, 1.1)
    ax.set_xlabel("Sentiment score (−1 = all negative, +1 = all positive)",
                  fontsize=8, color=COLORS["text"])

    _style_axes(ax)
    plt.tight_layout()
    return _fig_to_base64(fig)


# ── Chart 3: sentiment breakdown donut ─────────────────────────────────

def chart_sentiment_donut(pos_count, neg_count, neu_count):
    """
    Donut chart showing overall sentiment split.
    """
    total = pos_count + neg_count + neu_count
    if total == 0:
        return None

    sizes  = [pos_count, neg_count, neu_count]
    colors = [COLORS["positive"], COLORS["negative"], COLORS["neutral"]]
    labels = [
        f"Positive\n{pos_count}",
        f"Negative\n{neg_count}",
        f"Neutral\n{neu_count}",
    ]

    fig, ax = plt.subplots(figsize=(4, 4))
    fig.patch.set_facecolor(COLORS["bg"])

    wedges, texts = ax.pie(
        sizes, colors=colors, startangle=90,
        wedgeprops={"width": 0.5, "edgecolor": "white", "linewidth": 2},
    )

    # center label
    ax.text(0, 0, f"{total}\nmentions",
            ha="center", va="center", fontsize=10,
            fontweight="500", color=COLORS["text"])

    ax.legend(wedges, labels, loc="lower center",
              bbox_to_anchor=(0.5, -0.15), ncol=3,
              fontsize=8, framealpha=0)

    plt.tight_layout()
    return _fig_to_base64(fig)


if __name__ == "__main__":
    # quick test
    print("Testing chart generator...")
    test_scores = [
        {"date": f"2026-03-{i:02d}",
         "health_score": 40 + i * 0.5,
         "smoothed_score": 42 + i * 0.3}
        for i in range(1, 32)
    ]
    b64 = chart_health_trend(test_scores)
    print(f"Health trend chart: {len(b64)} chars of base64")

    test_aspects = {
        "quality":  {"avg_score": 0.12, "positive_pct": 65, "negative_pct": 20},
        "ux":       {"avg_score": -0.08, "positive_pct": 40, "negative_pct": 55},
        "price":    {"avg_score": -0.31, "positive_pct": 20, "negative_pct": 75},
        "support":  {"avg_score": -0.05, "positive_pct": 45, "negative_pct": 48},
        "delivery": {"avg_score":  0.18, "positive_pct": 70, "negative_pct": 22},
    }
    b64 = chart_aspect_bars(test_aspects)
    print(f"Aspect bars chart: {len(b64)} chars of base64")
    print("Chart generator OK")
