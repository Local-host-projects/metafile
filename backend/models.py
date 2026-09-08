"""
SQLAlchemy models for Metafile.

Structure:
  User 1---* Metafile 1---* Artifact
  A metafile is a container owned by a user; it holds any number of
  artifacts (facts / spreadsheet / html / canvas / calendar / timer /
  media). Access is owner-auth (login) OR the classic capability token
  embedded in a share URL. Every mutation is appended to MutationLog
  with an agent fingerprint, and writes are rejected if the version
  has moved (optimistic concurrency).
"""
import os
import shutil
import uuid
import time
import hashlib
import secrets
from pathlib import Path
from sqlalchemy import (
    Column, String, Integer, Float, Text, ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()

FREE_TIER_BYTES = 5 * 1_048_576  # 5 MiB free per metafile, then upgrade to paid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def new_token() -> str:
    # 32 bytes of randomness, url-safe. This token IS the credential --
    # never logged or stored in plaintext (see hash_token).
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: new_id("usr"))
    name = Column(String, nullable=False, default="Untitled")
    email = Column(String, nullable=False, unique=True)
    pw_hash = Column(String, nullable=False)  # salt$pbkdf2_hex
    created_at = Column(Float, default=time.time)


class Metafile(Base):
    __tablename__ = "metafiles"

    id = Column(String, primary_key=True, default=lambda: new_id("mf"))
    name = Column(String, nullable=False, default="Untitled metafile")
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)  # NULL = legacy, unclaimed

    version = Column(Integer, nullable=False, default=1)
    bytes_used = Column(Integer, nullable=False, default=0)

    tier = Column(String, nullable=False, default="free")  # free|paid
    byte_limit = Column(Integer, nullable=False, default=FREE_TIER_BYTES)

    rw_token_hash = Column(String, nullable=False)
    ro_token_hash = Column(String, nullable=False)

    created_at = Column(Float, default=time.time)
    updated_at = Column(Float, default=time.time)

    artifacts = relationship(
        "Artifact", back_populates="metafile",
        cascade="all, delete-orphan", order_by="Artifact.created_at",
    )
    mutations = relationship(
        "MutationLog", back_populates="metafile",
        cascade="all, delete-orphan", order_by="MutationLog.seq"
    )


class Artifact(Base):
    """One typed block inside a metafile container."""
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=lambda: new_id("art"))
    metafile_id = Column(String, ForeignKey("metafiles.id"), nullable=False)

    name = Column(String, nullable=False, default="Untitled")
    artifact_type = Column(String, nullable=False)  # facts|spreadsheet|html|canvas|calendar|timer|media
    content_json = Column(Text, nullable=False, default="{}")
    bytes_used = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)

    created_at = Column(Float, default=time.time)
    updated_at = Column(Float, default=time.time)

    metafile = relationship("Metafile", back_populates="artifacts")


class MutationLog(Base):
    __tablename__ = "mutation_log"

    seq = Column(Integer, primary_key=True, autoincrement=True)
    metafile_id = Column(String, ForeignKey("metafiles.id"), nullable=False)
    artifact_id = Column(String, nullable=True)  # NULL = container-level op

    agent = Column(String, nullable=False)  # fingerprint / signature, required on every write
    op = Column(String, nullable=False)     # set | append | bulk_set | delete | ...
    path = Column(String, nullable=True)    # e.g. cell "B3", fact id, or null for whole-doc
    summary = Column(String, nullable=True)  # short human-readable diff description

    old_version = Column(Integer, nullable=False)
    new_version = Column(Integer, nullable=False)
    at = Column(Float, default=time.time)

    metafile = relationship("Metafile", back_populates="mutations")


class Session(Base):
    """A 'playground' -- a saved arrangement of multiple metafile windows,
    addressable as /session/{id}/{token}. The session's own token is a
    separate capability credential from any individual metafile's token;
    it grants control over the *layout* (which windows, where, what size)
    plus the right to approve/reject AI-proposed new artifacts."""
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: new_id("sess"))
    name = Column(String, nullable=False, default="Untitled playground")
    layout_json = Column(Text, nullable=False, default="[]")  # list of window dicts
    version = Column(Integer, nullable=False, default=1)
    owner_token_hash = Column(String, nullable=False)
    collab_token_hash = Column(String, nullable=False)  # can propose artifacts + read; cannot approve or rearrange
    created_at = Column(Float, default=time.time)
    updated_at = Column(Float, default=time.time)


