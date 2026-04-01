import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sqlite_utils

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import init_daily_table

# ── weights / constants (set in Step 1 — do not redefine) ────────────────────
# Aspect weights — must sum to 1.0
# Rationale: quality and UX are core to a streaming service's value prop.
# Price drives churn. Support and delivery are secondary signals.
ASPECT_WEIGHTS = {
    "quality":  0.30,
    "ux":       0.25,
    "price":    0.20,
    "support":  0.15,
    "delivery": 0.10,
}

# The 'overall' aspect is distilBERT fallback — lower weight
# because it carries no aspect-level specificity
OVERALL_WEIGHT = 0.40   # used only when no specific aspects exist for that day

# Rolling window for smoothing the final score
SMOOTHING_WINDOW = 7
MIN_PERIODS      = 3


def _make_score_id(brand: str, date: str) -> str:
    raw = f"{brand}:{date}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def load_daily_scores(db_path: str, brand_name: str) -> pd.DataFrame:
    """Load brand_health_daily rows into a DataFrame."""
    db = sqlite_utils.Database(db_path)
    rows = list(db.execute(
        """
        SELECT date, aspect, avg_score, mention_count
        FROM brand_health_daily
        WHERE brand = ?
        ORDER BY date, aspect
        """,
        [brand_name],
    ).fetchall())

    cols = ["date", "aspect", "avg_score", "mention_count"]
    df = pd.DataFrame(rows, columns=cols)
    print(f"Loaded {len(df)} daily aspect rows for brand '{brand_name}'")
    return df


def compute_composite(df: pd.DataFrame, brand_name: str) -> pd.DataFrame:
    """
    Compute a weighted composite health score for each day.

    Scoring logic:
    - Use ASPECT_WEIGHTS for specific aspects (quality, ux, price, support, delivery)
    - Use OVERALL_WEIGHT for the 'overall' fallback aspect only when
      no specific aspects are present that day
    - Rescale from (-1, +1) → (0, 100)
    """
    if df.empty:
        print("  No daily data found.")
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    results    = []

    for date, day_group in df.groupby("date"):
        aspect_rows = {
            row["aspect"]: row
            for _, row in day_group.iterrows()
        }

        specific_aspects = {
            k: v for k, v in aspect_rows.items()
            if k in ASPECT_WEIGHTS
        }

        weighted_sum   = 0.0
        total_weight   = 0.0
        aspects_used   = []
        dominant       = None
        dominant_score = None

        if specific_aspects:
            # use named aspect weights
            for aspect, weight in ASPECT_WEIGHTS.items():
                if aspect not in specific_aspects:
                    continue
                score = float(specific_aspects[aspect]["avg_score"])
                weighted_sum  += score * weight
                total_weight  += weight
                aspects_used.append(aspect)

                if dominant_score is None or abs(score) > abs(dominant_score):
                    dominant       = aspect
                    dominant_score = score

        elif "overall" in aspect_rows:
            # fall back to overall only if no specific aspects exist
            score         = float(aspect_rows["overall"]["avg_score"])
            weighted_sum  = score * OVERALL_WEIGHT
            total_weight  = OVERALL_WEIGHT
            aspects_used  = ["overall"]
            dominant      = "overall"

        if total_weight == 0:
            continue

        raw_score    = weighted_sum / total_weight
        health_score = round((raw_score + 1) / 2 * 100, 2)
        health_score = max(0.0, min(100.0, health_score))  # clamp 0–100

        results.append({
            "date":            date,
            "raw_score":       round(raw_score,   4),
            "health_score":    health_score,
            "aspect_count":    len(aspects_used),
            "dominant_aspect": dominant or "none",
        })

    out_df = pd.DataFrame(results).sort_values("date").reset_index(drop=True)
    return out_df


