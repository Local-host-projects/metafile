"""
Size metering, tiers, and real Paystack payments.

Free tier: 5 MiB per metafile. Paid: 100 MiB, unlocked by a verified
Paystack charge (card, bank account, or bank transfer -- selected via
the `channels` param at initialize time).

No third-party HTTP client: Paystack is called with stdlib urllib.
"""
import hashlib
import hmac
import json
import urllib.request
import urllib.error
from fastapi import HTTPException

import config
from models import FREE_TIER_BYTES

PAID_TIER_BYTES = 100 * 1024 * 1024  # 100 MiB per paid metafile

PAYSTACK_API = "https://api.paystack.co"
PAYSTACK_CHANNELS = ["card", "bank", "bank_transfer"]


class PaymentError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------- size metering

def content_size(content: dict) -> int:
    return len(json.dumps(content).encode("utf-8"))


def enforce_total_limit(metafile, total_bytes: int):
    if total_bytes > metafile.byte_limit:
        limit_mb = metafile.byte_limit / (1024 * 1024)
        raise HTTPException(
            402,
            f"This write would make the metafile {total_bytes/1024:.1f}KB, over its "
            f"{limit_mb:.0f}MB {metafile.tier} limit. Upgrade to raise the cap."
        )
    return total_bytes


def upgrade_tier(metafile):
    """Flip to paid -- ONLY call after a verified Paystack charge
    (or the dev-only free-upgrade flag)."""
    metafile.tier = "paid"
    metafile.byte_limit = PAID_TIER_BYTES
    return metafile


# ------------------------------------------------------------ Paystack

def _paystack(method: str, path: str, payload: dict = None) -> dict:
    if not config.PAYSTACK_CONFIGURED:
        raise PaymentError(
            "Payments are not connected on this server -- set PAYSTACK_SECRET_KEY "
            "in backend/.env and restart.", status=501,
        )
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        PAYSTACK_API + path, data=data, method=method,
        headers={
            "Authorization": f"Bearer {config.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:
            detail = ""
        raise PaymentError(f"Paystack rejected the request ({e.code}) {detail}".strip(), status=502)
    except Exception as e:
        raise PaymentError(f"Could not reach Paystack: {e}", status=502)
    if not body.get("status"):
        raise PaymentError(f"Paystack error: {body.get('message', 'unknown')}", status=502)
    return body["data"]


def init_payment(email: str, amount_kobo: int, reference: str, metadata: dict) -> dict:
    """Returns {authorization_url, access_code, reference}."""
    return _paystack("POST", "/transaction/initialize", {
        "email": email,
        "amount": amount_kobo,
        "reference": reference,
        "callback_url": f"{config.APP_URL}/?paid={reference}",
        "channels": PAYSTACK_CHANNELS,
        "metadata": metadata,
    })


def verify_payment(reference: str) -> dict:
    """Returns the verified transaction data dict."""
    return _paystack("GET", f"/transaction/verify/{reference}")


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    if not config.PAYSTACK_CONFIGURED or not signature:
        return False
    expected = hmac.new(
        config.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
