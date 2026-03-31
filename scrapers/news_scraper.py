import datetime
import hashlib
import os
import re
import time

import requests
from dotenv import load_dotenv


load_dotenv()

BASE_URL = "https://newsapi.org/v2/everything"
NEWS_API_KEY = os.getenv("NEWS_API_KEY")


def _make_id(url):
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]


def _iso(date_string):
    if not date_string:
        return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    clean = date_string.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(clean).isoformat()


def scrape_news(brand_name, days_back=30, max_articles=300):
    if not NEWS_API_KEY:
        print("NEWS_API_KEY missing; cannot scrape news.")
        return []

    if days_back > 30:
        print("days_back > 30 is not supported on free tier; capping to 30.")
        days_back = 30

    mentions = []
    seen_urls = set()

    from_date = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)
    ).strftime("%Y-%m-%d")
    page = 1

    while len(mentions) < max_articles:
        if page > 3:
            break
        params = {
            "q": brand_name,
            "language": "en",
            "sortBy": "relevancy",
            "pageSize": 100,
            "from": from_date,
            "page": page,
            "apiKey": NEWS_API_KEY,
        }

        try:
            response = requests.get(BASE_URL, params=params, timeout=10)
            if response.status_code == 426:
                print(f"  NewsAPI free tier limit reached — stopping at page {page}")
                break
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"NewsAPI request failed on page {page}: {exc}")
            break

        if payload.get("status") != "ok":
            code = payload.get("code", "unknown")
            message = payload.get("message", "unknown")
            if code == "rateLimited":
                print("NewsAPI rate limit reached; stop now and retry later.")
                break
            if code == "parameterInvalid":
                print(f"NewsAPI parameter error: {message}")
                break
            print(
                "NewsAPI returned error: "
                f"{code} - {message}"
            )
            break

        articles = payload.get("articles", [])
        print(f"Page {page}: received {len(articles)} articles")
        if not articles:
            break

        for article in articles:
            url = (article.get("url") or "").strip()
            if not url or url in seen_urls:
                continue

            seen_urls.add(url)
            title = article.get("title") or ""
            description = article.get("description") or ""
            content = article.get("content") or ""
            text = f"{title} {description} {content}".strip()
            text = re.sub(r"\[\+\d+ chars\]", "", text).strip()

            published_at = article.get("publishedAt") or ""
            timestamp = _iso(published_at) if published_at else ""

            mentions.append(
                {
                    "id": _make_id(url),
                    "source": "news",
                    "source_detail": (article.get("source") or {}).get("name", ""),
                    "timestamp": timestamp,
                    "text": text,
                    "url": url,
                    "score": 0,
                    "mention_type": "article",
                }
            )

            if len(mentions) >= max_articles:
                break

        page += 1
        if page <= 3 and len(mentions) < max_articles:
            time.sleep(1)

    return mentions


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from config import BRAND_NAME

    results = scrape_news(BRAND_NAME, days_back=30, max_articles=300)
    print(f"Total collected: {len(results)}")

    if results:
        print("\nSample record:")
        sample = results[0]
        print(f"  id              : {sample.get('id', '')}")
        print(f"  source          : {sample.get('source', '')}")
        print(f"  source_detail   : {sample.get('source_detail', '')}")
        print(f"  timestamp       : {sample.get('timestamp', '')}")
        print(f"  text            : {sample.get('text', '')[:100]}")
        print(f"  url             : {sample.get('url', '')}")
        print(f"  score           : {sample.get('score', 0)}")
        print(f"  mention_type    : {sample.get('mention_type', '')}")
