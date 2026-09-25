"""Shared test setup: import paths and a hermetic environment (no real AWS, site or Telegram)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "dashboard" / "backend")]

# parking_bot reads its configuration at import time.
os.environ.update(
    TELEGRAM_TOKEN="test-token",
    TELEGRAM_CHAT_ID="1",
    SITE_EMAIL="user@example.com",
    SITE_PASSWORD="secret",
)

# Never touch a real AWS profile: dummy static credentials win over any local
# config / `aws login` session, and the config files point nowhere.
os.environ.update(
    AWS_DEFAULT_REGION="eu-central-1",
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_CONFIG_FILE=os.devnull,
    AWS_SHARED_CREDENTIALS_FILE=os.devnull,
)
