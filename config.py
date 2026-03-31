import os
from dotenv import load_dotenv

load_dotenv()

BRAND_NAME = "Netflix"
BRAND_KEYWORDS = ["Netflix", "netflix"]
REDDIT_SUBREDDITS = ["netflix", "television", "movies", "cordcutters"]

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "brand-monitor/1.0")

GOOGLE_PLAY_APP_ID = "com.netflix.mediaclient"
APP_STORE_APP_ID = "363590051"
APP_STORE_APP_NAME = "netflix"

DB_PATH = "data/brand_mentions.db"
