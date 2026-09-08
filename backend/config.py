"""
App settings. Reads backend/.env (KEY=VALUE lines) plus real environment
variables -- no third-party dependencies. A SECRET_KEY is generated and
persisted to .env on first boot so login sessions survive restarts.
"""
import os
import secrets
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


def _load_dotenv():
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


def _secret_key() -> str:
    existing = os.environ.get("SECRET_KEY")
    if existing:
        return existing
    generated = secrets.token_hex(32)
    try:
        with open(ENV_PATH, "a", encoding="utf-8") as f:
            if ENV_PATH.stat().st_size and not open(ENV_PATH, encoding="utf-8").read().endswith("\n"):
                f.write("\n")
            f.write(f"SECRET_KEY={generated}\n")
    except OSError:
        pass
    os.environ["SECRET_KEY"] = generated
    return generated


SECRET_KEY = _secret_key()

# --- Paystack (real payments: card, bank, bank transfer) ---
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_CONFIGURED = bool(PAYSTACK_SECRET_KEY)
UPGRADE_AMOUNT_KOBO = int(os.environ.get("UPGRADE_AMOUNT_KOBO", "250000"))  # 2500 NGN
CURRENCY = os.environ.get("CURRENCY", "NGN")
APP_URL = os.environ.get("APP_URL", "http://localhost:4000").rstrip("/")

# --- Dev/testing only: instant free upgrade endpoint. NEVER true in prod. ---
ALLOW_FREE_UPGRADE = os.environ.get("ALLOW_FREE_UPGRADE", "false").lower() == "true"


def upgrade_display() -> str:
    major = UPGRADE_AMOUNT_KOBO / 100
    symbol = {"NGN": "\u20a6", "GHS": "GH\u20b5", "ZAR": "R", "USD": "$"}.get(CURRENCY, CURRENCY + " ")
    return f"{symbol}{major:,.0f}"
