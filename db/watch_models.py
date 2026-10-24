"""M0 Watch (competitor intelligence) tables. Created at start-up with the others by db.database.init_db.

Collection, extraction and change detection are done without AI. Only signals, scores, briefs and opportunities
come from the n8n "Odynza Radar Signals" workflow.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from db.database import Base

TIERS = ('direct', 'adjacent', 'aspirational', 'emerging')
COMPETITOR_STATUS = ('proposed', 'confirmed', 'rejected', 'queued')
SOURCE_KINDS = ('page', 'instagram', 'facebook', 'linkedin', 'ads', 'web')
PAGE_KINDS = ('homepage', 'pricing', 'services', 'clients', 'about', 'careers', 'news')


class WatchClient(Base):
    """A client profile (F01). Several clients can be watched; each request works on the one picked in the UI."""
    __tablename__ = 'watch_clients'
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    website = Column(String(500), nullable=False, default='')
    sector = Column(String(120), nullable=False, default='Software / AI')
    market = Column(String(120), nullable=False, default='Egypt')
    offer = Column(Text, nullable=False, default='')            # what they sell
    audience = Column(Text, nullable=False, default='')         # to whom
    positioning = Column(Text, nullable=False, default='')
    price_position = Column(String(20), nullable=False, default='mid')   # budget | mid | premium
    channels = Column(JSON, nullable=False, default=list)
    claims = Column(JSON, nullable=False, default=list)         # the claims the client makes
    socials = Column(JSON, nullable=False, default=dict)        # instagram, facebook, linkedin URLs
    brief_emails = Column(JSON, nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)        # bumped on every profile change (rescore hint)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchAccess(Base):
    """Which client a "client" login may see. A client login with no row sees the first client (stage 1)."""
    __tablename__ = 'watch_access'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('watch_clients.id', ondelete='CASCADE'), index=True, nullable=False)
    username = Column(String(80), index=True, nullable=False)


class WatchCompetitor(Base):
    """The register (F02, F03). Nothing is collected until status is confirmed."""
    __tablename__ = 'watch_competitors'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('watch_clients.id', ondelete='CASCADE'), index=True, nullable=False)
    name = Column(String(200), nullable=False)
    website = Column(String(500), nullable=False, default='')
    socials = Column(JSON, nullable=False, default=dict)
    tier = Column(String(20), nullable=False, default='direct')
    status = Column(String(20), nullable=False, default='proposed', index=True)
    origin = Column(String(20), nullable=False, default='proposal')   # proposal | manual | new_entrant
    why = Column(Text, nullable=False, default='')
    decided_by = Column(String(64), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    review_at = Column(DateTime, nullable=True)                       # 90-day register review
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchSource(Base):
    """One thing that is watched: a page, a social account or the ad library. competitor_id NULL = the client."""
    __tablename__ = 'watch_sources'
    __table_args__ = (UniqueConstraint('client_id', 'competitor_id', 'kind', 'url'),)
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('watch_clients.id', ondelete='CASCADE'), index=True, nullable=False)
    competitor_id = Column(Integer, ForeignKey('watch_competitors.id', ondelete='CASCADE'), index=True, nullable=True)
    kind = Column(String(20), nullable=False)          # page | instagram | facebook | linkedin | ads | web
    page_kind = Column(String(20), nullable=True)      # for pages: homepage, pricing, ...
    url = Column(String(1000), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    fail_count = Column(Integer, nullable=False, default=0)
    next_run_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchSnapshot(Base):
    """One capture of one source. A capture identical to the previous one is not stored again."""
    __tablename__ = 'watch_snapshots'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('watch_sources.id', ondelete='CASCADE'), index=True, nullable=False)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    content_hash = Column(String(64), nullable=False)
    text = Column(Text, nullable=False, default='')
    fields = Column(JSON, nullable=False, default=dict)    # extracted without AI: prices, plans, lists, headings
    metrics = Column(JSON, nullable=False, default=dict)   # followers, posts per week, engagement rate ...
    items = Column(JSON, nullable=False, default=list)     # posts or ads, as collected


class WatchVisit(Base):
    """One run of collection over some sources. Its new changes are sent to n8n by visit id."""
    __tablename__ = 'watch_visits'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('watch_clients.id', ondelete='CASCADE'), index=True, nullable=False)
    trigger = Column(String(20), nullable=False, default='schedule')    # schedule | run_now | rescore
    status = Column(String(20), nullable=False, default='collecting')   # collecting | scoring | done | failed
    source_ids = Column(JSON, nullable=False, default=list)
    report = Column(JSON, nullable=False, default=dict)                 # per source: items, changes, error, cost
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchChange(Base):
    """A difference between two snapshots, found by rules (no AI)."""
    __tablename__ = 'watch_changes'
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, ForeignKey('watch_visits.id', ondelete='CASCADE'), index=True, nullable=False)
    source_id = Column(Integer, ForeignKey('watch_sources.id', ondelete='CASCADE'), index=True, nullable=False)
    competitor_id = Column(Integer, nullable=True, index=True)
    field = Column(String(200), nullable=False)
    kind = Column(String(20), nullable=False)          # added | removed | changed
    before = Column(Text, nullable=True)
    after = Column(Text, nullable=True)
    before_snapshot_id = Column(Integer, nullable=True)
    after_snapshot_id = Column(Integer, nullable=False)
    fingerprint = Column(String(64), nullable=False, index=True)   # dedupe: same change on two pages or twice
    status = Column(String(20), nullable=False, default='new')     # new | signalled | duplicate
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchSignal(Base):
    """A classified change. Always carries what it means for the client (consequence, not summary)."""
    __tablename__ = 'watch_signals'
    id = Column(Integer, primary_key=True)
    change_id = Column(Integer, ForeignKey('watch_changes.id', ondelete='CASCADE'), unique=True, nullable=False)
    client_id = Column(Integer, index=True, nullable=False)
    competitor_id = Column(Integer, nullable=True, index=True)
    type = Column(String(30), nullable=False)          # pricing, offer, client, hiring, claim, ad, social, ...
    theme = Column(String(120), nullable=False, default='')
    title = Column(String(300), nullable=False)
    meaning = Column(Text, nullable=False)
    claims = Column(JSON, nullable=False, default=list)
    source_url = Column(String(1000), nullable=False, default='')
    captured_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WatchScore(Base):
    """Impact 1-5 per signal. Kept apart from signals so rescoring never collects again (F20)."""
    __tablename__ = 'watch_scores'
    signal_id = Column(Integer, ForeignKey('watch_signals.id', ondelete='CASCADE'), primary_key=True)
    score = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False, default='')
    corrected_score = Column(Integer, nullable=True)
    corrected_reason = Column(Text, nullable=True)
    corrected_by = Column(String(64), nullable=True)
    corrected_at = Column(DateTime, nullable=True)
    model = Column(String(100), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchClaim(Base):
    """The claim map (F18): one label and who makes it, with evidence."""
    __tablename__ = 'watch_claims'
    __table_args__ = (UniqueConstraint('client_id', 'label'),)
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, index=True, nullable=False)
    label = Column(String(120), nullable=False)
    synonyms = Column(JSON, nullable=False, default=list)
    holders = Column(JSON, nullable=False, default=dict)   # "client" or competitor id -> {quote, source_url, at}
    edited_by = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchBrief(Base):
    """The weekly competitor brief: 3-7 items, or a quiet week. Never padded."""
    __tablename__ = 'watch_briefs'
    __table_args__ = (UniqueConstraint('client_id', 'week_start'),)
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, index=True, nullable=False)
    week_start = Column(String(10), nullable=False)     # Monday, YYYY-MM-DD (Cairo)
    status = Column(String(20), nullable=False, default='running')   # running | ready | failed
    headline = Column(String(300), nullable=False, default='')
    items = Column(JSON, nullable=False, default=list)
    quiet = Column(Boolean, nullable=False, default=False)
    error = Column(Text, nullable=True)
    emailed_at = Column(DateTime, nullable=True)
    email_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchOpportunity(Base):
    """A ranked marketing opportunity with the 10 required fields, handed to M1 Strategy by Act."""
    __tablename__ = 'watch_opportunities'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, index=True, nullable=False)
    week_start = Column(String(10), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    angle = Column(Text, nullable=False)
    trigger = Column(Text, nullable=False)
    claim = Column(String(200), nullable=False)
    audience = Column(Text, nullable=False)
    why_now = Column(Text, nullable=False)
    competitors_saying = Column(Text, nullable=False)
    wrong_if = Column(Text, nullable=False)
    confidence = Column(String(10), nullable=False)     # high | medium | low
    expires_on = Column(String(10), nullable=False)     # YYYY-MM-DD
    evidence = Column(JSON, nullable=False, default=list)   # signal ids
    status = Column(String(20), nullable=False, default='new')   # new | accepted | rejected | acted | expired
    decided_by = Column(String(64), nullable=True)
    plan_id = Column(String(36), nullable=True)
    outcome = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchAlert(Base):
    """Movement alerts (F19), fired by rules: goes quiet, starts discounting, repositions, broadens."""
    __tablename__ = 'watch_alerts'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, index=True, nullable=False)
    competitor_id = Column(Integer, index=True, nullable=True)
    rule = Column(String(30), nullable=False)
    message = Column(Text, nullable=False)
    key = Column(String(120), nullable=False, unique=True)   # one alert per rule, competitor and week
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchState(Base):
    """Small key/value store for the scheduler (last weekly run, Apify spend per month)."""
    __tablename__ = 'watch_state'
    key = Column(String(80), primary_key=True)
    value = Column(JSON, nullable=True)
    num = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
