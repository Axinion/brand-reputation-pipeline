import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sqlite_utils

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import init_alerts_table, insert_alerts

# ── thresholds ────────────────────────────────────────────────────────────────
SENTIMENT_SPIKE_THRESHOLD = 1.5   # z-score units
VOLUME_SPIKE_MULTIPLIER   = 2.0   # x rolling average
ROLLING_WINDOW            = 7     # days
MIN_PERIODS               = 3     # minimum days before computing rolling stats


def _make_alert_id(brand: str, date: str, aspect: str, alert_type: str) -> str:
    raw = f"{brand}:{date}:{aspect}:{alert_type}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def load_daily_data(db_path: str, brand_name: str) -> pd.DataFrame:
    """Load brand_health_daily into a DataFrame sorted by aspect and date."""
    db = sqlite_utils.Database(db_path)
    rows = list(db.execute(
        """
        SELECT date, aspect, avg_score, mention_count,
               positive_pct, negative_pct, neutral_pct
        FROM brand_health_daily
        WHERE brand = ?
        ORDER BY aspect, date
        """,
        [brand_name],
    ).fetchall())

    cols = ["date", "aspect", "avg_score", "mention_count",
            "positive_pct", "negative_pct", "neutral_pct"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    print(f"Loaded {len(df)} daily rows for brand '{brand_name}'")
    return df


def compute_rolling_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute rolling mean, std, and volume baseline per aspect.
    Groups by aspect so Netflix/ux rolling stats don't bleed
    into Netflix/price rolling stats.
    """
    df = df.sort_values(["aspect", "date"]).copy()

    rolling_means  = []
    rolling_stds   = []
    rolling_counts = []

    for aspect, group in df.groupby("aspect"):
        # rolling on avg_score
        rm = (group["avg_score"]
              .rolling(window=ROLLING_WINDOW, min_periods=MIN_PERIODS)
              .mean())
        rs = (group["avg_score"]
              .rolling(window=ROLLING_WINDOW, min_periods=MIN_PERIODS)
              .std()
              .fillna(0.01))   # fill NaN std with small value to avoid div/0

        # rolling on mention_count
        rc = (group["mention_count"]
              .rolling(window=ROLLING_WINDOW, min_periods=MIN_PERIODS)
              .mean())

        rolling_means.append(rm)
        rolling_stds.append(rs)
        rolling_counts.append(rc)

    df["rolling_mean"]       = pd.concat(rolling_means)
    df["rolling_std"]        = pd.concat(rolling_stds)
    df["rolling_count_mean"] = pd.concat(rolling_counts)

    # z-score computed inline
    df["z_score"] = (
        (df["avg_score"] - df["rolling_mean"]) / df["rolling_std"]
    ).round(4)

    return df


def detect_spikes(df: pd.DataFrame, brand_name: str) -> list:
    """
    Detect sentiment and volume spikes using z-score thresholds.
    Returns list of alert dicts ready for DB insertion.
    """
    alerts = []

    for _, row in df.iterrows():
        z      = row["z_score"]
        date   = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])
        aspect = row["aspect"]

        # skip rows where rolling stats aren't yet reliable
        if pd.isna(z):
            continue

        # determine severity
        def severity(z_val):
            abs_z = abs(z_val)
            if abs_z >= 2.5:
                return "high"
            elif abs_z >= 1.5:
                return "medium"
            return None

        # negative sentiment spike
        if z <= -SENTIMENT_SPIKE_THRESHOLD:
            sev = severity(z)
            alerts.append({
                "id":             _make_alert_id(brand_name, date, aspect, "sentiment_drop"),
                "brand":          brand_name,
                "alert_type":     "sentiment_drop",
                "aspect":         aspect,
                "date":           date,
                "score":          round(float(row["avg_score"]),    4),
                "baseline_mean":  round(float(row["rolling_mean"]), 4),
                "baseline_std":   round(float(row["rolling_std"]),  4),
                "z_score":        round(float(z),                   4),
                "mention_count":  int(row["mention_count"]),
                "baseline_count": round(float(row["rolling_count_mean"]), 2),
                "severity":       sev,
                "top_mentions":   "",
            })

        # positive sentiment spike
        elif z >= SENTIMENT_SPIKE_THRESHOLD:
            sev = severity(z)
            alerts.append({
                "id":             _make_alert_id(brand_name, date, aspect, "sentiment_rise"),
                "brand":          brand_name,
                "alert_type":     "sentiment_rise",
                "aspect":         aspect,
                "date":           date,
                "score":          round(float(row["avg_score"]),    4),
                "baseline_mean":  round(float(row["rolling_mean"]), 4),
                "baseline_std":   round(float(row["rolling_std"]),  4),
                "z_score":        round(float(z),                   4),
                "mention_count":  int(row["mention_count"]),
                "baseline_count": round(float(row["rolling_count_mean"]), 2),
                "severity":       sev,
                "top_mentions":   "",
            })

        # volume spike — independent of sentiment direction
        rolling_count = row["rolling_count_mean"]
        if (not pd.isna(rolling_count) and
                rolling_count > 0 and
                row["mention_count"] >= rolling_count * VOLUME_SPIKE_MULTIPLIER):
            alerts.append({
                "id":             _make_alert_id(brand_name, date, aspect, "volume_spike"),
                "brand":          brand_name,
                "alert_type":     "volume_spike",
                "aspect":         aspect,
                "date":           date,
                "score":          round(float(row["avg_score"]),    4),
                "baseline_mean":  round(float(row["rolling_mean"]), 4),
                "baseline_std":   round(float(row["rolling_std"]),  4),
                "z_score":        round(float(z),                   4),
                "mention_count":  int(row["mention_count"]),
                "baseline_count": round(float(row["rolling_count_mean"]), 2),
                "severity":       "medium",
                "top_mentions":   "",
            })

    return alerts


def run_detection(db_path: str, brand_name: str) -> list:
    """Full detection pipeline — load, compute, detect, store."""
    print(f"Loading daily data for {brand_name}...")
    df = load_daily_data(db_path, brand_name)

    if df.empty:
        print("No daily data found. Run aggregator.py first.")
        return []

    print(f"  Loaded {len(df)} daily rows across "
          f"{df['aspect'].nunique()} aspects")

    print("Computing rolling statistics...")
    df = compute_rolling_stats(df)

    print("Detecting spikes...")
    alerts = detect_spikes(df, brand_name)

    db = sqlite_utils.Database(db_path)
    init_alerts_table(db)
    insert_alerts(db, alerts)

    # summary
    if alerts:
        from collections import Counter
        by_type = Counter(a["alert_type"] for a in alerts)
        by_sev  = Counter(a["severity"]   for a in alerts)

        print(f"\nAlerts detected: {len(alerts)}")
        print(f"By type:")
        for t, n in by_type.most_common():
            print(f"  {t:20}: {n}")
        print(f"By severity:")
        for s, n in by_sev.most_common():
            print(f"  {s:20}: {n}")
    else:
        print("\nNo spikes detected — data may be too uniform "
              "or window too short")

    return alerts


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    from config import BRAND_NAME, DB_PATH

    print("=" * 60)
    print(f"Trend Detector | Brand: {BRAND_NAME}")
    print("=" * 60)

    alerts = run_detection(DB_PATH, BRAND_NAME)
