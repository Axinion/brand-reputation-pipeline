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

# LLM Report Generation
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Alerting
SLACK_WEBHOOK_URL    = os.getenv("SLACK_WEBHOOK_URL", "")
ALERT_EMAIL_FROM     = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_TO       = os.getenv("ALERT_EMAIL_TO", "")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")
SMTP_HOST            = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT            = int(os.getenv("SMTP_PORT", "587"))
