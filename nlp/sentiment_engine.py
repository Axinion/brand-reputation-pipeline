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
_classifier = None


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


def get_classifier():
    global _classifier
    if _classifier is None:
        from transformers import pipeline

        try:
            _classifier = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
                device="mps",
            )
        except Exception:
            _classifier = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
                device="cpu",
            )
    return _classifier


def map_distilbert_label(label, score, neutral_threshold=0.75):
    if score < neutral_threshold:
        return "NEUTRAL"
    if label == "POSITIVE":
        return "POSITIVE"
    if label == "NEGATIVE":
        return "NEGATIVE"
    return "NEUTRAL"


def make_scored_id(mention_id, aspect):
    raw = f"{mention_id}{aspect}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _make_fallback_id(mention_id):
    return hashlib.md5(f"{mention_id}:overall".encode()).hexdigest()[:16]


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


def run_fallback_pipeline(db_path, brand_name, batch_size=32):
    import sqlite_utils
    from database import insert_scored, init_scored_table

    db = sqlite_utils.Database(db_path)
    init_scored_table(db)

    # get already-scored mention IDs as a Python set
    scored_ids = set(
        r[0]
        for r in db.execute(
            "SELECT DISTINCT mention_id FROM scored_mentions WHERE brand = ?",
            [brand_name],
        ).fetchall()
    )
    print(f"Already scored: {len(scored_ids)} unique mentions")

    # load unscored records - filter in Python not SQL to avoid NOT IN issues
    all_rows = list(
        db.execute(
            """
            SELECT id, source, source_detail, timestamp, normalized_text
            FROM raw_mentions
            WHERE brand = ?
            AND LENGTH(normalized_text) > 20
            """,
            [brand_name],
        ).fetchall()
    )

    col_names = ["id", "source", "source_detail", "timestamp", "normalized_text"]
    all_rows = [dict(zip(col_names, r)) for r in all_rows]

    # filter to only unscored
    unscored = [r for r in all_rows if r["id"] not in scored_ids]
    print(f"Records needing fallback: {len(unscored)}")

    if not unscored:
        print("All records already scored - nothing to do.")
        return {"inserted": 0}

    classifier = get_classifier()
    fallback_records = []
    texts = [r["normalized_text"] for r in unscored]

    print(f"Running distilBERT on {len(unscored)} records...")
    for i in range(0, len(unscored), batch_size):
        batch_rows = unscored[i : i + batch_size]
        batch_texts = texts[i : i + batch_size]

        print(
            f"  Fallback batch {i//batch_size + 1}"
            f"/{(len(unscored) + batch_size - 1)//batch_size}..."
        )

        try:
            results = classifier(
                batch_texts,
                truncation=True,
                max_length=512,
                batch_size=batch_size,
            )
        except Exception as e:
            print(f"  Batch failed: {e} - skipping")
            continue

        for row, result in zip(batch_rows, results):
            label = result["label"]
            score = result["score"]
            sentiment = map_distilbert_label(label, score)

            fallback_records.append(
                {
                    "id": _make_fallback_id(row["id"]),
                    "mention_id": row["id"],
                    "brand": brand_name,
                    "source": row["source"],
                    "source_detail": row["source_detail"],
                    "timestamp": row["timestamp"],
                    "aspect": "overall",
                    "sentiment": sentiment,
                    "confidence": round(score, 4),
                    "overall_sentiment": sentiment,
                    "overall_score": round(score, 4),
                    "original_text": row["normalized_text"],
                }
            )

    print(f"\nFallback complete: {len(fallback_records)} records scored")
    insert_scored(db, fallback_records)

    # summary
    sentiments = Counter(r["sentiment"] for r in fallback_records)
    print("\nFallback sentiment breakdown:")
    for sent, count in sentiments.most_common():
        pct = (count / len(fallback_records) * 100) if fallback_records else 0
        bar = "█" * (count // 10)
        print(f"  {sent:10}: {count:>4}  ({pct:.1f}%)  {bar}")

    return {"inserted": len(fallback_records), "by_sentiment": dict(sentiments)}


if __name__ == "__main__":
    import warnings

    warnings.filterwarnings("ignore")

    from config import BRAND_NAME, DB_PATH
    from database import init_db

    print("=" * 60)
    print(f"Sentiment Engine | Brand: {BRAND_NAME}")
    print("=" * 60)

    db = init_db(DB_PATH)

    print("\n--- Stage 1: PyABSA aspect extraction ---")
    run_sentiment_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME, batch_size=16)

    print("\n--- Stage 2: distilBERT fallback ---")
    run_fallback_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME, batch_size=32)

    print("\n--- Final DB state ---")
    import sqlite_utils
    from collections import Counter

    db2 = sqlite_utils.Database(DB_PATH)
    rows = list(db2["scored_mentions"].rows)
    total = len(rows)
    unique_mentions = len(set(r["mention_id"] for r in rows))
    aspects = Counter(r["aspect"] for r in rows)
    sents = Counter(r["sentiment"] for r in rows)

    print(f"Total scored rows    : {total}")
    print(f"Unique mentions      : {unique_mentions} of 722")
    print(f"\nBy aspect:")
    for asp, count in aspects.most_common():
        print(f"  {asp:12}: {count:>4}")
    print(f"\nBy sentiment:")
    for sent, count in sents.most_common():
        pct = count / total * 100
        print(f"  {sent:10}: {count:>4}  ({pct:.1f}%)")
