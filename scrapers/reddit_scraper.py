import hashlib
import time
from datetime import datetime, timezone

import requests


HEADERS = {
    "User-Agent": "Mozilla/5.0 brand-monitor research project v1.0"
}


def _fetch_json(url, params=None):
    """Fetch JSON with retries and rate-limit handling."""
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=10)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "2")
                try:
                    sleep_seconds = float(retry_after)
                except ValueError:
                    sleep_seconds = 2.0
                print(f"Rate limited (429). Sleeping {sleep_seconds}s before retry.")
                time.sleep(sleep_seconds)
                continue

            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "data" not in data and "error" in data:
                print(f"  Reddit error: {data.get('message', 'unknown')}")
                return None
            return data
        except Exception as exc:
            if attempt == max_retries:
                print(f"Failed after {max_retries} attempts for {url}: {exc}")
                return None
            print(f"Fetch error (attempt {attempt}/{max_retries}) for {url}: {exc}")
            time.sleep(1)

    return None


def _make_id(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _iso(utc_timestamp):
    dt = datetime.fromtimestamp(float(utc_timestamp), tz=timezone.utc)
    return dt.isoformat()


def scrape_subreddit_search(subreddit, keyword, limit=100):
    results = []
    after = None

    while len(results) < limit:
        params = {
            "q": keyword,
            "restrict_sr": 1,
            "sort": "new",
            "limit": 100,
            "t": "month",
        }
        if after:
            params["after"] = after

        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        payload = _fetch_json(url, params=params)
        if not payload:
            break

        data = payload.get("data", {})
        children = data.get("children", [])
        if not children:
            break

        for item in children:
            post = item.get("data", {})
            permalink = post.get("permalink", "")
            post_url = (
                f"https://www.reddit.com{permalink}"
                if permalink
                else post.get("url", "")
            )
            title = post.get("title", "") or ""
            selftext = post.get("selftext", "") or ""
            merged_text = (title + "\n" + selftext).strip()

            raw_id = post.get("id") or f"{subreddit}:{title}:{post.get('created_utc', 0)}"
            mention_id = _make_id(f"reddit_post:{raw_id}")

            results.append(
                {
                    "id": mention_id,
                    "source": "reddit",
                    "source_detail": subreddit,
                    "timestamp": _iso(post.get("created_utc", 0)),
                    "text": merged_text,
                    "url": post_url,
                    "score": post.get("score", 0),
                    "mention_type": "post",
                }
            )

            if len(results) >= limit:
                break

        after = data.get("after")
        if not after or len(results) >= limit:
            break

        time.sleep(2)

    return results


def scrape_post_comments(post_url, subreddit="unknown", max_comments=20):
    comments = []

    if post_url.endswith(".json"):
        comments_url = post_url
    else:
        comments_url = post_url.rstrip("/") + ".json"

    payload = _fetch_json(comments_url, params={"limit": max_comments, "sort": "top"})
    if not payload or not isinstance(payload, list) or len(payload) < 2:
        return comments

    comment_listing = payload[1].get("data", {}).get("children", [])
    for item in comment_listing:
        if item.get("kind") != "t1":
            continue

        data = item.get("data", {})
        body = (data.get("body") or "").strip()
        if not body or body in {"[deleted]", "[removed]"}:
            continue

        permalink = data.get("permalink", "")
        comment_url = f"https://www.reddit.com{permalink}" if permalink else post_url
        raw_id = data.get("id") or f"{comment_url}:{data.get('created_utc', 0)}"
        mention_id = _make_id(f"reddit_comment:{raw_id}")

        comments.append(
            {
                "id": mention_id,
                "source": "reddit",
                "source_detail": subreddit,
                "timestamp": _iso(data.get("created_utc", 0)),
                "text": body,
                "url": comment_url,
                "score": data.get("score", 0),
                "mention_type": "comment",
            }
        )

        if len(comments) >= max_comments:
            break

    return comments


def scrape_reddit(keywords, subreddits, fetch_comments=True):
    if not keywords:
        print("No keywords supplied; skipping Reddit scrape.")
        return []

    keyword = keywords[0]
    all_mentions = []
    seen_ids = set()

    for subreddit in subreddits:
        print(f"Searching r/{subreddit} for keyword: {keyword}")
        posts = scrape_subreddit_search(subreddit, keyword, limit=100)
        print(f"  Found {len(posts)} posts in r/{subreddit}")

        for post in posts:
            if post["id"] in seen_ids:
                continue
            seen_ids.add(post["id"])
            all_mentions.append(post)

        if not fetch_comments:
            continue

        comment_count = 0
        for post in posts:
            post_comments = scrape_post_comments(
                post["url"], subreddit=subreddit, max_comments=20
            )
            for comment in post_comments:
                if comment["id"] in seen_ids:
                    continue
                seen_ids.add(comment["id"])
                all_mentions.append(comment)
                comment_count += 1
            time.sleep(0.5)
        print(f"  Fetched {comment_count} comments from r/{subreddit}")

    print(f"Reddit scrape complete. Total unique mentions: {len(all_mentions)}")
    return all_mentions

if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from config import BRAND_KEYWORDS

    test_keyword = BRAND_KEYWORDS[0]
    test_subreddits = ["netflix"]

    print(f"Testing Reddit scraper for: {test_keyword}")
    print(f"Subreddits: {test_subreddits}")
    print("-" * 40)

    results = scrape_reddit(
        keywords=[test_keyword],
        subreddits=test_subreddits,
        fetch_comments=False,
    )

    print(f"\nTotal collected: {len(results)}")
    if results:
        print("\nSample post record:")
        sample = results[0]
        print(f"  id              : {sample.get('id', '')}")
        print(f"  source          : {sample.get('source', '')}")
        print(f"  source_detail   : {sample.get('source_detail', '')}")
        print(f"  timestamp       : {sample.get('timestamp', '')}")
        text_val = sample.get("text", "")
        text_preview = (text_val[:60] + "...") if len(text_val) > 60 else text_val
        print(f"  text            : {text_preview}")
        print(f"  url             : {sample.get('url', '')}")
        print(f"  score           : {sample.get('score', 0)}")
        print(f"  mention_type    : {sample.get('mention_type', '')}")