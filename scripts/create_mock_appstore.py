import requests
import json
import hashlib
from datetime import datetime, timezone


def _make_id(text):
    return hashlib.md5(text.encode()).hexdigest()[:16]


def scrape_appstore_via_search(app_id="363590051", count=300):
    """
    Use iTunes customer reviews API endpoint directly.
    More reliable than app_store_scraper library.
    """
    reviews = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    }

    for page in range(1, 11):  # up to 10 pages of 50 reviews each
        url = (
            f"https://itunes.apple.com/us/rss/customerreviews/"
            f"page={page}/id={app_id}/sortby=mostrecent/json"
        )
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                print(f"  Page {page}: status {r.status_code} - stopping")
                break

            data = r.json()
            entries = data.get("feed", {}).get("entry", [])

            # first entry on page 1 is app metadata, not a review
            if page == 1 and entries:
                entries = entries[1:]

            if not entries:
                print(f"  Page {page}: no entries - stopping")
                break

            for entry in entries:
                review_id = entry.get("id", {}).get("label", "")
                text = entry.get("content", {}).get("label", "").strip()
                rating = entry.get("im:rating", {}).get("label", "0")
                updated = entry.get("updated", {}).get("label", "")

                if not text:
                    continue

                try:
                    ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).isoformat()
                except Exception:
                    ts = datetime.now(tz=timezone.utc).isoformat()

                reviews.append(
                    {
                        "id": _make_id(review_id or text),
                        "source": "app_review",
                        "source_detail": "app_store",
                        "timestamp": ts,
                        "text": text,
                        "url": "",
                        "score": int(rating),
                        "mention_type": "review",
                    }
                )

            print(
                f"  Page {page}: {len(entries)} reviews collected "
                f"(running total: {len(reviews)})"
            )

            if len(reviews) >= count:
                break

        except Exception as e:
            print(f"  Page {page} error: {e}")
            break

    return reviews[:count]


if __name__ == "__main__":
    print("Fetching App Store reviews via iTunes API...")
    reviews = scrape_appstore_via_search(app_id="363590051", count=300)
    print(f"\nTotal fetched: {len(reviews)}")

    if reviews:
        print("\nSample review:")
        r = reviews[0]
        print(f"  score : {r['score']}")
        print(f"  text  : {r['text'][:80]}...")
        print(f"  time  : {r['timestamp']}")

        # merge into existing reviews file
        try:
            with open("data/reviews_raw.json") as f:
                existing = json.load(f)
        except FileNotFoundError:
            existing = []

        existing_ids = {r["id"] for r in existing}
        new_reviews = [r for r in reviews if r["id"] not in existing_ids]
        combined = existing + new_reviews

        with open("data/reviews_raw.json", "w") as f:
            json.dump(combined, f, indent=2)

        print(f"\nAdded {len(new_reviews)} App Store reviews")
        print(f"Total reviews file now: {len(combined)} records")
    else:
        print("\nApple RSS still returning 0 - network is blocking Apple endpoints.")
        print("Proceeding with Google Play only (300 reviews is sufficient).")
