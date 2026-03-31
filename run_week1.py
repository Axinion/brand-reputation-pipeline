import json
import os
import time
from collections import Counter

import database
from config import BRAND_NAME, DB_PATH
from scrapers import normalizer
from scrapers.news_scraper import scrape_news
from scrapers.reddit_scraper import scrape_reddit
from scrapers.review_scraper import scrape_app_reviews


def load_raw_json(path):
    if not os.path.exists(path):
        print(f"Missing file: {path} (using empty list)")
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        print(f"Failed to load {path}: {exc}")
        return []


def main():
    start = time.time()
    print("=" * 60)
    print(f"Week 1 Master Pipeline | Brand: {BRAND_NAME}")
    print("=" * 60)

    # Imported scrapers are kept here explicitly for pipeline visibility.
    available_scrapers = [scrape_reddit.__name__, scrape_news.__name__, scrape_app_reviews.__name__]
    print(f"Scrapers available: {', '.join(available_scrapers)}")

    db = database.init_db(DB_PATH)

    reddit = load_raw_json("data/reddit_raw.json")
    news = load_raw_json("data/news_raw.json")
    reviews = load_raw_json("data/reviews_raw.json")
    combined = reddit + news + reviews

    print("\nRaw input counts:")
    print(f"  Reddit:  {len(reddit)}")
    print(f"  News:    {len(news)}")
    print(f"  Reviews: {len(reviews)}")
    print(f"  Combined:{len(combined)}")

    by_source = Counter(m.get("source", "unknown") for m in combined)
    print("\nBy source before normalization:")
    for src, count in by_source.most_common():
        print(f"  {src:12} {count}")

    normalized = normalizer.normalize_mentions(combined)
    print(f"\nAfter normalization: {len(normalized)} records")

    inserted = database.insert_mentions(db, normalized, BRAND_NAME)
    database.get_stats(db, BRAND_NAME)

    elapsed = time.time() - start
    print(
        f"Pipeline complete. Inserted {inserted} new records in {elapsed:.1f}s. "
        f"DB: {DB_PATH}"
    )


if __name__ == "__main__":
    main()