def apply_smoothing(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 7-day rolling smoothed score alongside the raw daily score.
    Both are kept — raw shows actual day, smoothed shows trend.
    """
    if df.empty:
        return df

    df = df.sort_values("date").copy()

    df["smoothed_score"] = (
        df["health_score"]
        .rolling(window=SMOOTHING_WINDOW, min_periods=MIN_PERIODS)
        .mean()
        .round(2)
    )

    # where smoothing has insufficient data use raw score
    df["smoothed_score"] = df["smoothed_score"].fillna(df["health_score"])

    return df


def write_scores_to_db(df: pd.DataFrame, db_path: str, brand_name: str) -> int:
    """Upsert composite scores into brand_health_scores table."""
    db  = sqlite_utils.Database(db_path)
    now = datetime.now(tz=timezone.utc).isoformat()

    schema = {
        "id":              str,
        "brand":           str,
        "date":            str,
        "raw_score":       float,
        "health_score":    float,
        "smoothed_score":  float,
        "aspect_count":    int,
        "dominant_aspect": str,
        "created_at":      str,
    }

    if "brand_health_scores" not in db.table_names():
        db["brand_health_scores"].create(schema, pk="id")
        for col in ["brand", "date"]:
            db["brand_health_scores"].create_index([col], if_not_exists=True)
        print("  Created brand_health_scores table")

    records = []
    for _, row in df.iterrows():
        records.append({
            "id":              _make_score_id(brand_name, row["date"]),
            "brand":           brand_name,
            "date":            row["date"],
            "raw_score":       float(row["raw_score"]),
            "health_score":    float(row["health_score"]),
            "smoothed_score":  float(row["smoothed_score"]),
            "aspect_count":    int(row["aspect_count"]),
            "dominant_aspect": row["dominant_aspect"],
            "created_at":      now,
        })

    db["brand_health_scores"].upsert_all(records, pk="id")
    print(f"  Upserted {len(records)} health score rows")
    return len(records)


def run_health_score(db_path: str, brand_name: str) -> pd.DataFrame:
    """Full health score pipeline — load, compute, smooth, store."""
    print(f"Loading daily aspect scores for {brand_name}...")
    df = load_daily_scores(db_path, brand_name)

    if df.empty:
        print("No data found. Run aggregator.py first.")
        return pd.DataFrame()

    print(f"  Loaded {len(df)} daily aspect rows")

    print("Computing composite scores...")
    scored_df = compute_composite(df, brand_name)
    print(f"  Computed {len(scored_df)} daily composite scores")

    print("Applying 7-day smoothing...")
    smoothed_df = apply_smoothing(scored_df)

    print("Writing to database...")
    write_scores_to_db(smoothed_df, db_path, brand_name)

    # print final table
    print(f"\n{'Date':12}  {'Raw':>6}  {'Score':>7}  "
          f"{'Smooth':>8}  {'Aspects':>7}  Dominant")
    print("-" * 60)
    for _, row in smoothed_df.iterrows():
        print(f"{row['date']:12}  "
              f"{row['raw_score']:>+6.3f}  "
              f"{row['health_score']:>6.1f}/100  "
              f"{row['smoothed_score']:>6.1f}/100  "
              f"{int(row['aspect_count']):>4} asp  "
              f"{row['dominant_aspect']}")

    # summary stats
    latest       = smoothed_df.iloc[-1]
    week_ago     = smoothed_df.iloc[-7] if len(smoothed_df) >= 7 else smoothed_df.iloc[0]
    score_change = latest["smoothed_score"] - week_ago["smoothed_score"]
    trend_arrow  = "↑" if score_change > 1 else "↓" if score_change < -1 else "→"

    print(f"\nSummary:")
    print(f"  Latest score   : {latest['health_score']:.1f}/100")
    print(f"  7-day smoothed : {latest['smoothed_score']:.1f}/100")
    print(f"  Week trend     : {score_change:+.1f} pts  {trend_arrow}")
    print(f"  Period range   : "
          f"{smoothed_df['health_score'].min():.1f} – "
          f"{smoothed_df['health_score'].max():.1f}")

    return smoothed_df


def get_current_score(db_path: str, brand_name: str) -> dict | None:
    """
    Return the most recent health score for a brand.
    Used by the alert engine to include context in notifications.
    """
    db = sqlite_utils.Database(db_path)
    try:
        row = next(db.execute(
            """
            SELECT date, health_score, smoothed_score, dominant_aspect
            FROM brand_health_scores
            WHERE brand = ?
            ORDER BY date DESC LIMIT 1
            """,
            [brand_name],
        ))
        return {
            "date":            row[0],
            "health_score":    row[1],
            "smoothed_score":  row[2],
            "dominant_aspect": row[3],
        }
    except StopIteration:
        return None


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    from config import BRAND_NAME, DB_PATH

    print("=" * 60)
    print(f"Brand Health Score | Brand: {BRAND_NAME}")
    print("=" * 60)

    run_health_score(DB_PATH, BRAND_NAME)
