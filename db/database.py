"""SQLAlchemy engine, session factory and the shared tables (plans, content, search cache, accounts).
The competitor-watch tables are in db/watch_models.py."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    Boolean,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/marketing.db")
if DATABASE_URL.startswith("sqlite:///") and not DATABASE_URL.startswith("sqlite:///:memory:"):
    Path(DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

# connect_args only needed for SQLite (allows use across threads in FastAPI)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass









class StrategyPlan(Base):
    """M1 strategy plan written by the n8n strategy agents."""
    __tablename__ = "strategy_plans"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String(36), nullable=False, default="")      # unused, kept for older databases
    company_id = Column(String(300), nullable=False)
    company_name = Column(String(300), nullable=False)
    status = Column(String(20), default="queued", index=True)   # queued | running | completed | failed
    inputs = Column(JSON, nullable=False, default=dict)
    plan = Column(JSON, nullable=True)
    validation_errors = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StrategyResult(Base):
    """Ad numbers for one week, platform and campaign of a Radar strategy plan, typed by hand from the ad managers."""
    __tablename__ = "strategy_results"
    id = Column(Integer, primary_key=True)
    plan_id = Column(String(36), ForeignKey("strategy_plans.id", ondelete="CASCADE"), index=True, nullable=False)
    week_start = Column(String(10), nullable=False)                # Monday, YYYY-MM-DD
    platform = Column(String(20), nullable=False)                  # Meta ads | LinkedIn ads | Instagram | Facebook | LinkedIn
    campaign_id = Column(String(12), nullable=False, default="")
    spend = Column(Integer, nullable=False, default=0)             # whole currency units
    impressions = Column(Integer, nullable=False, default=0)
    clicks = Column(Integer, nullable=False, default=0)
    leads = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=False, default="")
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContentRun(Base):
    """M2: one batch of social media drafts made by the n8n platform agents from an M1 plan."""
    __tablename__ = "content_runs"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    plan_id = Column(String(36), ForeignKey("strategy_plans.id"), index=True, nullable=False)
    session_id = Column(String(36), nullable=False, default="")      # unused, kept for older databases
    company_name = Column(String(300), nullable=False)
    status = Column(String(20), default="queued", index=True)   # queued | running | completed | failed
    inputs = Column(JSON, nullable=False, default=dict)          # dates, platforms, cadence, brand look, slots
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContentItem(Base):
    """One draft post for one platform and date. Images and reels are files under data/content/<run>/."""
    __tablename__ = "content_items"
    id = Column(Integer, primary_key=True)
    run_id = Column(String(36), ForeignKey("content_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    slot_id = Column(String(40), nullable=False)
    platform = Column(String(20), nullable=False)                  # LinkedIn | Instagram | Facebook
    post_date = Column(String(10), nullable=False)                 # YYYY-MM-DD
    format = Column(String(20), nullable=False)                    # post | carousel | document | reel
    campaign_id = Column(String(40), nullable=True)
    status = Column(String(20), default="draft", index=True)       # draft | approved | rejected | posted
    content = Column(JSON, nullable=False, default=dict)           # text, hashtags, prompts, slides, checks
    image_status = Column(String(20), default="none")              # none | pending | ready | failed | uploaded
    image_error = Column(Text, nullable=True)
    video_status = Column(String(20), default="none")              # none | waiting | uploaded
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DiscoveryCache(Base):
    """Company search cache: profiles, homepage reads and finished searches survive a restart."""
    __tablename__ = "discovery_cache"
    key = Column(String(64), primary_key=True)
    kind = Column(String(20), index=True, nullable=False)   # profile | page | result
    value = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class User(Base):
    """A person who can sign in. Passwords are stored only as scrypt hashes."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)   # stored lowercase
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="member")             # admin | member | viewer | client
    disabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)


class AuthSession(Base):
    """A signed-in browser. Only a SHA-256 of the cookie value is stored, so a copied database cannot sign anyone in."""
    __tablename__ = "auth_sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    csrf = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)


def get_db():
    """FastAPI dependency: yields a DB session and closes it after the request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called once at app startup."""
    import db.watch_models  # noqa: F401  (registers the M0 Watch tables)
    Base.metadata.create_all(bind=engine)
