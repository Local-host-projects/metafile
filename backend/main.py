"""
Metafile API.

Flow: sign up / log in -> create metafiles (containers) -> add any
number of typed artifacts inside each one -> manage everything from
the dashboard. Every metafile also keeps its capability-URL share
links (rw/ro tokens), so any agent holding a link can fetch, query
and mutate through one address.

Artifact content ops ride on GET /m/{id} (small payloads) or
POST /m/{id}/bulk (large payloads), always scoped to one artifact
via `artifact=<id>`. Every write requires `agent` (provenance
fingerprint) and `if_version` (optimistic concurrency -- rejected
with 409 + current state on conflict).
"""
import json
import time
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Query, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

import config
import events
from models import (
    Metafile, Artifact, MutationLog, Session as Playground, Proposal,
    User, Payment, make_engine, make_session_factory, init_db,
    new_token, hash_token,
)
from sqlalchemy import event as sa_event
from auth import (
    get_current_user, optional_user, resolve_access, Scope,
    hash_password, verify_password, issue_token,
)
from billing import (
    enforce_total_limit, upgrade_tier, content_size, init_payment,
    verify_payment, verify_webhook_signature, PaymentError,
)
from search import search_facts
from artifacts.spreadsheet import evaluate_grid, FormulaError
from artifacts.simple import HANDLERS
from artifacts import media

ARTIFACT_TYPES = {"facts", "spreadsheet", "html", "canvas", "calendar", "timer", "media"}

TYPE_LABELS = {
    "facts": "Memory", "spreadsheet": "Spreadsheet", "html": "Page",
    "canvas": "Canvas", "calendar": "Calendar", "timer": "Timer", "media": "Media",
}

DEFAULT_CONTENT = {
    "facts": {"facts": []},
    "spreadsheet": {"cells": {}, "cols": 8, "rows": 20},
    "html": {"html": "<!-- start writing -->"},
    "canvas": {"width": 800, "height": 600, "strokes": []},
    "calendar": {"events": []},
    "timer": {"timers": []},
    "media": {"items": []},
}

engine = make_engine()
init_db(engine)
SessionLocal = make_session_factory(engine)

# ---- live sync: collect changed objects on flush, publish after commit ----
# Central hook instead of per-endpoint calls: every commit that touches a
# Metafile/Artifact/Session/Proposal publishes, so no write site can be
# forgotten. Clients just re-fetch on "changed".

def _track_live(pub, obj, deleted):
    if isinstance(obj, Metafile) and obj.id:
        pub.add(("mf", obj.id, "deleted" if deleted else "changed"))
    elif isinstance(obj, Artifact) and obj.metafile_id and not deleted:
        # cascade deletes would double-fire alongside the Metafile's own
        # "deleted" event, so only live artifacts publish "changed"
        pub.add(("mf", obj.metafile_id, "changed"))
    elif isinstance(obj, Playground) and obj.id:
        pub.add(("sess", obj.id, "changed"))
    elif isinstance(obj, Proposal) and obj.session_id:
        pub.add(("sess", obj.session_id, "proposals"))


@sa_event.listens_for(SessionLocal, "before_flush")
def _collect_live(session, flush_context, instances):
    pub = session.info.setdefault("live_pub", set())
    for obj in session.new:
        _track_live(pub, obj, deleted=False)
    for obj in session.dirty:
        _track_live(pub, obj, deleted=False)
    for obj in session.deleted:
        _track_live(pub, obj, deleted=True)


@sa_event.listens_for(SessionLocal, "after_commit")
def _publish_live(session, *args):
    for kind, oid, ev in session.info.pop("live_pub", set()):
        events.bus.publish((kind, oid), {"kind": ev, "at": time.time()})


@sa_event.listens_for(SessionLocal, "after_rollback")
def _drop_live(session, *args):
    session.info.pop("live_pub", None)

