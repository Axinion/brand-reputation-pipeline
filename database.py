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
