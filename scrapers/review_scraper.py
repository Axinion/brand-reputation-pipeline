import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app_store_scraper import AppStore
from google_play_scraper import reviews as gp_reviews, Sort


def _make_id(text):
    return hashlib.md5(str(text).encode("utf-8")).hexdigest()[:16]


def _iso(dt):
    """Convert datetime object or string to UTC ISO string."""
    if dt is None:
        return datetime.now(tz=timezone.utc).isoformat()
    if isinstance(dt, datetime):
        # google_play_scraper returns timezone-aware datetimes
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    # handle string dates from app_store_scraper
    try:
        clean = str(dt).replace("Z", "+00:00")
        return datetime.fromisoformat(clean).isoformat()
    except Exception:
        return datetime.now(tz=timezone.utc).isoformat()


def scrape_google_play(app_id, count=300):
    try:
        raw_reviews, _ = gp_reviews(
            app_id,
            lang="en",
            country="us",
            sort=Sort.NEWEST,
            count=count,
        )
        if raw_reviews is None:
            print(f"Google Play returned no iterable reviews for app_id={app_id}")
            return []

        output = []
        for r in raw_reviews:
            review_id = r.get("reviewId", "")
            output.append(
                {
                    "id": _make_id(review_id),
                    "source": "app_review",
                    "source_detail": "google_play",
                    "timestamp": _iso(r.get("at")),
                    "text": (r.get("content") or "").strip(),
                    "url": "",
                    "score": int(r.get("score") or 0),
                    "mention_type": "review",
                }
            )
        return output
    except Exception as exc:
        print(f"Google Play scrape failed: {exc}")
        return []


def scrape_app_store(app_id, app_name, count=300):
    for attempt in range(1, 3):
        try:
            app = AppStore(country="us", app_name=app_name, app_id=str(app_id))
            app.review(how_many=count, sleep=2)

            filtered_reviews = [r for r in app.reviews if r.get("review")]
            output = []
            for r in filtered_reviews:
                review_id = r.get("id", "")
                output.append(
                    {
                        "id": _make_id(review_id),
                        "source": "app_review",
                        "source_detail": "app_store",
                        "timestamp": _iso(r.get("date")),
                        "text": (r.get("review") or "").strip(),
                        "url": "",
                        "score": int(r.get("rating") or 0),
                        "mention_type": "review",
                    }
                )
            return output
        except Exception as exc:
            if attempt == 2:
                print(f"App Store scrape failed: {exc}")
                return []
            print(f"App Store scrape attempt {attempt} failed, retrying: {exc}")
            time.sleep(2)


def scrape_app_reviews(google_play_id, app_store_id, app_store_name):
    gp_reviews = scrape_google_play(google_play_id, count=300)
    # Small pause to be polite to provider endpoints.
    time.sleep(0.5)
    as_reviews = scrape_app_store(app_store_id, app_store_name, count=300)

    merged = []
    seen_ids = set()
    for item in gp_reviews + as_reviews:
        rid = item.get("id")
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        merged.append(item)

    print("App review scrape summary:")
    print(f"  Google Play: {len(gp_reviews)}")
    print(f"  App Store:   {len(as_reviews)}")
    print(f"  Merged:      {len(merged)}")
    return merged


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from config import APP_STORE_APP_ID, APP_STORE_APP_NAME, GOOGLE_PLAY_APP_ID

    gp_reviews = scrape_google_play(GOOGLE_PLAY_APP_ID, count=50)
    as_reviews = scrape_app_store(APP_STORE_APP_ID, APP_STORE_APP_NAME, count=50)

    merged = []
    seen_ids = set()
    for item in gp_reviews + as_reviews:
        rid = item.get("id")
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        merged.append(item)

    print("\nTest summary (count=50 per store):")
    print(f"  Google Play: {len(gp_reviews)}")
    print(f"  App Store:   {len(as_reviews)}")
    print(f"  Merged:      {len(merged)}")

    if merged:
        sample = merged[0]
        print("\nSample record:")
        print(f"  id              : {sample.get('id', '')}")
        print(f"  source          : {sample.get('source', '')}")
        print(f"  source_detail   : {sample.get('source_detail', '')}")
        print(f"  timestamp       : {sample.get('timestamp', '')}")
        print(f"  text            : {sample.get('text', '')[:100]}")
        print(f"  url             : {sample.get('url', '')}")
        print(f"  score           : {sample.get('score', 0)}")
        print(f"  mention_type    : {sample.get('mention_type', '')}")
