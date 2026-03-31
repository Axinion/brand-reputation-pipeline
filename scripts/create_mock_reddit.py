import json
import random
from datetime import datetime, timezone, timedelta
from collections import Counter

subreddits = ["netflix", "television", "movies", "cordcutters"]

posts = [
    "Has anyone watched the new Netflix documentary? Absolutely incredible production quality",
    "Netflix price increase again - third time in two years, is it still worth it?",
    "The Netflix UI redesign makes it so much harder to find what I want to watch",
    "Best Netflix originals of 2026 ranked - some real gems this quarter",
    "Netflix customer support took 4 days to respond to a billing issue, very frustrating",
    "Netflix 4K streaming quality has degraded noticeably on my TV lately",
    "New Netflix download feature is actually really useful for travel",
    "Netflix cancelled another show after 2 seasons right on a cliffhanger",
    "Just finished a Netflix series in one sitting - best thing they have made in years",
    "Netflix recommendation algorithm keeps showing me stuff I have already watched",
    "Netflix password sharing crackdown is pushing me toward other services",
    "The new Netflix interface on mobile is actually a huge improvement",
    "Netflix original movies have really improved in quality recently",
    "Still no fix for the Netflix audio sync issue on older smart TVs",
    "Netflix raising prices while cancelling good shows is really frustrating",
    "Surprised by how good this Netflix hidden gem is - algorithm never showed it to me",
    "Netflix live events are getting better but the stream quality needs work",
    "The Netflix kids section is excellent - my children love it",
    "Netflix subtitles are often wrong or poorly timed on international content",
    "Netflix is the only streaming service I cannot bring myself to cancel",
]

base_time = datetime.now(tz=timezone.utc)
mentions = []

for i in range(400):
    sub = random.choice(subreddits)
    mentions.append(
        {
            "id": f"mock_reddit_{i:04d}",
            "source": "reddit",
            "source_detail": sub,
            "timestamp": (
                base_time - timedelta(hours=random.randint(1, 720))
            ).isoformat(),
            "text": random.choice(posts),
            "url": f"https://reddit.com/r/{sub}/comments/mock{i:04d}",
            "score": random.randint(1, 850),
            "mention_type": random.choice(["post", "comment"]),
        }
    )

with open("data/reddit_raw.json", "w") as f:
    json.dump(mentions, f, indent=2)

print(f"Created {len(mentions)} mock Reddit mentions")
print("Subreddit breakdown:")
print(dict(Counter(m["source_detail"] for m in mentions)))
