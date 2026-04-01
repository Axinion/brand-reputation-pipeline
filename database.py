from datetime import datetime, timezone
from pathlib import Path

import sqlite_utils


SCHEMA = {
    "id": "TEXT PRIMARY KEY",
    "brand": "TEXT",
    "source": "TEXT",
    "source_detail": "TEXT",
    "timestamp": "TEXT",
    "text": "TEXT",
    "normalized_text": "TEXT",
    "url": "TEXT",
    "score": "INTEGER",
    "mention_type": "TEXT",
    "created_at": "TEXT",
}


def init_db(db_path):
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite_utils.Database(db_file)
    table = db["raw_mentions"]
    create_columns = dict(SCHEMA)
    create_columns["id"] = "TEXT"
    table.create(columns=create_columns, pk="id", if_not_exists=True)

    table.create_index(["timestamp"], if_not_exists=True)
    table.create_index(["source"], if_not_exists=True)
    table.create_index(["brand"], if_not_exists=True)
    table.create_index(["mention_type"], if_not_exists=True)

    print(f"DB initialized at {db_file} | current rows: {table.count}")
    return db


def init_scored_table(db):
    table = db["scored_mentions"]
    columns = {
        "id": str,
        "mention_id": str,
        "brand": str,
        "source": str,
        "source_detail": str,
        "timestamp": str,
        "aspect": str,
        "sentiment": str,
        "confidence": float,
        "overall_sentiment": str,
        "overall_score": float,
        "original_text": str,
        "created_at": str,
    }
    table.create(columns=columns, pk="id", if_not_exists=True)
    table.create_index(["mention_id"], if_not_exists=True)
    table.create_index(["brand"], if_not_exists=True)
    table.create_index(["aspect"], if_not_exists=True)
    table.create_index(["sentiment"], if_not_exists=True)
    table.create_index(["timestamp"], if_not_exists=True)
    print(f"Scored table ready | current rows: {table.count}")


def insert_mentions(db, mentions, brand_name):
    table = db["raw_mentions"]
    before_count = table.count
    created_at = datetime.now(tz=timezone.utc).isoformat()

    prepared = []
    for m in mentions:
        prepared.append(
            {
                "id": m.get("id", ""),
                "brand": brand_name,
                "source": m.get("source", ""),
                "source_detail": m.get("source_detail", ""),
                "timestamp": m.get("timestamp", ""),
                "text": m.get("text", ""),
                "normalized_text": m.get("normalized_text", ""),
                "url": m.get("url", ""),
                "score": int(m.get("score", 0) or 0),
                "mention_type": m.get("mention_type", ""),
                "created_at": created_at,
            }
        )

    if prepared:
        table.upsert_all(prepared, pk="id")

    after_count = table.count
    inserted = max(after_count - before_count, 0)
    print(
        f"Insert complete for brand '{brand_name}': "
        f"{inserted} inserted, {len(prepared)} processed."
    )
    return inserted


def insert_scored(db, records):
    """Upsert scored aspect records into scored_mentions table."""
    if not records:
        print("  No scored records to insert.")
        return 0

    now = datetime.now(tz=timezone.utc).isoformat()
    for r in records:
        r["created_at"] = now

    db["scored_mentions"].upsert_all(records, pk="id")
    print(f"  Inserted/updated {len(records)} scored records.")
    return len(records)


def init_daily_table(db):
    """Create brand_health_daily table for time-series aggregation."""
    table = db["brand_health_daily"]
    columns = {
        "id":             str,
        "brand":          str,
        "date":           str,
        "aspect":         str,
        "avg_score":      float,
        "mention_count":  int,
        "positive_count": int,
        "negative_count": int,
        "neutral_count":  int,
        "positive_pct":   float,
        "negative_pct":   float,
        "neutral_pct":    float,
        "created_at":     str,
    }
    table.create(columns=columns, pk="id", if_not_exists=True)
    table.create_index(["date"],   if_not_exists=True)
    table.create_index(["brand"],  if_not_exists=True)
    table.create_index(["aspect"], if_not_exists=True)
    print(f"Daily table ready | current rows: {table.count}")
    return db


def insert_daily_rows(db, records):
    """Upsert daily aggregated rows into brand_health_daily."""
    if not records:
        print("  No daily rows to insert.")
        return 0
    now = datetime.now(tz=timezone.utc).isoformat()
    for r in records:
        r["created_at"] = now
    db["brand_health_daily"].upsert_all(records, pk="id")
    print(f"  Upserted {len(records)} daily rows.")
    return len(records)


def get_stats(db, brand_name):
    """Print and return summary stats for a brand."""
    rows = list(db.execute("SELECT * FROM raw_mentions WHERE brand = ?", [brand_name]).fetchall())

    if not rows:
        print(f"No records found for brand: {brand_name}")
        return {}

    from collections import Counter

    col_names = [d[0] for d in db.execute("SELECT * FROM raw_mentions LIMIT 1").description]
    records = [dict(zip(col_names, row)) for row in rows]

    by_source = Counter(r["source"] for r in records)
    by_type = Counter(r["mention_type"] for r in records)
    timestamps = sorted(r["timestamp"] for r in records if r.get("timestamp"))

    stats = {
        "total": len(records),
        "by_source": dict(by_source),
        "by_type": dict(by_type),
        "earliest": timestamps[0] if timestamps else None,
        "latest": timestamps[-1] if timestamps else None,
    }

    print(f"\n{'='*40}")
    print(f"Brand: {brand_name}")
    print(f"Total records: {stats['total']}")
    print("\nBy source:")
    for src, count in by_source.most_common():
        bar = "█" * (count // 10)
        print(f"  {src:20} {count:>5}  {bar}")
    print("\nBy type:")
    for t, count in by_type.most_common():
        print(f"  {t:20} {count:>5}")
    print(f"\nDate range: {stats['earliest'][:10]} → {stats['latest'][:10]}")
    print(f"{'='*40}\n")

    return stats