app = FastAPI(title="Metafile API", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ================================================================ helpers

def get_metafile_or_404(db, metafile_id: str) -> Metafile:
    mf = db.get(Metafile, metafile_id)
    if not mf:
        raise HTTPException(404, "No metafile with that id")
    return mf


def get_artifact_or_404(db, mf: Metafile, artifact_id: str) -> Artifact:
    art = db.get(Artifact, artifact_id)
    if not art or art.metafile_id != mf.id:
        raise HTTPException(404, "No such artifact in this metafile")
    return art


def require_artifact_id(artifact_id: Optional[str]) -> str:
    if not artifact_id:
        raise HTTPException(400, "This operation needs &artifact=<artifact id>")
    return artifact_id


def recompute_size(mf: Metafile) -> int:
    mf.bytes_used = sum(a.bytes_used for a in mf.artifacts)
    return mf.bytes_used


def artifact_view(art: Artifact) -> dict:
    raw = json.loads(art.content_json)
    computed = None
    content = raw
    if art.artifact_type == "spreadsheet":
        try:
            computed = {"evaluated": evaluate_grid(raw.get("cells", {}))}
        except FormulaError as e:
            computed = {"error": str(e)}
    else:
        get_state, _ = HANDLERS[art.artifact_type]
        content = get_state(raw)  # sorts events, live timers, strips media payloads
    view = {
        "id": art.id,
        "name": art.name,
        "type": art.artifact_type,
        "version": art.version,
        "bytes_used": art.bytes_used,
        "created_at": art.created_at,
        "updated_at": art.updated_at,
        "content": content,
    }
    if computed is not None:
        view["computed"] = computed
    return view


def metafile_view(mf: Metafile, role: str = "owner") -> dict:
    return {
        "id": mf.id,
        "name": mf.name,
        "tier": mf.tier,
        "bytes_used": mf.bytes_used,
        "byte_limit": mf.byte_limit,
        "version": mf.version,
        "claimed": mf.owner_id is not None,
        "owner": role == "owner",
        "created_at": mf.created_at,
        "updated_at": mf.updated_at,
        "artifacts": [artifact_view(a) for a in mf.artifacts],
    }


def record_mutation(db, mf, artifact_id, agent, op, path, old_version, summary):
    db.add(MutationLog(
        metafile_id=mf.id, artifact_id=artifact_id, agent=agent, op=op,
        path=path, old_version=old_version, new_version=mf.version
        if artifact_id is None else db.get(Artifact, artifact_id).version,
        summary=summary,
    ))


def _version_conflict(mf):
    raise HTTPException(
        409,
        {
            "error": "version_conflict",
            "message": "This metafile changed since you last read it. Re-fetch and retry.",
            "current_version": mf.version,
            "current_state": metafile_view(mf),
        },
    )


def _artifact_conflict(mf, art):
    raise HTTPException(
        409,
        {
            "error": "version_conflict",
            "message": "This artifact changed since you last read it. Re-fetch and retry.",
            "current_version": art.version,
            "current_state": artifact_view(art),
        },
    )


# ==================================================================== auth

class RegisterRequest(BaseModel):
    name: str = "Untitled"
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _user_view(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email,
            "created_at": user.created_at}


@app.post("/auth/register")
def register(req: RegisterRequest):
    email = (req.email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Enter a valid email address")
    if len(req.password or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(409, "An account with this email already exists -- log in instead")
        user = User(name=(req.name or "Untitled").strip() or "Untitled",
                    email=email, pw_hash=hash_password(req.password))
        db.add(user)
        db.commit()
        return {"token": issue_token(user.id), "user": _user_view(user)}
    finally:
        db.close()


@app.post("/auth/login")
def login(req: LoginRequest):
    email = (req.email or "").strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(req.password or "", user.pw_hash):
            raise HTTPException(401, "Wrong email or password")
        return {"token": issue_token(user.id), "user": _user_view(user)}
    finally:
        db.close()


@app.get("/auth/me")
def me(request: Request):
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        files = db.query(Metafile).filter(Metafile.owner_id == user.id).all()
        return {
            "user": _user_view(user),
            "stats": {
                "metafiles": len(files),
                "artifacts": sum(len(f.artifacts) for f in files),
                "bytes_used": sum(f.bytes_used for f in files),
            },
        }
    finally:
        db.close()


# ================================================================== billing

@app.get("/billing/config")
def billing_config():
    return {
        "configured": config.PAYSTACK_CONFIGURED,
        "public_key": config.PAYSTACK_PUBLIC_KEY or None,
        "amount_kobo": config.UPGRADE_AMOUNT_KOBO,
        "amount_display": config.upgrade_display(),
        "currency": config.CURRENCY,
        "channels": ["card", "bank account", "bank transfer"],
    }


def _apply_successful_payment(db, payment: Payment):
    mf = get_metafile_or_404(db, payment.metafile_id)
    if payment.status != "success":
        payment.status = "success"
        payment.decided_at = time.time()
    if mf.tier != "paid":
        upgrade_tier(mf)
        mf.updated_at = time.time()
    db.commit()
    return {"id": mf.id, "tier": mf.tier, "byte_limit": mf.byte_limit}


@app.post("/metafiles/{metafile_id}/upgrade/init")
def upgrade_init(metafile_id: str, request: Request):
    """Start a real Paystack charge. Returns the authorization URL --
    the payer completes card / bank / transfer there, then we verify."""
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        mf = get_metafile_or_404(db, metafile_id)
        if mf.owner_id != user.id:
            raise HTTPException(403, "Only the owning account can upgrade this metafile")
        if mf.tier == "paid":
            raise HTTPException(409, "This metafile is already on the paid tier")
        reference = f"upg_{mf.id[:14]}_{new_token()[:8]}"
        payment = Payment(reference=reference, metafile_id=mf.id,
                          user_id=user.id, amount_kobo=config.UPGRADE_AMOUNT_KOBO)
        db.add(payment)
        db.commit()
        try:
            data = init_payment(user.email, config.UPGRADE_AMOUNT_KOBO, reference,
                                {"kind": "upgrade", "metafile_id": mf.id, "user_id": user.id})
        except PaymentError as e:
            raise HTTPException(e.status, str(e))
        return {
            "authorization_url": data["authorization_url"],
            "reference": reference,
            "amount_display": config.upgrade_display(),
        }
    finally:
        db.close()


class VerifyRequest(BaseModel):
    reference: str


@app.post("/metafiles/{metafile_id}/upgrade/verify")
def upgrade_verify(metafile_id: str, body: VerifyRequest, request: Request):
    """Verify a Paystack reference server-side and unlock paid tier."""
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        mf = get_metafile_or_404(db, metafile_id)
        if mf.owner_id != user.id:
            raise HTTPException(403, "Only the owning account can upgrade this metafile")
        payment = db.query(Payment).filter(Payment.reference == body.reference).first()
        if not payment or payment.metafile_id != mf.id:
            raise HTTPException(404, "No such payment for this metafile")
        if payment.status == "success":
            return _apply_successful_payment(db, payment)
        try:
            data = verify_payment(body.reference)
        except PaymentError as e:
            raise HTTPException(e.status, str(e))
        meta = data.get("metadata") or {}
        if data.get("status") == "success" and data.get("amount") == payment.amount_kobo \
                and meta.get("metafile_id") == mf.id:
            return _apply_successful_payment(db, payment)
        payment.status = "failed" if data.get("status") == "failed" else payment.status
        payment.decided_at = time.time()
        db.commit()
        raise HTTPException(402, f"Payment not confirmed (Paystack status: {data.get('status')})")
    finally:
        db.close()


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request):
    """Paystack server event -- verified by HMAC-SHA512 signature."""
    raw = await request.body()
    sig = request.headers.get("x-paystack-signature", "")
    if not verify_webhook_signature(raw, sig):
        raise HTTPException(401, "Bad webhook signature")
    try:
        event = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise HTTPException(400, "Bad webhook payload")
    if event.get("event") == "charge.success":
        data = event.get("data") or {}
        meta = data.get("metadata") or {}
        if meta.get("kind") == "upgrade" and data.get("status") == "success":
            db = SessionLocal()
            try:
                payment = db.query(Payment).filter(
                    Payment.reference == data.get("reference")).first()
                if payment and payment.status != "success" \
                        and data.get("amount") == payment.amount_kobo:
                    _apply_successful_payment(db, payment)
            finally:
                db.close()
    return {"ok": True}


@app.post("/metafiles/{metafile_id}/upgrade/free")
def upgrade_free(metafile_id: str, request: Request):
    """DEV ONLY -- instant upgrade without payment. 404s unless the
    server was started with ALLOW_FREE_UPGRADE=true."""
    if not config.ALLOW_FREE_UPGRADE:
        raise HTTPException(404, "Not found")
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        mf = get_metafile_or_404(db, metafile_id)
        if mf.owner_id != user.id:
            raise HTTPException(403, "Only the owning account can upgrade this metafile")
        upgrade_tier(mf)
        db.commit()
        return {"id": mf.id, "tier": mf.tier, "byte_limit": mf.byte_limit}
    finally:
        db.close()


# ============================================================ dashboard CRUD

class CreateRequest(BaseModel):
    name: str = "Untitled metafile"


class RenameRequest(BaseModel):
    name: str


def _file_card(db, mf: Metafile, mine: bool) -> dict:
    return {
        "id": mf.id,
        "name": mf.name,
        "tier": mf.tier,
        "bytes_used": mf.bytes_used,
        "byte_limit": mf.byte_limit,
        "version": mf.version,
        "mine": mine,
        "claimed": mf.owner_id is not None,
        "artifact_count": len(mf.artifacts),
        "artifacts": [{"id": a.id, "name": a.name, "type": a.artifact_type} for a in mf.artifacts],
        "updated_at": mf.updated_at,
        "created_at": mf.created_at,
    }


@app.get("/metafiles")
def list_metafiles(request: Request):
    """Dashboard listing: my files plus legacy unclaimed ones (claimable)."""
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        rows = db.query(Metafile).order_by(Metafile.updated_at.desc()).all()
        return [_file_card(db, m, m.owner_id == user.id)
                for m in rows if m.owner_id == user.id or m.owner_id is None]
    finally:
        db.close()


@app.post("/metafiles")
def create_metafile(req: CreateRequest, request: Request):
    rw_raw, ro_raw = new_token(), new_token()
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        mf = Metafile(
            name=(req.name or "Untitled metafile").strip() or "Untitled metafile",
            owner_id=user.id,
            rw_token_hash=hash_token(rw_raw),
            ro_token_hash=hash_token(ro_raw),
        )
        db.add(mf)
        db.flush()
        db.add(MutationLog(metafile_id=mf.id, artifact_id=None, agent=user.email,
                           op="create", path=None, old_version=0, new_version=1,
                           summary="metafile created"))
        db.commit()
        base = str(request.base_url).rstrip("/")
        return {
            "id": mf.id,
            "name": mf.name,
            "rw_token": rw_raw,
            "ro_token": ro_raw,
            "rw_url": f"{base}/m/{mf.id}?token={rw_raw}",
            "ro_url": f"{base}/m/{mf.id}?token={ro_raw}",
        }
    finally:
        db.close()


@app.patch("/metafiles/{metafile_id}")
def rename_metafile(metafile_id: str, req: RenameRequest, request: Request,
                    token: Optional[str] = Query(None)):
    db = SessionLocal()
    try:
        mf = get_metafile_or_404(db, metafile_id)
        role, _ = resolve_access(db, mf, request, token, Scope.WRITE)
        if role not in ("owner", "rw"):
            raise HTTPException(403, "Only the owner or a read-write link can rename")
        mf.name = (req.name or "Untitled metafile").strip() or "Untitled metafile"
        mf.version += 1
        mf.updated_at = time.time()
        db.commit()
        return {"id": mf.id, "name": mf.name, "version": mf.version}
    finally:
        db.close()


@app.delete("/metafiles/{metafile_id}")
def delete_metafile(metafile_id: str, request: Request):
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        mf = get_metafile_or_404(db, metafile_id)
        if mf.owner_id != user.id:
            raise HTTPException(403, "Only the owning account can delete this metafile")
        db.delete(mf)
        db.commit()
        return {"deleted": metafile_id}
    finally:
        db.close()


@app.post("/metafiles/{metafile_id}/claim")
def claim_metafile(metafile_id: str, request: Request):
    """Adopt a legacy ownerless metafile into your account."""
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        mf = get_metafile_or_404(db, metafile_id)
        if mf.owner_id is not None:
            raise HTTPException(409, "Already claimed by an account")
        mf.owner_id = user.id
        mf.updated_at = time.time()
        db.commit()
        return {"id": mf.id, "owner": True}
    finally:
        db.close()


@app.post("/metafiles/{metafile_id}/rotate")
def rotate_tokens(metafile_id: str, request: Request):
    """Owner-only: invalidate old share links and mint fresh ones
    (shown once -- only hashes are stored)."""
    db = SessionLocal()
    try:
        user = get_current_user(db, request)
        mf = get_metafile_or_404(db, metafile_id)
        if mf.owner_id != user.id:
            raise HTTPException(403, "Only the owning account can rotate share links")
        rw_raw, ro_raw = new_token(), new_token()
        mf.rw_token_hash = hash_token(rw_raw)
        mf.ro_token_hash = hash_token(ro_raw)
        mf.updated_at = time.time()
        db.commit()
        base = str(request.base_url).rstrip("/")
        return {
            "rw_token": rw_raw, "ro_token": ro_raw,
            "rw_url": f"{base}/m/{mf.id}?token={rw_raw}",
            "ro_url": f"{base}/m/{mf.id}?token={ro_raw}",
        }
    finally:
        db.close()


# --------------------------------------------------------------- artifacts

class AddArtifactRequest(BaseModel):
    artifact_type: str
    name: Optional[str] = None
    agent: str = "unknown"
    if_version: int


@app.post("/metafiles/{metafile_id}/artifacts")
def add_artifact(metafile_id: str, req: AddArtifactRequest, request: Request,
                 token: Optional[str] = Query(None)):
    if req.artifact_type not in ARTIFACT_TYPES:
        raise HTTPException(400, f"artifact_type must be one of {sorted(ARTIFACT_TYPES)}")
    db = SessionLocal()
    try:
        mf = get_metafile_or_404(db, metafile_id)
        role, _ = resolve_access(db, mf, request, token, Scope.WRITE)
        if role not in ("owner", "rw"):
            raise HTTPException(403, "Only the owner or a read-write link can add artifacts")
        if req.if_version != mf.version:
            _version_conflict(mf)
        label = TYPE_LABELS[req.artifact_type]
        existing = sum(1 for a in mf.artifacts if a.artifact_type == req.artifact_type)
        art = Artifact(
            metafile_id=mf.id,
            name=(req.name or f"{label} {existing + 1}").strip() or label,
            artifact_type=req.artifact_type,
            content_json=json.dumps(DEFAULT_CONTENT[req.artifact_type]),
            bytes_used=content_size(DEFAULT_CONTENT[req.artifact_type]),
        )
        db.add(art)
        db.flush()
        recompute_size(mf)
        mf.version += 1
        mf.updated_at = time.time()
        record_mutation(db, mf, art.id, req.agent, "add_artifact", None,
                        req.if_version, f"added {label} '{art.name}'")
        db.commit()
        return {"metafile_version": mf.version, "artifact": artifact_view(art)}
    finally:
        db.close()


@app.delete("/metafiles/{metafile_id}/artifacts/{artifact_id}")
def remove_artifact(metafile_id: str, artifact_id: str, request: Request,
                    token: Optional[str] = Query(None),
                    agent: str = Query("unknown"), if_version: int = Query(...)):
    db = SessionLocal()
    try:
        mf = get_metafile_or_404(db, metafile_id)
        role, _ = resolve_access(db, mf, request, token, Scope.WRITE)
        if role not in ("owner", "rw"):
            raise HTTPException(403, "Only the owner or a read-write link can remove artifacts")
        if if_version != mf.version:
            _version_conflict(mf)
        art = get_artifact_or_404(db, mf, artifact_id)
        label = f"{TYPE_LABELS[art.artifact_type]} '{art.name}'"
        db.query(MutationLog).filter(MutationLog.artifact_id == art.id).delete()
        db.delete(art)
        db.flush()
        recompute_size(mf)
        mf.version += 1
        mf.updated_at = time.time()
        record_mutation(db, mf, None, agent, "remove_artifact", None,
                        if_version, f"removed {label}")
        db.commit()
        return {"metafile_version": mf.version, "removed": artifact_id}
    finally:
        db.close()


class RenameArtifactRequest(BaseModel):
    name: str


@app.patch("/metafiles/{metafile_id}/artifacts/{artifact_id}")
def rename_artifact(metafile_id: str, artifact_id: str, req: RenameArtifactRequest,
                    request: Request, token: Optional[str] = Query(None),
                    agent: str = Query("unknown"), if_version: int = Query(...)):
    db = SessionLocal()
    try:
        mf = get_metafile_or_404(db, metafile_id)
        role, _ = resolve_access(db, mf, request, token, Scope.WRITE)
        if role not in ("owner", "rw"):
            raise HTTPException(403, "Only the owner or a read-write link can rename artifacts")
        if if_version != mf.version:
            _version_conflict(mf)
        art = get_artifact_or_404(db, mf, artifact_id)
        art.name = (req.name or art.name).strip() or art.name
        art.updated_at = time.time()
        mf.version += 1
        mf.updated_at = time.time()
        record_mutation(db, mf, art.id, agent, "rename_artifact", None,
                        if_version, f"renamed artifact to '{art.name}'")
        db.commit()
        return {"metafile_version": mf.version, "artifact": artifact_view(art)}
    finally:
        db.close()


# --------------------------------------------------------------- fetch/query/mutate

@app.get("/m/{metafile_id}")
def query_metafile(
    metafile_id: str,
    request: Request,
    token: Optional[str] = Query(None),
    op: str = Query("fetch"),
    artifact: Optional[str] = Query(None),
    path: Optional[str] = Query(None),
    value: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(10),
    offset: int = Query(0),
    if_version: Optional[int] = Query(None),
    agent: Optional[str] = Query(None),
    type: Optional[str] = Query(None, alias="type"),
    name: Optional[str] = Query(None),
):
    return _handle_query(metafile_id, request, token, op, artifact, path, value,
                         q, limit, offset, if_version, agent, type, name)


@app.get("/m/{metafile_id}/{token}")
def query_metafile_pathauth(
    metafile_id: str,
    token: str,
    request: Request,
    op: str = Query("fetch"),
    artifact: Optional[str] = Query(None),
    path: Optional[str] = Query(None),
    value: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(10),
    offset: int = Query(0),
    if_version: Optional[int] = Query(None),
    agent: Optional[str] = Query(None),
    type: Optional[str] = Query(None, alias="type"),
    name: Optional[str] = Query(None),
):
    """Same interface with the token as a path segment -- the address
    itself carries identity+auth, query params carry the request."""
    return _handle_query(metafile_id, request, token, op, artifact, path, value,
                         q, limit, offset, if_version, agent, type, name)


WRITE_OPS = {"rename", "add_artifact", "remove_artifact", "rename_artifact",
             "set", "append", "delete"}


def _handle_query(metafile_id, request, token, op, artifact_id, path, value,
                  q, limit, offset, if_version, agent, atype, name):
    db = SessionLocal()
    try:
        mf = get_metafile_or_404(db, metafile_id)
        required = Scope.WRITE if op in WRITE_OPS else Scope.READ
        role, _ = resolve_access(db, mf, request, token, required)

        if op == "fetch":
            return metafile_view(mf, role)

        if op in WRITE_OPS and role not in ("owner", "rw"):
            raise HTTPException(403, "Only the owner or a read-write link can write")

        if op == "rename":
            _need_write_params(agent, if_version, "Renames")
            if if_version != mf.version:
                _version_conflict(mf)
            old_name = mf.name
            mf.name = (value or "Untitled metafile").strip() or "Untitled metafile"
            mf.version += 1
            mf.updated_at = time.time()
            record_mutation(db, mf, None, agent, "rename", None, if_version,
                            f"renamed '{old_name}' -> '{mf.name}'")
            db.commit()
            return metafile_view(mf, role)

        if op == "add_artifact":
            _need_write_params(agent, if_version, "Artifact adds")
            if not atype or atype not in ARTIFACT_TYPES:
                raise HTTPException(400, f"&type= must be one of {sorted(ARTIFACT_TYPES)}")
            if if_version != mf.version:
                _version_conflict(mf)
            label = TYPE_LABELS[atype]
            existing = sum(1 for a in mf.artifacts if a.artifact_type == atype)
            art = Artifact(
                metafile_id=mf.id,
                name=(name or f"{label} {existing + 1}").strip() or label,
                artifact_type=atype,
                content_json=json.dumps(DEFAULT_CONTENT[atype]),
                bytes_used=content_size(DEFAULT_CONTENT[atype]),
            )
            db.add(art)
            db.flush()
            recompute_size(mf)
            mf.version += 1
            mf.updated_at = time.time()
            record_mutation(db, mf, art.id, agent, "add_artifact", None,
                            if_version, f"added {label} '{art.name}'")
            db.commit()
            return metafile_view(mf, role)

        if op == "remove_artifact":
            _need_write_params(agent, if_version, "Artifact removals")
            art = get_artifact_or_404(db, mf, require_artifact_id(artifact_id))
            if if_version != mf.version:
                _version_conflict(mf)
            label = f"{TYPE_LABELS[art.artifact_type]} '{art.name}'"
            db.query(MutationLog).filter(MutationLog.artifact_id == art.id).delete()
            db.delete(art)
            db.flush()
            recompute_size(mf)
            mf.version += 1
            mf.updated_at = time.time()
            record_mutation(db, mf, None, agent, "remove_artifact", None,
                            if_version, f"removed {label}")
            db.commit()
            return metafile_view(mf, role)

        if op == "rename_artifact":
            _need_write_params(agent, if_version, "Artifact renames")
            art = get_artifact_or_404(db, mf, require_artifact_id(artifact_id))
            if if_version != mf.version:
                _version_conflict(mf)
            art.name = (value or art.name).strip() or art.name
            art.updated_at = time.time()
            mf.version += 1
            mf.updated_at = time.time()
            record_mutation(db, mf, art.id, agent, "rename_artifact", None,
                            if_version, f"renamed artifact to '{art.name}'")
            db.commit()
            return metafile_view(mf, role)

        if op == "get":
            art = get_artifact_or_404(db, mf, require_artifact_id(artifact_id))
            return _get_artifact_path(art, path)

        if op == "search":
            art = get_artifact_or_404(db, mf, require_artifact_id(artifact_id))
            if art.artifact_type != "facts":
                raise HTTPException(400, "search only applies to memory artifacts")
            content = json.loads(art.content_json)
            results, total = search_facts(content.get("facts", []), q or "", limit, offset)
            return {
                "query": q, "total": total, "limit": limit, "offset": offset,
                "results": [{"fact": f, "score": round(s, 4)} for f, s in results],
            }

        if op == "history":
            query = db.query(MutationLog).filter(MutationLog.metafile_id == metafile_id)
            if artifact_id:
                query = query.filter(MutationLog.artifact_id == artifact_id)
            rows = query.order_by(MutationLog.seq.desc()).offset(offset).limit(limit).all()
            return {
                "total_shown": len(rows),
                "history": [
                    {
                        "agent": r.agent, "op": r.op, "path": r.path,
                        "summary": r.summary, "old_version": r.old_version,
                        "new_version": r.new_version, "at": r.at,
                        "artifact_id": r.artifact_id,
                    } for r in rows
                ],
            }

        if op in ("set", "append", "delete"):
            _need_write_params(agent, if_version, "Writes")
            art = get_artifact_or_404(db, mf, require_artifact_id(artifact_id))
            return _mutate_artifact(db, mf, art, op, path, value, if_version, agent, role)

        raise HTTPException(400, f"Unknown op: {op}")
    finally:
        db.close()


def _need_write_params(agent, if_version, what: str):
    if agent is None:
        raise HTTPException(400, f"{what} must include agent=<name/signature> for provenance")
    if if_version is None:
        raise HTTPException(400, f"{what} must include if_version=<version you read> "
                                  "(optimistic concurrency -- prevents silent overwrites)")


def _get_artifact_path(art: Artifact, path: Optional[str]) -> dict:
    content = json.loads(art.content_json)
    atype = art.artifact_type
    if atype == "spreadsheet":
        if not path:
            raise HTTPException(400, "?path=<cell ref> required, e.g. path=B2")
        try:
            evaluated = evaluate_grid(content.get("cells", {}))
        except FormulaError as e:
            raise HTTPException(422, str(e))
        return {"path": path.upper(), "cell": content.get("cells", {}).get(path.upper()),
                "value": evaluated.get(path.upper())}
    if atype == "facts":
        if not path:
            raise HTTPException(400, "?path=<fact id> required")
        for f in content.get("facts", []):
            if f["id"] == path:
                return f
        raise HTTPException(404, "No fact with that id")
    if atype == "calendar":
        if not path:
            raise HTTPException(400, "?path=<event id> required")
        for e in content.get("events", []):
            if e["id"] == path:
                return e
        raise HTTPException(404, "No event with that id")
    if atype == "timer":
        if not path:
            raise HTTPException(400, "?path=<timer id> required")
        get_state, _ = HANDLERS["timer"]
        for t in get_state(content)["timers"]:
            if t["id"] == path:
                return t
        raise HTTPException(404, "No timer with that id")
    if atype == "media":
        if not path:
            raise HTTPException(400, "?path=<media item id> required (full payload, incl. data_base64)")
        item = media.get_item(content, path)
        if item is None:
            raise HTTPException(404, "No media item with that id")
        return item
    if atype in ("html", "canvas"):
        get_state, _ = HANDLERS[atype]
        return get_state(content)
    raise HTTPException(400, "Unsupported artifact type")


def _mutate_artifact(db, mf: Metafile, art: Artifact, op: str, path, value,
                     if_version: int, agent: str, role: str) -> dict:
    if if_version != art.version:
        _artifact_conflict(mf, art)

    content = json.loads(art.content_json)
    old_version = art.version

    try:
        if art.artifact_type == "spreadsheet":
            if op == "delete":
                content.get("cells", {}).pop((path or "").upper(), None)
                summary = f"cleared {path}"
            else:
                if not path:
                    raise HTTPException(400, "?path=<cell ref> required for spreadsheet writes")
                cells = content.setdefault("cells", {})
                cell_ref = path.upper()
                if value is not None and value.startswith("="):
                    cells[cell_ref] = {"formula": value}
                else:
                    cells[cell_ref] = {"value": value}
                summary = f"{cell_ref} = {value}"
            evaluate_grid(content.get("cells", {}))  # validate before committing
        else:
            _, apply_patch = HANDLERS[art.artifact_type]
            content = apply_patch(content, op, path, value)
            summary = f"{op} {path or ''}".strip()
    except FormulaError as e:
        raise HTTPException(422, f"Formula error: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    new_size = content_size(content)
    others = sum(a.bytes_used for a in mf.artifacts if a.id != art.id)
    enforce_total_limit(mf, others + new_size)  # raises 402; nothing persisted yet
    art.content_json = json.dumps(content)
    art.bytes_used = new_size
    art.version += 1
    art.updated_at = time.time()
    recompute_size(mf)
    mf.version += 1
    mf.updated_at = time.time()
    db.add(MutationLog(
        metafile_id=mf.id, artifact_id=art.id, agent=agent, op=op, path=path,
        old_version=old_version, new_version=art.version, summary=summary,
    ))
    db.commit()
    return metafile_view(mf, role)


# --------------------------------------------------------- bulk write (POST, for large payloads)

class BulkWrite(BaseModel):
    op: str
    artifact: Optional[str] = None
    path: Optional[str] = None
    value: Any = None
    if_version: int
    agent: str


@app.post("/m/{metafile_id}/bulk")
def bulk_mutate(metafile_id: str, body: BulkWrite, request: Request,
                token: Optional[str] = Query(None)):
    db = SessionLocal()
    try:
        mf = get_metafile_or_404(db, metafile_id)
        role, _ = resolve_access(db, mf, request, token, Scope.WRITE)
        if role not in ("owner", "rw"):
            raise HTTPException(403, "Only the owner or a read-write link can write")

        if body.op == "add_artifact":
            atype = (body.value or {}).get("type") if isinstance(body.value, dict) else None
            if not atype or atype not in ARTIFACT_TYPES:
                raise HTTPException(400, f"value.type must be one of {sorted(ARTIFACT_TYPES)}")
            if body.if_version != mf.version:
                _version_conflict(mf)
            label = TYPE_LABELS[atype]
            existing = sum(1 for a in mf.artifacts if a.artifact_type == atype)
            aname = ((body.value or {}).get("name") if isinstance(body.value, dict) else None)
            art = Artifact(
                metafile_id=mf.id,
                name=(aname or f"{label} {existing + 1}").strip() or label,
                artifact_type=atype,
                content_json=json.dumps(DEFAULT_CONTENT[atype]),
                bytes_used=content_size(DEFAULT_CONTENT[atype]),
            )
            db.add(art)
            db.flush()
            recompute_size(mf)
            mf.version += 1
            mf.updated_at = time.time()
            record_mutation(db, mf, art.id, body.agent, "add_artifact", None,
                            body.if_version, f"added {label} '{art.name}'")
            db.commit()
            return metafile_view(mf, role)

        if body.op == "remove_artifact":
            art = get_artifact_or_404(db, mf, require_artifact_id(body.artifact))
            if body.if_version != mf.version:
                _version_conflict(mf)
            db.query(MutationLog).filter(MutationLog.artifact_id == art.id).delete()
            db.delete(art)
            db.flush()
            recompute_size(mf)
            mf.version += 1
            mf.updated_at = time.time()
            record_mutation(db, mf, None, body.agent, "remove_artifact", None,
                            body.if_version, f"removed '{art.name}'")
            db.commit()
            return metafile_view(mf, role)

        if body.op == "rename_artifact":
            art = get_artifact_or_404(db, mf, require_artifact_id(body.artifact))
            if body.if_version != mf.version:
                _version_conflict(mf)
            aname = body.value.get("name", "") if isinstance(body.value, dict) else ""
            art.name = (aname or art.name).strip() or art.name
            art.updated_at = time.time()
            mf.version += 1
            mf.updated_at = time.time()
            record_mutation(db, mf, art.id, body.agent, "rename_artifact", None,
                            body.if_version, f"renamed artifact to '{art.name}'")
            db.commit()
            return metafile_view(mf, role)

        art = get_artifact_or_404(db, mf, require_artifact_id(body.artifact))
        return _mutate_artifact(db, mf, art, body.op, body.path, body.value,
                                body.if_version, body.agent, role)
    finally:
        db.close()


# ============================================================ sessions (playgrounds)

class CreateSessionRequest(BaseModel):
    name: str = "Untitled playground"
    agent: str = "unknown"


def playground_view(sess: Playground, role: str = None) -> dict:
    view = {
        "id": sess.id,
        "name": sess.name,
        "version": sess.version,
        "layout": json.loads(sess.layout_json),
        "created_at": sess.created_at,
        "updated_at": sess.updated_at,
    }
    if role:
        view["role"] = role
    return view


def get_session_or_404(db, session_id: str) -> Playground:
    sess = db.get(Playground, session_id)
    if not sess:
        raise HTTPException(404, "No playground session with that id")
    return sess


@app.get("/sessions")
def list_sessions():
    db = SessionLocal()
    try:
        rows = db.query(Playground).order_by(Playground.updated_at.desc()).all()
        return [
            {
                "id": s.id, "name": s.name, "version": s.version,
                "window_count": len(json.loads(s.layout_json)),
                "created_at": s.created_at, "updated_at": s.updated_at,
            }
            for s in rows
        ]
    finally:
        db.close()


@app.post("/sessions")
def create_session(req: CreateSessionRequest, request: Request):
    owner_raw, collab_raw = new_token(), new_token()
    sess = Playground(
        name=req.name, layout_json="[]",
        owner_token_hash=hash_token(owner_raw), collab_token_hash=hash_token(collab_raw),
    )
    db = SessionLocal()
    try:
        db.add(sess)
        db.commit()
        base = str(request.base_url).rstrip("/")
        return {
            "id": sess.id,
            "name": sess.name,
            "owner_token": owner_raw,
            "collaborator_token": collab_raw,
            "owner_url": f"{base}/session/{sess.id}/{owner_raw}",
            "collaborator_url": f"{base}/session/{sess.id}/{collab_raw}",
            "note": "owner_url can rearrange windows and approve/reject proposals. "
                    "collaborator_url (hand this to an AI) can read the playground and "
                    "propose new artifacts, but can't create or approve anything by itself. "
                    "Save both now.",
        }
    finally:
        db.close()


@app.get("/session/{session_id}/{token}")
def session_query(
    session_id: str,
    token: str,
    op: str = Query("fetch"),
    if_version: Optional[int] = Query(None),
    agent: Optional[str] = Query(None),
    value: Optional[str] = Query(None),
    # window placement fields
    window_id: Optional[str] = Query(None),
    metafile_id: Optional[str] = Query(None),
    m_token: Optional[str] = Query(None),
    artifact_id: Optional[str] = Query(None),
    x: Optional[float] = Query(None),
    y: Optional[float] = Query(None),
    w: Optional[float] = Query(None),
    h: Optional[float] = Query(None),
    z: Optional[int] = Query(None),
    # proposal fields
    name: Optional[str] = Query(None),
    artifact_type: Optional[str] = Query(None),
    reason: Optional[str] = Query(None),
    proposal_id: Optional[str] = Query(None),
    status: Optional[str] = Query("pending"),
):
    db = SessionLocal()
    try:
        sess = get_session_or_404(db, session_id)
        token_hash = hash_token(token)
        is_owner = token_hash == sess.owner_token_hash
        is_collab = token_hash == sess.collab_token_hash
        if not (is_owner or is_collab):
            raise HTTPException(403, "Invalid session token")

        WRITE_OPS = {"add_window", "place_all", "move_resize", "remove_window", "rename",
                     "approve_proposal", "reject_proposal"}
        if op in WRITE_OPS and not is_owner:
            raise HTTPException(403, "Only the session owner token can rearrange windows "
                                      "or approve/reject proposals -- the collaborator link is read + propose only")

        if op == "fetch":
            return playground_view(sess, role="owner" if is_owner else "collaborator")

        if op in ("add_window", "place_all", "move_resize", "remove_window", "rename"):
            if agent is None or if_version is None:
                raise HTTPException(400, "Layout writes need ?agent=...&if_version=...")
            if if_version != sess.version:
                raise HTTPException(409, {
                    "error": "version_conflict", "current_version": sess.version,
                    "current_state": playground_view(sess),
                })
            layout = json.loads(sess.layout_json)

            if op == "add_window":
                if not metafile_id or not m_token:
                    raise HTTPException(400, "add_window needs metafile_id and m_token "
                                              "(that metafile's own capability token)")
                win = {
                    "window_id": new_token()[:12],
                    "metafile_id": metafile_id,
                    "token": m_token,
                    "artifact_id": artifact_id,
                    "x": x or 40, "y": y or 40, "w": w or 420, "h": h or 320, "z": z or 1,
                }
                layout.append(win)
            elif op == "place_all":
                # "Throw everything in": place EVERY artifact of a metafile as
                # its own window, laid out on a grid, in one versioned step.
                if not metafile_id or not m_token:
                    raise HTTPException(400, "place_all needs metafile_id and m_token "
                                              "(that metafile's read-write token)")
                target = get_metafile_or_404(db, metafile_id)
                if hash_token(m_token) != target.rw_token_hash:
                    raise HTTPException(403, "m_token must be that metafile's read-write link token")
                arts = target.artifacts
                if not arts:
                    raise HTTPException(400, "That metafile has no artifacts to place")
                COLS, W, H, GAP, X0, Y0 = 3, 440, 340, 40, 40, 40
                base_z = len(layout) + 1
                for i, a in enumerate(arts):
                    row, col = divmod(i, COLS)
                    layout.append({
                        "window_id": new_token()[:12],
                        "metafile_id": metafile_id,
                        "token": m_token,
                        "artifact_id": a.id,
                        "x": X0 + col * (W + GAP), "y": Y0 + row * (H + GAP),
                        "w": W, "h": H, "z": base_z + i,
                    })
            elif op == "move_resize":
                for win in layout:
                    if win["window_id"] == window_id:
                        for k, v in (("x", x), ("y", y), ("w", w), ("h", h), ("z", z)):
                            if v is not None:
                                win[k] = v
                        break
                else:
                    raise HTTPException(404, "No window with that id in this session")
            elif op == "remove_window":
                layout = [win for win in layout if win["window_id"] != window_id]
            elif op == "rename":
                sess.name = (value or "Untitled playground").strip() or "Untitled playground"

            sess.layout_json = json.dumps(layout)
            sess.version += 1
            sess.updated_at = time.time()
            db.commit()
            return playground_view(sess)

        if op == "list_proposals":
            rows = (
                db.query(Proposal)
                .filter(Proposal.session_id == session_id, Proposal.status == status)
                .order_by(Proposal.created_at.desc()).all()
            )
            return {"proposals": [
                {"id": p.id, "agent": p.agent, "name": p.name, "artifact_type": p.artifact_type,
                 "reason": p.reason, "status": p.status, "created_at": p.created_at,
                 "created_metafile_id": p.created_metafile_id}
                for p in rows
            ]}

        if op == "approve_proposal" or op == "reject_proposal":
            if not proposal_id:
                raise HTTPException(400, "?proposal_id=... required")
            prop = db.get(Proposal, proposal_id)
            if not prop or prop.session_id != session_id:
                raise HTTPException(404, "No such proposal in this session")
            if prop.status != "pending":
                raise HTTPException(409, f"Proposal already {prop.status}")

            if op == "reject_proposal":
                prop.status = "rejected"
                prop.decided_at = time.time()
                db.commit()
                return {"id": prop.id, "status": "rejected"}

            # approve: create the container AND its first artifact now
            if prop.artifact_type not in ARTIFACT_TYPES:
                raise HTTPException(400, f"artifact_type must be one of {sorted(ARTIFACT_TYPES)}")
            rw_raw, ro_raw = new_token(), new_token()
            mf = Metafile(
                name=prop.name, owner_id=None,
                rw_token_hash=hash_token(rw_raw), ro_token_hash=hash_token(ro_raw),
            )
            db.add(mf)
            db.flush()
            art = Artifact(
                metafile_id=mf.id, name=TYPE_LABELS[prop.artifact_type],
                artifact_type=prop.artifact_type,
                content_json=json.dumps(DEFAULT_CONTENT[prop.artifact_type]),
                bytes_used=content_size(DEFAULT_CONTENT[prop.artifact_type]),
            )
            db.add(art)
            db.flush()
            recompute_size(mf)
            db.add(MutationLog(metafile_id=mf.id, artifact_id=art.id, agent=prop.agent,
                               op="create", path=None, old_version=0, new_version=1,
                               summary=f"created via approved proposal ({prop.artifact_type})"))

            layout = json.loads(sess.layout_json)
            layout.append({
                "window_id": new_token()[:12], "metafile_id": mf.id, "token": rw_raw,
                "artifact_id": art.id,
                "x": x or 40, "y": y or 40, "w": w or 420, "h": h or 320, "z": (z or len(layout) + 1),
            })
            sess.layout_json = json.dumps(layout)
            sess.version += 1
            sess.updated_at = time.time()

            prop.status = "approved"
            prop.created_metafile_id = mf.id
            prop.decided_at = time.time()
            db.commit()
            return {"id": prop.id, "status": "approved", "metafile_id": mf.id,
                    "artifact_id": art.id, "rw_token": rw_raw}
        raise HTTPException(400, f"Unknown op: {op}")
    finally:
        db.close()


@app.post("/session/{session_id}/{token}/propose")
def propose_artifact(
    session_id: str, token: str,
    name: str = Query(...), artifact_type: str = Query(...),
    agent: str = Query(...), reason: Optional[str] = Query(None),
):
    """Any holder of a session link (read *or* write) can propose a new
    artifact -- but proposing never creates anything by itself. Only
    the session owner's approve_proposal op does that. This is the
    permission gate for agent-initiated creation."""
    if artifact_type not in ARTIFACT_TYPES:
        raise HTTPException(400, f"artifact_type must be one of {sorted(ARTIFACT_TYPES)}")
    db = SessionLocal()
    try:
        sess = get_session_or_404(db, session_id)
        token_hash = hash_token(token)
        if token_hash not in (sess.owner_token_hash, sess.collab_token_hash):
            raise HTTPException(403, "Invalid session token")
        prop = Proposal(session_id=session_id, agent=agent, name=name,
                         artifact_type=artifact_type, reason=reason)
        db.add(prop)
        db.commit()
        return {"proposal_id": prop.id, "status": "pending",
                "note": "Waiting for the session owner to approve or reject this before "
                        f"the '{artifact_type}' artifact is actually created."}
    finally:
        db.close()


# ------------------------------------------------------------- live sync (SSE)

import asyncio
from queue import Empty as QueueEmpty


def _sse_response(q, key, request, close_kinds=("deleted",)):
    async def gen():
        try:
            yield "retry: 2500\n\n"
            last_beat = time.time()
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = q.get_nowait()
                except QueueEmpty:
                    if time.time() - last_beat > 12:
                        yield ": keep-alive\n\n"
                        last_beat = time.time()
                    await asyncio.sleep(0.35)
                    continue
                yield f"event: {ev.get('kind', 'change')}\ndata: {json.dumps(ev)}\n\n"
                if ev.get("kind") in close_kinds:
                    return
        finally:
            events.bus.unsubscribe(key, q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@app.get("/events/m/{metafile_id}")
async def metafile_events(metafile_id: str, request: Request,
                          token: Optional[str] = Query(None)):
    """Live change stream for one metafile. Auth: capability token or
    Bearer. Emits `changed` / `deleted` events; re-fetch on each."""
    db = SessionLocal()
    try:
        mf = get_metafile_or_404(db, metafile_id)
        resolve_access(db, mf, request, token, Scope.READ)
    finally:
        db.close()
    key = ("mf", metafile_id)
    return _sse_response(events.bus.subscribe(key), key, request)


@app.get("/events/session/{session_id}/{token}")
async def session_events(session_id: str, token: str, request: Request):
    """Live change stream for a playground session (layout + proposals)."""
    db = SessionLocal()
    try:
        sess = get_session_or_404(db, session_id)
        if hash_token(token) not in (sess.owner_token_hash, sess.collab_token_hash):
            raise HTTPException(403, "Invalid session token")
    finally:
        db.close()
    key = ("sess", session_id)
    return _sse_response(events.bus.subscribe(key), key, request)


# ------------------------------------------------ agent entry point + frontend

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _ai_doc() -> str:
    return (FRONTEND_DIR / "llms.txt").read_text(encoding="utf-8")


@app.get("/", include_in_schema=False)
def root_entry(request: Request):
    """Browsers get the app; everything else (curl, agents, no Accept or
    Accept: */*) gets the machine-readable agent guide. This makes the AI
    doc literally the first thing an agent reads when it hits the URL."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
    return PlainTextResponse(_ai_doc(), media_type="text/plain; charset=utf-8")


@app.get("/ai", include_in_schema=False)
def ai_entry():
    return PlainTextResponse(_ai_doc(), media_type="text/plain; charset=utf-8")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
