import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "carbs.db"

# Claude does the photo reading. Override CLAUDE_MODEL to trade accuracy for cost.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Optional free key from https://fdc.nal.usda.gov/api-key-signup.html (DEMO_KEY works but is rate limited).
USDA_API_KEY = os.environ.get("USDA_API_KEY", "DEMO_KEY")

# If APP_PASSWORD is set the whole app sits behind HTTP basic auth.
APP_USER = os.environ.get("APP_USER", "carbs")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
USER_AGENT = "CarbTracker/1.0 (self-hosted)"