class Proposal(Base):
    """An AI-initiated request to create a new artifact inside a session.
    Nothing is created until a human holding the session's owner token
    approves it -- this is the permission gate for agent-initiated
    creation."""
    __tablename__ = "proposals"

    id = Column(String, primary_key=True, default=lambda: new_id("prop"))
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    agent = Column(String, nullable=False)
    name = Column(String, nullable=False)
    artifact_type = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending|approved|rejected
    created_metafile_id = Column(String, nullable=True)
    created_at = Column(Float, default=time.time)
    decided_at = Column(Float, nullable=True)


class Payment(Base):
    """A Paystack upgrade payment for one metafile."""
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=lambda: new_id("pay"))
    reference = Column(String, nullable=False, unique=True)
    metafile_id = Column(String, ForeignKey("metafiles.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    amount_kobo = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending|success|failed
    created_at = Column(Float, default=time.time)
    decided_at = Column(Float, nullable=True)


def make_engine(db_path: str = None):
    """DATABASE_URL env var wins (e.g. sqlite:////data/metafile.db with a
    mounted volume on Railway); default is ./metafile.db next to the app."""
    if db_path is None:
        db_path = os.environ.get("DATABASE_URL", "sqlite:///./metafile.db")
    engine = create_engine(db_path, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(engine):
    """Create new tables, add new columns to old ones, and backfill one
    Artifact row per pre-existing metafile. Backs the sqlite file up first.
    Safe to run on every boot (idempotent)."""
    db_file = None
    try:
        db_name = engine.url.database or ""
        if db_name and db_name != ":memory:":
            db_file = Path(db_name)
    except Exception:
        db_file = None

    if db_file is not None and db_file.exists():
        bak = db_file.with_suffix(".db.bak")
        if not bak.exists():
            try:
                shutil.copyfile(db_file, bak)
            except OSError:
                pass

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        mf_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(metafiles)").all()]
        if "owner_id" not in mf_cols:
            conn.exec_driver_sql("ALTER TABLE metafiles ADD COLUMN owner_id VARCHAR(64)")

        log_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(mutation_log)").all()]
        if "artifact_id" not in log_cols:
            conn.exec_driver_sql("ALTER TABLE mutation_log ADD COLUMN artifact_id VARCHAR(64)")

        import sqlite3 as _sqlite3
        n_artifacts = conn.exec_driver_sql("SELECT COUNT(*) FROM artifacts").scalar() or 0
        if n_artifacts == 0:
            rows = conn.exec_driver_sql(
                "SELECT id, artifact_type, content_json, bytes_used, version FROM metafiles"
            ).all()
            for mf_id, atype, content_json, bytes_used, version in rows:
                conn.exec_driver_sql(
                    "INSERT INTO artifacts (id, metafile_id, name, artifact_type, "
                    "content_json, bytes_used, version, created_at, updated_at) "
                    "VALUES (:id, :mf, :name, :type, :content, :bytes, :ver, :now, :now)",
                    {
                        "id": new_id("art"), "mf": mf_id,
                        "name": {"facts": "Memory", "spreadsheet": "Spreadsheet",
                                 "html": "Page", "canvas": "Canvas",
                                 "calendar": "Calendar", "timer": "Timer",
                                 "media": "Media"}.get(atype, "Block"),
                        "type": atype, "content": content_json or "{}",
                        "bytes": bytes_used or 0, "ver": version or 1,
                        "now": time.time(),
                    },
                )

        # Legacy columns from the single-artifact era are unusable now: the
        # new model never sets them, but the old table declares them NOT
        # NULL, so every insert would fail. Content is already backfilled
        # into artifacts above, so drop them (SQLite >= 3.35).
        if _sqlite3.sqlite_version_info >= (3, 35, 0):
            mf_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(metafiles)").all()]
            for legacy in ("artifact_type", "content_json"):
                if legacy in mf_cols:
                    conn.exec_driver_sql(f"ALTER TABLE metafiles DROP COLUMN {legacy}")

