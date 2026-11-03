import json
from pathlib import Path


MONGO_URI = (
    "mongodb://adding_social_accounts_user:45dfgd454gf26zeerf"
    "@57.129.18.234:27017/leadfeeder-social-accounts"
    "?authSource=leadfeeder-social-accounts"
)
DB_NAME = "leadfeeder-social-accounts"
COLLECTION = "adding_social_accounts"
CHECKPOINT_COLLECTION = "linkedin_enrichment_progress"
CHECKPOINT_ID = "missing_linkedin_companies"
MONGO_BATCH_SIZE = 100

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_JSON = PROJECT_DIR / "linkedin_results.json"
CONFIG_JSON = PROJECT_DIR / "configuration" / "config.json"
CHROME_PROFILE_DIR = PROJECT_DIR / "chrome_profile"

LI_HOME_URL = "https://www.linkedin.com"
LI_FEED_URL = "https://www.linkedin.com/feed/"
LI_SEARCH_URL = "https://www.linkedin.com/search/results/companies/?keywords={query}"
LI_LOGIN_URL = "https://www.linkedin.com/login"
GOOGLE_SEARCH = "https://www.google.com/search?q={query}"

BLACKLIST_SLUGS = {
    "setup", "new", "about", "security", "careers", "press", "legal",
    "terms", "privacy", "help", "pulse", "feed", "search", "jobs",
    "learning", "premium", "recruiter", "talent", "ads", "mycompany",
    "showcase", "events", "school", "products", "checkpoint", "authwall",
    "login", "signup"
}

WAIT_PAGE = 8
WAIT_BETWEEN = 2.5


def load_results() -> dict:
    if OUTPUT_JSON.exists():
        try:
            return json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_results(data: dict) -> None:
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict:
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_JSON.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")