import warnings
warnings.filterwarnings("ignore")

import sys
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prefect import flow, task, get_run_logger
from prefect.tasks import task_input_hash
from prefect.schedules import Interval


# ── Tasks ──────────────────────────────────────────────────────────────

@task(
    name="ingest-data",
    description="Scrape Reddit, NewsAPI and app store reviews",
    retries=2,
    retry_delay_seconds=60,
    cache_key_fn=task_input_hash,
    cache_expiration=timedelta(hours=6),
)
def task_ingest(brand_name: str, db_path: str) -> dict:
    logger = get_run_logger()
    logger.info(f"Starting ingestion for brand: {brand_name}")

    import json
    from scrapers.reddit_scraper  import scrape_reddit
    from scrapers.news_scraper    import scrape_news
    from scrapers.review_scraper  import scrape_app_reviews
    from config import (BRAND_KEYWORDS, REDDIT_SUBREDDITS,
                        GOOGLE_PLAY_APP_ID, APP_STORE_APP_ID,
                        APP_STORE_APP_NAME)

    reddit  = scrape_reddit(BRAND_KEYWORDS, REDDIT_SUBREDDITS,
                            fetch_comments=True)
    news    = scrape_news(brand_name, days_back=7, max_articles=100)
    reviews = scrape_app_reviews(GOOGLE_PLAY_APP_ID,
                                 APP_STORE_APP_ID,
                                 APP_STORE_APP_NAME)

    # save raw files
    data_dir = Path(db_path).parent
    json.dump(reddit,  open(data_dir / "reddit_raw.json",  "w"))
    json.dump(news,    open(data_dir / "news_raw.json",    "w"))
    json.dump(reviews, open(data_dir / "reviews_raw.json", "w"))

    counts = {
        "reddit":  len(reddit),
        "news":    len(news),
        "reviews": len(reviews),
        "total":   len(reddit) + len(news) + len(reviews),
    }
    logger.info(f"Ingested: {counts}")
    return counts


@task(
    name="normalize-and-store",
    description="Normalize text and upsert into SQLite",
    retries=2,
    retry_delay_seconds=30,
)
def task_normalize_store(brand_name: str, db_path: str,
                         ingest_counts: dict) -> int:
    logger = get_run_logger()
    logger.info(f"Normalizing {ingest_counts.get('total', 0)} raw records")

    import json
    from pathlib import Path
    from scrapers.normalizer import normalize_mentions
    from database import init_db, insert_mentions

    data_dir = Path(db_path).parent
    raw = []
    for fname in ["reddit_raw.json", "news_raw.json", "reviews_raw.json"]:
        path = data_dir / fname
        if path.exists():
            raw.extend(json.load(open(path)))

    normalized = normalize_mentions(raw)
    db         = init_db(db_path)
    inserted   = insert_mentions(db, normalized, brand_name)

    logger.info(f"Normalized: {len(normalized)}, "
                f"inserted/updated: {inserted}")
    return len(normalized)


@task(
    name="run-sentiment-analysis",
    description="PyABSA aspect extraction + distilBERT fallback",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=3600,    # NLP can take up to 1 hour on large datasets
)
def task_run_sentiment(brand_name: str, db_path: str) -> dict:
    logger = get_run_logger()
    logger.info("Running sentiment pipeline")

    from nlp.sentiment_engine import (run_sentiment_pipeline,
                                      run_fallback_pipeline)
    import sqlite_utils

    run_sentiment_pipeline(db_path=db_path,
                           brand_name=brand_name,
                           batch_size=16)
    run_fallback_pipeline(db_path=db_path,
                          brand_name=brand_name,
                          batch_size=32)

    db    = sqlite_utils.Database(db_path)
    total = db["scored_mentions"].count
    logger.info(f"Scored mentions in DB: {total}")
    return {"scored_total": total}


@task(
    name="aggregate-daily",
    description="Aggregate scored mentions into daily time series",
    retries=2,
    retry_delay_seconds=30,
)
def task_aggregate(brand_name: str, db_path: str) -> int:
    logger = get_run_logger()
    logger.info("Aggregating daily scores")
    from analytics.aggregator import run_aggregation
    run_aggregation(db_path, brand_name)

    import sqlite_utils
    db    = sqlite_utils.Database(db_path)
    total = db["brand_health_daily"].count
    logger.info(f"Daily rows in DB: {total}")
    return total


@task(
    name="detect-trends",
    description="Rolling z-score spike detection",
    retries=2,
    retry_delay_seconds=30,
)
def task_detect_trends(brand_name: str, db_path: str) -> int:
    logger = get_run_logger()
    logger.info("Running trend detection")

    from analytics.trend_detector import run_detection
    alerts = run_detection(db_path, brand_name)

    logger.info(f"Alerts detected: {len(alerts)}")
    return len(alerts)


