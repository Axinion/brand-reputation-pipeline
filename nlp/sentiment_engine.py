import hashlib
import sys
import warnings
from collections import Counter
from pathlib import Path

import sqlite_utils

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database
from nlp.taxonomy import IGNORE_TERMS, MIN_CONFIDENCE, MIN_TEXT_LENGTH, map_to_taxonomy


warnings.filterwarnings("ignore")

# Singleton extractor; loaded lazily by get_extractor()
_extractor = None


def get_extractor():
    global _extractor
    if _extractor is None:
        from pyabsa import AspectTermExtraction as ATEPC

        _extractor = ATEPC.AspectExtractor(
            "multilingual",
            auto_device=True,
            cal_perplexity=False,
        )
    return _extractor


def make_scored_id(mention_id, aspect):
    raw = f"{mention_id}{aspect}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def run_atepc_batch(texts, batch_size=16):
    extractor = get_extractor()
    all_results = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        print(
            f"  Processing batch {i//batch_size + 1}"
            f"/{(len(texts) + batch_size - 1)//batch_size}"
            f" ({len(batch)} texts)..."
        )
        results = extractor.predict(batch, print_result=False)
        all_results.extend(results)

    return all_results


def _derive_overall_from_row(row):
    source = row.get("source", "")
    raw_score = row.get("score", 0) or 0

    if source == "app_review":
        try:
            stars = float(raw_score)
        except Exception:
            stars = 0.0
        if stars >= 4:
            return "Positive", round(stars / 5.0, 3)
        if stars <= 2:
            return "Negative", round(stars / 5.0, 3)
        return "Neutral", round(stars / 5.0, 3)

    return "Neutral", 0.0


def process_mention(row, atepc_result, brand_name):
    scored = []
    aspects = atepc_result.get("aspect", []) or []
    sentiments = atepc_result.get("sentiment", []) or []
    confidences = atepc_result.get("confidence", []) or []

    for asp, sent, conf in zip(aspects, sentiments, confidences):
        if conf < MIN_CONFIDENCE:
            continue

        category = map_to_taxonomy(asp)
        if category in ("ignore", "other"):
            continue

        scored.append(
            {
                "id": make_scored_id(row["id"], asp),
                "mention_id": row["id"],
                "brand": brand_name,
                "source": row["source"],
                "source_detail": row["source_detail"],
                "timestamp": row["timestamp"],
                "aspect": category,
                "sentiment": sent.upper(),
                "confidence": round(conf, 4),
                "overall_sentiment": sent.upper(),
                "overall_score": round(conf, 4),
                "original_text": row["normalized_text"],
            }
        )

    return scored


def run_sentiment_pipeline(db_path, brand_name, batch_size=16):
    db = sqlite_utils.Database(db_path)
    database.init_scored_table(db)

    rows = list(
        db.query(
            """
            SELECT id, source, source_detail, timestamp, normalized_text
            FROM raw_mentions
            WHERE brand = ? AND LENGTH(normalized_text) > ?
            """,
            [brand_name, MIN_TEXT_LENGTH],
        )
    )

    if not rows:
        print(f"No candidate mentions found for brand '{brand_name}'.")
        return {"inserted": 0, "by_aspect": {}}

    print(f"Loaded {len(rows)} records from DB")
    texts = [r["normalized_text"] for r in rows]
    print(f"Running ATEPC on {len(texts)} mentions...")
    results = run_atepc_batch(texts, batch_size=batch_size)

    scored_records = []
    by_aspect = Counter()
    for row, result in zip(rows, results):
        produced = process_mention(row, result, brand_name)
        scored_records.extend(produced)
        for rec in produced:
            by_aspect[rec["aspect"]] += 1

    inserted = database.insert_scored(db, scored_records)

    print("\nSentiment pipeline summary")
    print(f"  Mentions processed: {len(rows)}")
    print(f"  Aspect rows scored: {len(scored_records)}")
    print(f"  Inserted/updated:   {inserted}")
    print("  By aspect category:")
    for cat, count in by_aspect.most_common():
        print(f"    {cat:12}: {count}")

    return {"inserted": inserted, "by_aspect": dict(by_aspect)}


if __name__ == "__main__":
    import warnings

    warnings.filterwarnings("ignore")

    from config import BRAND_NAME, DB_PATH
    from database import init_db

    print("=" * 60)
    print(f"Sentiment Engine | Brand: {BRAND_NAME}")
    print("=" * 60)

    db = init_db(DB_PATH)
    run_sentiment_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME, batch_size=16)
