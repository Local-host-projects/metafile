"""
Account auth: email + password login issuing signed tokens.

- Passwords: PBKDF2-HMAC-SHA256 (210k rounds, per-user salt), stdlib only.
- Tokens: stateless `user_id.expiry.sig` triples, HMAC-SHA256 signed with
  the app SECRET_KEY. Verified with compare_digest. No server-side store,
  no extra dependencies.
"""
import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException, Request

import config

TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days


# ---------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 210_000
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), 210_000
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------- tokens

def issue_token(user_id: str) -> str:
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    body = f"{user_id}.{exp}"
    sig = hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str):
    """Returns the user_id, or None if missing/malformed/expired/forged."""
    try:
        user_id, exp, sig = token.split(".", 2)
        if int(exp) < time.time():
            return None
        expected = hmac.new(
            config.SECRET_KEY.encode(), f"{user_id}.{exp}".encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        return user_id
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------- request helpers

def _bearer_token(request: Request):
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def optional_user(db, request: Request):
    """The logged-in User, or None. Never raises."""
    from models import User  # local import: models must not import auth
    token = _bearer_token(request)
    if not token:
        return None
    user_id = verify_token(token)
    if not user_id:
        return None
    return db.get(User, user_id)


def get_current_user(db, request: Request):
    """The logged-in User, or 401."""
    user = optional_user(db, request)
    if user is None:
        raise HTTPException(401, "Not signed in -- log in and retry with your session token.")
    return user


class Scope:
    READ = "read"
    WRITE = "write"


def resolve_access(db, metafile, request: Request, token, required: str):
    """Who is acting on this metafile, and may they?

    Returns (role, user). Roles: owner (full) | rw (capability write) |
    ro (capability read) | unclaimed (logged-in user reading a legacy
    ownerless file -- read-only until claimed). Raises 401/403 otherwise.
    """
    from models import hash_token  # local import: models must not import auth
    user = optional_user(db, request)
    if user is not None and metafile.owner_id == user.id:
        return ("owner", user)

    if token:
        h = hash_token(token)
        if h == metafile.rw_token_hash:
            return ("rw", user)
        if h == metafile.ro_token_hash:
            if required == Scope.READ:
                return ("ro", user)
            raise HTTPException(403, "This is a read-only link for this metafile; "
                                     "use the read-write URL to mutate it")
        raise HTTPException(403, "Invalid token for this metafile")

    if user is not None and metafile.owner_id is None:
        if required == Scope.READ:
            return ("unclaimed", user)
        raise HTTPException(403, "Claim this metafile to your account before editing it")

    if user is not None:
        raise HTTPException(403, "This metafile belongs to another account")
    raise HTTPException(401, "Missing token: this metafile is capability-URL authed, "
                              "so the link itself is the credential -- append ?token=...")
