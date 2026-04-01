import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import sqlite_utils

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import init_daily_table, insert_daily_rows


def _make_daily_id(brand: str, date: str, aspect: str) -> str:
    raw = f"{brand}:{date}:{aspect}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def load_scored_mentions(db_path: str, brand_name: str) -> pd.DataFrame:
    """Load all scored_mentions for a brand into a DataFrame."""
    db = sqlite_utils.Database(db_path)
    rows = list(db.execute(
        """
        SELECT id, mention_id, brand, source, timestamp,
               aspect, sentiment, confidence
        FROM scored_mentions
        WHERE brand = ?
        """,
        [brand_name],
    ).fetchall())

    columns = ["id", "mention_id", "brand", "source", "timestamp",
               "aspect", "sentiment", "confidence"]
    df = pd.DataFrame(rows, columns=columns)
    print(f"Loaded {len(df)} scored records for brand '{brand_name}'")
    return df


def aggregate_daily(df: pd.DataFrame, brand_name: str) -> list:
    """
    Aggregate scored_mentions to one row per day per aspect.
    avg_score range: -1.0 (all negative) to +1.0 (all positive)
    """
    if df.empty:
        print("  No data to aggregate.")
        return []

    # parse timestamps — handle mixed formats gracefully
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["date"] = df["timestamp"].dt.strftime("%Y-%m-%d")

    records = []

    for (date, aspect), group in df.groupby(["date", "aspect"]):
        total = len(group)
        pos   = group[group["sentiment"] == "POSITIVE"]
        neg   = group[group["sentiment"] == "NEGATIVE"]
        neu   = group[group["sentiment"] == "NEUTRAL"]

        pos_count = len(pos)
        neg_count = len(neg)
        neu_count = len(neu)

        # weighted sentiment score: positive pulls toward +1, negative toward -1
        pos_score = pos["confidence"].mean() if len(pos) > 0 else 0.0
        neg_score = neg["confidence"].mean() if len(neg) > 0 else 0.0

        # net score: proportion-weighted
        avg_score = (pos_count * pos_score - neg_count * neg_score) / total

        records.append({
            "id":             _make_daily_id(brand_name, date, aspect),
            "brand":          brand_name,
            "date":           date,
            "aspect":         aspect,
            "avg_score":      round(float(avg_score), 4),
            "mention_count":  total,
            "positive_count": pos_count,
            "negative_count": neg_count,
            "neutral_count":  neu_count,
            "positive_pct":   round(pos_count / total * 100, 2),
            "negative_pct":   round(neg_count / total * 100, 2),
            "neutral_pct":    round(neu_count / total * 100, 2),
        })

    # sort by date then aspect for clean output
    records.sort(key=lambda x: (x["date"], x["aspect"]))
    return records


def run_aggregation(db_path: str, brand_name: str) -> None:
    """Load scored data, aggregate to daily level, upsert into brand_health_daily."""
    db = sqlite_utils.Database(db_path)
    init_daily_table(db)

    df = load_scored_mentions(db_path, brand_name)
    if df.empty:
        print("No scored mentions found — run sentiment_engine.py first.")
        return

    records = aggregate_daily(df, brand_name)

    insert_daily_rows(db, records)

    # summary
    dates  = sorted(set(r["date"]   for r in records))
    aspects = sorted(set(r["aspect"] for r in records))
    print(f"\nAggregation complete:")
    print(f"  Rows written  : {len(records)}")
    print(f"  Date range    : {dates[0]} → {dates[-1]}")
    print(f"  Unique days   : {len(dates)}")
    print(f"  Aspects       : {aspects}")

    print(f"\nSample daily rows (overall aspect):")
    overall = [r for r in records if r["aspect"] == "overall"][:5]
    print(f"  {'date':12} {'avg_score':>10} {'mentions':>9} {'pos%':>6} {'neg%':>6}")
    print(f"  {'-'*50}")
    for r in overall:
        print(
            f"  {r['date']:12} {r['avg_score']:>10.3f} "
            f"{r['mention_count']:>9} {r['positive_pct']:>6.1f} {r['negative_pct']:>6.1f}"
        )


def validate_daily_table(db_path: str, brand_name: str) -> bool:
    """
    Run basic sanity checks on brand_health_daily.
    Returns True if all checks pass.
    """
    db   = sqlite_utils.Database(db_path)
    rows = list(db.execute(
        "SELECT * FROM brand_health_daily WHERE brand = ?",
        [brand_name]
    ).fetchall())

    if not rows:
        print("FAIL: brand_health_daily is empty")
        return False

    cols = [d[0] for d in db.execute(
        "SELECT * FROM brand_health_daily LIMIT 1"
    ).description]
    records = [dict(zip(cols, r)) for r in rows]

    issues = []

    for r in records:
        # score in range
        if not -1.0 <= r["avg_score"] <= 1.0:
            issues.append(
                f"avg_score out of range: {r['avg_score']} "
                f"on {r['date']} / {r['aspect']}"
            )

        # percentages sum to ~100
        pct_sum = r["positive_pct"] + r["negative_pct"] + r["neutral_pct"]
        if not 99.0 <= pct_sum <= 101.0:
            issues.append(
                f"Percentages don't sum to 100: {pct_sum:.1f} "
                f"on {r['date']} / {r['aspect']}"
            )

        # counts match
        count_sum = (r["positive_count"] +
                     r["negative_count"] +
                     r["neutral_count"])
        if count_sum != r["mention_count"]:
            issues.append(
                f"Count mismatch: {count_sum} != {r['mention_count']} "
                f"on {r['date']} / {r['aspect']}"
            )

    if issues:
        print(f"VALIDATION ISSUES ({len(issues)}):")
        for issue in issues[:5]:
            print(f"  {issue}")
        return False

    print(f"Validation passed: {len(records)} rows, all checks clean")
    return True


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    from config import BRAND_NAME, DB_PATH

    print("=" * 60)
    print(f"Daily Aggregator | Brand: {BRAND_NAME}")
    print("=" * 60)
    run_aggregation(DB_PATH, BRAND_NAME)