@task(
    name="compute-health-score",
    description="Compute composite 0-100 brand health score",
    retries=2,
    retry_delay_seconds=30,
)
def task_compute_health(brand_name: str, db_path: str) -> dict:
    logger = get_run_logger()
    logger.info("Computing brand health score")

    from analytics.health_score import (run_health_score,
                                        get_current_score)
    run_health_score(db_path, brand_name)
    score = get_current_score(db_path, brand_name)

    logger.info(
        f"Current health score: {score.get('health_score', 0):.1f}/100"
        if score else "No score computed"
    )
    return score or {}


@task(
    name="fire-alerts",
    description="Send Slack and email notifications for new alerts",
    retries=1,
    retry_delay_seconds=60,
)
def task_fire_alerts(brand_name: str, db_path: str) -> dict:
    logger = get_run_logger()
    logger.info("Firing alert notifications")

    from analytics.alert_engine import run_alert_engine
    run_alert_engine(db_path, brand_name)

    import sqlite_utils
    db    = sqlite_utils.Database(db_path)
    fired = db["alert_log"].count
    logger.info(f"Total alert log entries: {fired}")
    return {"alert_log_total": fired}


# ── Flow ───────────────────────────────────────────────────────────────

@flow(
    name="brand-reputation-pipeline",
    description=(
        "End-to-end brand reputation monitoring: "
        "ingest → NLP → trend detection → alerts"
    ),
    log_prints=True,
)
def brand_reputation_pipeline(
    brand_name: str = "Netflix",
    db_path:    str = "data/brand_mentions.db",
):
    logger = get_run_logger()
    logger.info(f"Pipeline started | Brand: {brand_name}")

    # stage 1 — ingest
    counts = task_ingest(brand_name, db_path)
    logger.info(f"Stage 1 done: {counts['total']} records ingested")

    # stage 2 — normalize
    n_records = task_normalize_store(brand_name, db_path, counts)
    logger.info(f"Stage 2 done: {n_records} records normalized")

    # stage 3 — sentiment
    sentiment_result = task_run_sentiment(brand_name, db_path)
    logger.info(f"Stage 3 done: {sentiment_result}")

    # stage 4 — aggregate
    daily_rows = task_aggregate(brand_name, db_path)
    logger.info(f"Stage 4 done: {daily_rows} daily rows")

    # stage 5 — trend detection
    alert_count = task_detect_trends(brand_name, db_path)
    logger.info(f"Stage 5 done: {alert_count} alerts detected")

    # stage 6 — health score
    health = task_compute_health(brand_name, db_path)
    logger.info(
        f"Stage 6 done: health score = {health.get('health_score', 0):.1f}/100"
    )

    # stage 7 — fire alerts
    alert_result = task_fire_alerts(brand_name, db_path)
    logger.info(f"Stage 7 done: {alert_result}")

    # final summary
    summary = {
        "brand":        brand_name,
        "ingested":     counts["total"],
        "normalized":   n_records,
        "scored":       sentiment_result.get("scored_total", 0),
        "daily_rows":   daily_rows,
        "alerts":       alert_count,
        "health_score": health.get("health_score", 0),
    }
    logger.info(f"Pipeline complete: {summary}")
    return summary


# ── Entry points ───────────────────────────────────────────────────────

def local_run():
    """Run the flow immediately — for testing."""
    from config import BRAND_NAME, DB_PATH
    result = brand_reputation_pipeline(
        brand_name=BRAND_NAME,
        db_path=DB_PATH,
    )
    print("\nFinal summary:")
    for k, v in result.items():
        print(f"  {k:15}: {v}")


def deploy_scheduled():
    """
    Serve the flow with a weekly schedule via Prefect 3.
    Blocks the process — run in a dedicated terminal or background service.
    Requires: prefect server start && prefect config set PREFECT_API_URL=...
    """
    from config import BRAND_NAME, DB_PATH
    print("Starting weekly scheduled deployment (Prefect 3)...")
    print("Dashboard: http://127.0.0.1:4200")
    brand_reputation_pipeline.serve(
        name="weekly-brand-monitor",
        schedules=[Interval(timedelta(weeks=1))],
        parameters={
            "brand_name": BRAND_NAME,
            "db_path":    DB_PATH,
        },
        tags=["brand-monitor", "weekly"],
    )


if __name__ == "__main__":
    import sys as _sys
    cmd = _sys.argv[1] if len(_sys.argv) > 1 else "run"

    if cmd == "run":
        local_run()
    elif cmd == "deploy":
        deploy_scheduled()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python pipeline/prefect_flow.py [run|deploy]")
