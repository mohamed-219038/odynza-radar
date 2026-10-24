"""M0 Watch: client profile and register, watched sources, visits, signals and scores, compare, weekly brief,
opportunities (Act opens a strategy plan) and the n8n "Odynza Radar Signals" callbacks.

Roles: admin and member do everything; a client login confirms competitors, corrects scores and accepts or rejects
opportunities; a viewer only reads. Act is admin and member only.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.routers.strategy import callback_allowed
from api.security import AuthUser, env_int, limiter, rate_limit, require_user, too_many
from api.watch import engine, scheduler
from api.watch.brief import brief_html, brief_pdf, email_ready
from api.watch.scoring import SCALE, adjust
from api.watch.insight import (STARTER_CLAIMS, claim_map, companies, content_gaps, effective_score, latest,
                               run_alerts, scorecard, week_snapshot)
from db.database import StrategyPlan, get_db
from db.watch_models import (PAGE_KINDS, TIERS, WatchAccess, WatchAlert, WatchBrief, WatchChange, WatchClaim, WatchClient,
                             WatchCompetitor, WatchOpportunity, WatchScore, WatchSignal, WatchSnapshot, WatchSource,
                             WatchState, WatchVisit)

n8n = APIRouter()
Tier = Literal['direct', 'adjacent', 'aspirational', 'emerging']
_tasks: set[asyncio.Task] = set()


def background(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ---- Roles and the client being worked on ----------------------------------------------------

def allowed_clients(db: Session, user: AuthUser) -> list[int]:
    """Client ids this login may open: all for staff and viewers; the linked ones for a client login."""
    ids = [c.id for c in db.query(WatchClient.id).order_by(WatchClient.id)]
    if user.role != 'client':
        return ids
    linked = {a.client_id for a in db.query(WatchAccess).filter_by(username=user.username)}
    if linked:
        return [i for i in ids if i in linked]
    return ids[:1]   # not linked yet: the first client, as before


async def pick_client(request: Request, user: AuthUser = Depends(require_user), db: Session = Depends(get_db)):
    """The UI sends the picked client in X-Watch-Client; anything not allowed falls back to the first allowed one."""
    ids = allowed_clients(db, user)
    raw = request.headers.get('x-watch-client', '') or request.query_params.get('client', '')   # links opened in a new tab
    wanted = int(raw) if raw.isdigit() else None
    db.info['watch_client'] = wanted if wanted in ids else (ids[0] if ids else None)
    db.info['watch_allowed'] = ids


router = APIRouter(dependencies=[Depends(pick_client)])


def reader(user: AuthUser = Depends(require_user)) -> AuthUser:
    return user


def watcher(user: AuthUser = Depends(require_user)) -> AuthUser:
    """Admin, member or client: may confirm competitors, correct scores and decide opportunities."""
    if user.role not in ('admin', 'member', 'client'):
        raise HTTPException(403, 'Your account can view results only.')
    return user


def staff(user: AuthUser = Depends(require_user)) -> AuthUser:
    if user.role not in ('admin', 'member'):
        raise HTTPException(403, 'Only an admin or member can do this.')
    return user


def limited(name, limit, window):
    def dependency(user: AuthUser = Depends(staff)) -> AuthUser:
        wait = limiter.check(f'watch-{name}:{user.id}', limit, window)
        if wait:
            too_many(wait)
        return user
    return dependency


def the_client(db: Session) -> WatchClient:
    cid = db.info.get('watch_client')
    client = db.get(WatchClient, cid) if cid else None
    if client is None:
        raise HTTPException(409, 'Set up the client profile first.')
    return client


def get_or_404(db, model, key, what):
    row = db.get(model, key)
    owner = getattr(row, 'client_id', None)
    if row is not None and owner is None and getattr(row, 'source_id', None):
        source = db.get(WatchSource, row.source_id)
        owner = source.client_id if source else None
    # Rows of another client are hidden, so a client login cannot open them by id.
    if row is None or ('watch_client' in db.info and owner is not None and int(owner) != db.info['watch_client']):
        raise HTTPException(404, f'{what} not found.')
    return row


# ---- Bodies --------------------------------------------------------------------------------

def public_url(value: str, required=False) -> str:
    value = (value or '').strip()
    if not value:
        if required:
            raise ValueError('A website is required.')
        return ''
    if not re.match(r'^https?://', value, re.I):
        value = 'https://' + value
    if not re.match(r'^https?://[^\s/$.?#][^\s]*\.[^\s]{2,}$', value, re.I) or len(value) > 500:
        raise ValueError('Enter a full web address such as https://example.com.')
    return value.rstrip('/')


class Socials(BaseModel):
    instagram: str = ''
    facebook: str = ''
    linkedin: str = ''

    @field_validator('instagram', 'facebook', 'linkedin')
    @classmethod
    def check(cls, value, info):
        value = public_url(value)
        if value and info.field_name not in value.lower():
            raise ValueError(f'This is not a {info.field_name} link.')
        return value


class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website: str = Field(max_length=500)
    sector: str = Field(default='Software / AI', max_length=120)
    market: str = Field(default='Egypt', max_length=120)
    offer: str = Field(default='', max_length=2000)
    audience: str = Field(default='', max_length=2000)
    positioning: str = Field(default='', max_length=2000)
    price_position: Literal['budget', 'mid', 'premium'] = 'mid'
    channels: list[str] = Field(default_factory=list, max_length=12)
    claims: list[str] = Field(default_factory=list, max_length=20)
    socials: Socials = Field(default_factory=Socials)
    brief_emails: list[str] = Field(default_factory=list, max_length=10)

    @field_validator('website')
    @classmethod
    def site(cls, v):
        return public_url(v, required=True)

    @field_validator('brief_emails')
    @classmethod
    def emails(cls, v):
        out = []
        for a in v:
            a = a.strip()
            if a and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', a, re.I):
                raise ValueError(f'{a} is not an email address.')
            if a:
                out.append(a)
        return out


class CompetitorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website: str = Field(max_length=500)
    tier: Tier = 'direct'
    socials: Socials = Field(default_factory=Socials)
    why: str = Field(default='', max_length=600)

    @field_validator('website')
    @classmethod
    def site(cls, v):
        return public_url(v, required=True)


class CompetitorPatch(BaseModel):
    status: Literal['confirmed', 'rejected', 'proposed'] | None = None
    tier: Tier | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    socials: Socials | None = None


class SourceIn(BaseModel):
    competitor_id: int | None = None
    kind: Literal['page', 'instagram', 'facebook', 'linkedin', 'ads', 'web'] = 'page'
    url: str
    page_kind: Literal['homepage', 'pricing', 'services', 'clients', 'about', 'careers', 'news'] | None = None

    @field_validator('url')
    @classmethod
    def site(cls, v):
        return public_url(v, required=True)


class SourcePatch(BaseModel):
    enabled: bool


class RunIn(BaseModel):
    source_ids: list[int] = Field(default_factory=list, max_length=60)
    competitor_id: int | None = None
    everything: bool = False


class ScoreIn(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str = Field(default='', max_length=500)


class ClaimIn(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    synonyms: list[str] = Field(default_factory=list, max_length=12)


class HolderIn(BaseModel):
    company: str = Field(pattern=r'^(client|\d+)$')
    holds: bool
    quote: str = Field(default='', max_length=400)


class DecisionIn(BaseModel):
    status: Literal['accepted', 'rejected', 'new']


# ---- Serializers -------------------------------------------------------------------------------

def client_out(c: WatchClient | None):
    if c is None:
        return None
    out = {k: getattr(c, k) for k in ('id', 'name', 'website', 'sector', 'market', 'offer', 'audience', 'positioning',
                                      'price_position', 'channels', 'claims', 'socials', 'brief_emails', 'version',
                                      'updated_at')}
    return out


def competitor_out(c: WatchCompetitor, db: Session | None = None):
    out = {k: getattr(c, k) for k in ('id', 'name', 'website', 'socials', 'tier', 'status', 'origin', 'why', 'decided_by',
                                      'decided_at', 'review_at', 'created_at')}
    out['review_due'] = bool(c.review_at and c.review_at <= datetime.utcnow())
    if db is not None:
        out['sources'] = db.query(WatchSource).filter_by(competitor_id=c.id).count()
    return out


def source_out(s: WatchSource, names: dict):
    return {'id': s.id, 'company': names.get(s.competitor_id, 'You') if s.competitor_id else 'You',
            'competitor_id': s.competitor_id, 'kind': s.kind, 'page_kind': s.page_kind, 'url': s.url,
            'enabled': s.enabled, 'last_run_at': s.last_run_at, 'last_success_at': s.last_success_at,
            'last_error': s.last_error, 'fail_count': s.fail_count, 'next_run_at': s.next_run_at,
            'healthy': s.last_error is None, 'via': via(s)}


def via(s: WatchSource) -> str:
    from api.watch.collect import meta_ready
    if s.kind == 'page':
        return 'Website (Playwright)'
    if s.kind == 'instagram':
        return 'Meta API (free)' if meta_ready() else 'Apify'
    if s.kind == 'web':
        return 'Serper (Google web + news)'
    return 'Apify'


def signal_out(s: WatchSignal, score: WatchScore | None, change: WatchChange | None, names: dict, db=None):
    out = {'id': s.id, 'competitor_id': s.competitor_id,
           'competitor': names.get(s.competitor_id, 'You') if s.competitor_id else 'You',
           'type': s.type, 'theme': s.theme, 'title': s.title, 'meaning': s.meaning, 'claims': s.claims or [],
           'source_url': s.source_url, 'captured_at': s.captured_at, 'created_at': s.created_at,
           'score': effective_score(score), 'ai_score': score.score if score else None,
           'reason': (score.corrected_reason or score.reason) if score else '',
           'corrected': bool(score and score.corrected_score), 'corrected_by': score.corrected_by if score else None}
    if change is not None:
        out['evidence'] = {'field': change.field, 'kind': change.kind, 'before': change.before, 'after': change.after,
                           'before_snapshot_id': change.before_snapshot_id, 'after_snapshot_id': change.after_snapshot_id}
        if db is not None:
            for key in ('before_snapshot_id', 'after_snapshot_id'):
                snap = db.get(WatchSnapshot, change.__dict__[key]) if change.__dict__[key] else None
                out['evidence'][key.replace('_snapshot_id', '_at')] = snap.captured_at if snap else None
    return out


def names_of(db, client_id):
    return {c.id: c.name for c in db.query(WatchCompetitor).filter_by(client_id=client_id)}


def signals_query(db, client_id):
    return (db.query(WatchSignal, WatchScore, WatchChange)
            .outerjoin(WatchScore, WatchScore.signal_id == WatchSignal.id)
            .outerjoin(WatchChange, WatchChange.id == WatchSignal.change_id)
            .filter(WatchSignal.client_id == client_id))


# ---- Client profile and register ------------------------------------------------------------------

@router.get('/client', dependencies=[Depends(reader)])
def read_client(user: AuthUser = Depends(reader), db: Session = Depends(get_db)):
    cid = db.info.get('watch_client')
    client = db.get(WatchClient, cid) if cid else None
    out = {'client': client_out(client), 'starter_claims': STARTER_CLAIMS, 'tiers': list(TIERS),
           'page_kinds': list(PAGE_KINDS), 'email_ready': email_ready(), 'budget': engine.budget(db),
           'clients': [{'id': c.id, 'name': c.name, 'website': c.website}
                       for c in db.query(WatchClient).filter(WatchClient.id.in_(db.info.get('watch_allowed') or []))
                       .order_by(WatchClient.name)]}
    if client:
        out['logins'] = [a.username for a in db.query(WatchAccess).filter_by(client_id=client.id).order_by(WatchAccess.username)]
        out['counts'] = {s: db.query(WatchCompetitor).filter_by(client_id=client.id, status=s).count()
                         for s in ('proposed', 'confirmed', 'rejected', 'queued')}
        out['own_sources'] = db.query(WatchSource).filter_by(client_id=client.id, competitor_id=None).count()
        out['progress'] = progress(db, client)
    return out


def progress(db: Session, client: WatchClient) -> dict:
    """How far the client is along the steps: confirm rivals, baseline, changes, signals, brief."""
    baseline = db.query(WatchSnapshot).join(WatchSource, WatchSource.id == WatchSnapshot.source_id) \
        .filter(WatchSource.client_id == client.id, WatchSource.competitor_id.isnot(None)).count()
    visits = db.query(WatchVisit).filter_by(client_id=client.id)
    running = None
    live = visits.filter(WatchVisit.status == 'collecting', WatchVisit.started_at >= datetime.utcnow() - timedelta(hours=2)) \
        .order_by(WatchVisit.id.desc()).first()
    if live:
        running = {'id': live.id, 'done': len(live.report or {}), 'total': len(live.source_ids or [])}
    scoring = visits.filter(WatchVisit.status == 'scoring').count()
    from sqlalchemy import func
    repeated = db.query(WatchSnapshot.source_id).join(WatchSource, WatchSource.id == WatchSnapshot.source_id) \
        .filter(WatchSource.client_id == client.id, WatchSource.competitor_id.isnot(None)) \
        .group_by(WatchSnapshot.source_id).having(func.count(WatchSnapshot.id) > 1).count()
    return {'confirmed': db.query(WatchCompetitor).filter_by(client_id=client.id, status='confirmed').count(),
            'captures': baseline, 'repeated': repeated,
            'collections': visits.filter(WatchVisit.status.in_(('done', 'scoring'))).count(),
            'running': running, 'scoring': scoring,
            'changes': db.query(WatchChange).join(WatchVisit, WatchVisit.id == WatchChange.visit_id)
            .filter(WatchVisit.client_id == client.id).count(),
            'signals': db.query(WatchSignal).filter_by(client_id=client.id).count(),
            'briefs': db.query(WatchBrief).filter_by(client_id=client.id).filter(WatchBrief.status != 'failed').count(),
            'opportunities': db.query(WatchOpportunity).filter_by(client_id=client.id).count()}


@router.post('/clients')
async def new_client(body: ClientIn, user: AuthUser = Depends(staff), db: Session = Depends(get_db)):
    """Another client, watched separately with its own competitors, sources, briefs and opportunities."""
    if db.query(WatchClient).filter(WatchClient.name == body.name.strip()).first():
        raise HTTPException(409, f'A client called {body.name} already exists. Pick it in the client list.')
    db.info['watch_client'] = None
    return await save_client(body, user, db)


class LoginsIn(BaseModel):
    usernames: list[str] = Field(default_factory=list, max_length=20)


@router.put('/client/logins', dependencies=[Depends(staff)])
def set_logins(body: LoginsIn, db: Session = Depends(get_db)):
    """Client logins that see this client only."""
    from db.database import User
    client = the_client(db)
    names = sorted({n.strip() for n in body.usernames if n.strip()})
    users = {u.username: u for u in db.query(User).filter(User.username.in_(names))}
    missing = [n for n in names if n not in users]
    if missing:
        raise HTTPException(422, f"No account called {', '.join(missing)}. Create it in Team with the Client role first.")
    wrong = [n for n in names if users[n].role != 'client']
    if wrong:
        raise HTTPException(422, f"{', '.join(wrong)} is not a Client account. Only Client accounts are limited to one client.")
    db.query(WatchAccess).filter_by(client_id=client.id).delete()
    for n in names:
        db.add(WatchAccess(client_id=client.id, username=n))
    db.commit()
    return {'logins': names}


@router.put('/client')
async def save_client(body: ClientIn, user: AuthUser = Depends(staff), db: Session = Depends(get_db)):
    cid = db.info.get('watch_client')
    client = db.get(WatchClient, cid) if cid else None
    data = body.model_dump()
    data['socials'] = body.socials.model_dump()
    first = client is None
    if first:
        client = WatchClient(**data)
        db.add(client)
    else:
        for k, v in data.items():
            setattr(client, k, v)
        client.version = (client.version or 1) + 1
    db.commit()
    if first:
        await engine.setup_sources(db, client, None)
    for label in body.claims:
        upsert_claim(db, client.id, label, 'client', 'From the client profile', client.website)
    db.commit()
    return {'client': client_out(client), 'rescore_hint': not first}


@router.post('/client/sources', dependencies=[Depends(staff)])
async def setup_own_sources(db: Session = Depends(get_db)):
    client = the_client(db)
    rows = await engine.setup_sources(db, client, None)
    return {'sources': len(rows)}


@router.get('/competitors', dependencies=[Depends(reader)])
def list_competitors(status: str | None = None, db: Session = Depends(get_db)):
    client = the_client(db)
    q = db.query(WatchCompetitor).filter_by(client_id=client.id)
    if status:
        q = q.filter(WatchCompetitor.status == status)
    return [competitor_out(c, db) for c in q.order_by(WatchCompetitor.status, WatchCompetitor.name)]


@router.post('/competitors/propose', dependencies=[Depends(limited('propose', env_int('LIMIT_SEARCHES_PER_10_MIN', 20), 600))])
async def propose(db: Session = Depends(get_db)):
    """Runs the existing competitor search for the client. Results are proposals only: nothing is watched yet."""
    from api.discovery import DiscoveryRequest, discover
    from api.gemini import GeminiError
    client = the_client(db)
    try:
        result = await discover(DiscoveryRequest(company_name=client.name, context=client.market or '',
                                                 website=client.website, phase='competitors', market_scope='local_first'))
    except GeminiError as exc:
        raise HTTPException(502, str(exc)) from None
    known = {re.sub(r'^www\.', '', (c.website or '').split('//')[-1].split('/')[0].lower())
             for c in db.query(WatchCompetitor).filter_by(client_id=client.id)}
    added = []
    for c in result.get('candidates') or []:
        host = re.sub(r'^www\.', '', c['website'].split('//')[-1].split('/')[0].lower())
        if host in known:
            continue
        known.add(host)
        tier = 'direct' if c.get('relationship') == 'direct' else 'adjacent'
        if c.get('scale') in ('large', 'global', 'enterprise'):
            tier = 'aspirational'
        row = WatchCompetitor(client_id=client.id, name=c['name'], website=c['website'].rstrip('/'), tier=tier,
                              socials={k: c.get(k) or '' for k in ('instagram', 'facebook', 'linkedin')},
                              why=(c.get('rank_reason') or c.get('reason') or c.get('description') or '')[:600])
        db.add(row)
        added.append(row)
    db.commit()
    return {'added': [competitor_out(c) for c in added], 'notice': result.get('notice', '')}


@router.post('/competitors')
async def add_competitor(body: CompetitorIn, user: AuthUser = Depends(watcher), db: Session = Depends(get_db)):
    """Added by a person, so it is confirmed at once (a human confirmed it)."""
    client = the_client(db)
    row = WatchCompetitor(client_id=client.id, name=body.name, website=body.website, tier=body.tier, origin='manual',
                          socials=body.socials.model_dump(), why=body.why or f'Added by {user.username}',
                          status='confirmed', decided_by=user.username, decided_at=datetime.utcnow(),
                          review_at=datetime.utcnow() + timedelta(days=90))
    db.add(row)
    db.commit()
    await engine.setup_sources(db, client, row)
    return competitor_out(row, db)


@router.patch('/competitors/{competitor_id}')
async def decide_competitor(competitor_id: int, body: CompetitorPatch, user: AuthUser = Depends(watcher),
                            db: Session = Depends(get_db)):
    row = get_or_404(db, WatchCompetitor, competitor_id, 'Competitor')
    client = the_client(db)
    tier_changed = body.tier is not None and body.tier != row.tier
    if body.name:
        row.name = body.name
    if body.tier:
        row.tier = body.tier
    if body.socials is not None:
        row.socials = body.socials.model_dump()
    confirming = body.status == 'confirmed' and row.status != 'confirmed'
    if body.status:
        row.status, row.decided_by, row.decided_at = body.status, user.username, datetime.utcnow()
        if body.status == 'confirmed':
            row.review_at = datetime.utcnow() + timedelta(days=90)
    db.commit()
    if confirming or (row.status == 'confirmed' and (tier_changed or body.socials is not None)):
        await engine.setup_sources(db, client, row)
    return competitor_out(row, db)


@router.post('/competitors/{competitor_id}/reviewed', dependencies=[Depends(watcher)])
def reviewed(competitor_id: int, db: Session = Depends(get_db)):
    row = get_or_404(db, WatchCompetitor, competitor_id, 'Competitor')
    row.review_at = datetime.utcnow() + timedelta(days=90)
    db.commit()
    return competitor_out(row, db)


@router.get('/competitors/{competitor_id}', dependencies=[Depends(reader)])
def competitor_detail(competitor_id: int, db: Session = Depends(get_db)):
    comp = get_or_404(db, WatchCompetitor, competitor_id, 'Competitor')
    client = the_client(db)
    names = names_of(db, client.id)
    snaps = latest(db, client.id)
    theirs, mine = snaps.get(str(comp.id), {}), snaps.get('client', {})
    pages = []
    for name, entry in sorted(theirs.items()):
        if not name.startswith('page:'):
            continue
        s, snap = entry['source'], entry['snapshot']
        prev = (db.query(WatchSnapshot).filter(WatchSnapshot.source_id == s.id, WatchSnapshot.id < snap.id)
                .order_by(WatchSnapshot.id.desc()).first())
        pages.append({'source_id': s.id, 'snapshot_id': snap.id, 'page_kind': s.page_kind, 'url': s.url, 'captured_at': snap.captured_at,
                      'fields': snap.fields, 'previous_fields': prev.fields if prev else None, 'words': len(snap.text.split()),
                      'snapshots': db.query(WatchSnapshot).filter_by(source_id=s.id).count(), **page_pictures(snap.metrics)})
    social = {}
    for kind in ('instagram', 'facebook', 'linkedin'):
        if kind in theirs:
            social[kind] = {'them': theirs[kind]['snapshot'].metrics, 'you': mine.get(kind, {}).get('snapshot').metrics
                            if kind in mine else None, 'captured_at': theirs[kind]['snapshot'].captured_at,
                            'posts': theirs[kind]['snapshot'].items}
    ads = theirs.get('ads', {}).get('snapshot')
    web = theirs.get('web', {}).get('snapshot')
    timeline = [signal_out(s, sc, ch, names, db) for s, sc, ch in
                signals_query(db, client.id).filter(WatchSignal.competitor_id == comp.id)
                .order_by(WatchSignal.captured_at.desc()).limit(100)]
    source_ids = [s.id for s in db.query(WatchSource).filter_by(competitor_id=comp.id)]
    log = []
    for v in db.query(WatchVisit).filter_by(client_id=client.id).order_by(WatchVisit.id.desc()).limit(40):
        for sid, entry in (v.report or {}).items():
            if int(sid) in source_ids:
                log.append({'visit_id': v.id, 'at': v.started_at, **entry})
    jobs = next((p['fields'].get('jobs') for p in pages if p['page_kind'] == 'careers'), None)
    sources = [source_out(s, names) for s in db.query(WatchSource).filter_by(competitor_id=comp.id).order_by(WatchSource.kind)]
    claims = [c['label'] for c in claim_map(db, client) if str(comp.id) in c['holders']]
    return {'competitor': competitor_out(comp, db), 'pages': pages, 'social': social, 'jobs': jobs,
            'ads': ads_out(ads),
            'mentions': {'items': web.items, 'captured_at': web.captured_at} if web else None,
            'timeline': timeline, 'claims': claims, 'log': log[:60], 'sources': sources,
            'alerts': [{'rule': a.rule, 'message': a.message, 'at': a.created_at}
                       for a in db.query(WatchAlert).filter_by(competitor_id=comp.id).order_by(WatchAlert.id.desc()).limit(10)]}


def ads_out(snap: WatchSnapshot | None) -> dict | None:
    if not snap:
        return None
    if any('page_name' not in a for a in snap.items or []):
        # Captured before ads were checked against the page: these may belong to other pages.
        return {'items': [], 'metrics': {}, 'captured_at': snap.captured_at, 'unchecked': True}
    return {'items': snap.items, 'metrics': snap.metrics, 'captured_at': snap.captured_at, 'unchecked': False}


@router.get('/ads', dependencies=[Depends(reader)])
def all_ads(db: Session = Depends(get_db)):
    """Every watched competitor's Meta ads from its latest Ad Library check, and who has no Facebook page to check."""
    client = the_client(db)
    out = []
    for comp in db.query(WatchCompetitor).filter_by(client_id=client.id, status='confirmed').order_by(WatchCompetitor.name):
        src = db.query(WatchSource).filter_by(competitor_id=comp.id, kind='ads').first()
        snap = (db.query(WatchSnapshot).filter_by(source_id=src.id).order_by(WatchSnapshot.id.desc()).first()
                if src else None)
        out.append({'competitor_id': comp.id, 'name': comp.name, 'tier': comp.tier,
                    'facebook': (comp.socials or {}).get('facebook') or '', 'socials': comp.socials or {},
                    'source': source_out(src, {comp.id: comp.name}) if src else None,
                    'ads': ads_out(snap)})
    return {'companies': out}


# ---- All scraped data, images and logos ------------------------------------------------------------

def page_pictures(metrics: dict | None) -> dict:
    """A page's pictures: the main ones, every picture with its label, and the page's sections with their pictures."""
    m = metrics or {}
    return {'images': m.get('images') or [], 'pictures': m.get('pictures') or [], 'sections': m.get('sections') or [],
            'screenshot': m.get('screenshot')}


def company_data(snaps: dict) -> dict:
    """One company's latest capture of every source, in the same shape as the competitor detail."""
    pages = []
    for name, entry in sorted(snaps.items()):
        if name.startswith('page:'):
            s, snap = entry['source'], entry['snapshot']
            pages.append({'source_id': s.id, 'snapshot_id': snap.id, 'page_kind': s.page_kind, 'url': s.url,
                          'captured_at': snap.captured_at, 'fields': snap.fields, 'words': len((snap.text or '').split()),
                          'snapshots': 1, **page_pictures(snap.metrics)})
    social = {kind: {'them': snaps[kind]['snapshot'].metrics, 'you': None, 'captured_at': snaps[kind]['snapshot'].captured_at,
                     'posts': snaps[kind]['snapshot'].items} for kind in ('instagram', 'facebook', 'linkedin') if kind in snaps}
    ads, web = snaps.get('ads', {}).get('snapshot'), snaps.get('web', {}).get('snapshot')
    return {'pages': pages, 'social': social, 'ads': ads_out(ads),
            'mentions': {'items': web.items, 'captured_at': web.captured_at} if web else None,
            'jobs': next((p['fields'].get('jobs') for p in pages if p['page_kind'] == 'careers'), None)}


def image_links(snaps: dict) -> list[dict]:
    """Every saved picture of one company, with where it came from."""
    out = []
    for name, entry in snaps.items():
        snap, s = entry['snapshot'], entry['source']
        m = snap.metrics or {}
        for key, label in (('avatar', 'profile picture'), ('logo', 'site logo')):
            if m.get(key):
                out.append({'url': m[key], 'source': s.kind, 'label': f'{s.kind.title() if s.kind != "page" else "Website"} {label}',
                            'link': s.url, 'logo': True})
        for p in m.get('pictures') or []:
            if isinstance(p, dict) and p.get('url'):
                out.append({'url': p['url'], 'source': 'page', 'label': p.get('name') or p.get('label') or 'Website picture',
                            'link': s.url, 'kind': p.get('kind'), 'logo': p.get('kind') in ('brand_logo', 'client_logo', 'partner_logo', 'logo')})
        for u in m.get('images') or []:
            out.append({'url': u, 'source': 'page', 'label': f'Website · {s.page_kind or "page"}', 'link': s.url})
        if m.get('screenshot'):
            out.append({'url': m['screenshot'], 'source': 'page', 'label': f'Full-page screenshot · {s.page_kind or "page"}',
                        'link': s.url, 'kind': 'screenshot', 'date': snap.captured_at})
        if s.kind == 'ads' and any('page_name' not in a for a in snap.items or []):
            continue
        for item in snap.items or []:
            for u in item.get('images') or []:
                out.append({'url': u, 'source': s.kind, 'label': (item.get('caption') or item.get('headline') or item.get('body') or '')[:120],
                            'link': item.get('url') or s.url, 'date': item.get('date') or item.get('start')})
    seen, unique = set(), []
    for i in out:
        if i['url'] not in seen and str(i['url']).startswith(('https://', 'http://', 'shot:')):
            seen.add(i['url'])
            unique.append(i)
    return unique


def all_companies(db: Session, client: WatchClient):
    snaps = latest(db, client.id)
    comps = {c.id: c for c in db.query(WatchCompetitor).filter_by(client_id=client.id, status='confirmed')}
    for c in companies(db, client):
        row = comps.get(c['id'])
        yield {'key': c['key'], 'name': c['name'], 'tier': c['tier'], 'you': c['you'],
               'website': client.website if c['you'] else (row.website if row else ''),
               'socials': (client.socials if c['you'] else (row.socials if row else {})) or {}}, snaps.get(c['key'], {})


@router.get('/data', dependencies=[Depends(reader)])
def all_data(db: Session = Depends(get_db)):
    """Everything collected for you and every watched competitor, from the latest capture of each source."""
    client = the_client(db)
    out = []
    for info, snaps in all_companies(db, client):
        times = [e['snapshot'].captured_at for e in snaps.values()]
        out.append({**info, **company_data(snaps), 'images': image_links(snaps), 'captured_at': max(times) if times else None})
    return {'client': client.name, 'companies': out}


_logos: dict = {}


async def logo_bytes(candidates: list[str], website: str):
    """The site's sharpest own icon first (saved on this computer), then the profile picture or site logo."""
    from api.logos import company_logo, site_root
    from api.watch import pictures
    root = site_root(website)
    if root:
        kept = pictures.saved('site-logo:' + root)
        if kept is not None:
            from api.media import image_type
            return kept, image_type(kept, icons=True)[0]
        found = await company_logo(website)
        if found is not None:
            pictures.keep('site-logo:' + root, found[0])
            return found
    for url in candidates:
        try:
            data, mime = await pictures.get(url, icons=True)
            if len(data) > 400:
                return data, mime
        except HTTPException:
            continue
    return None


@router.get('/logo/{key}', dependencies=[Depends(reader), Depends(rate_limit('images', env_int('LIMIT_IMAGES_PER_MIN', 240), 60))])
async def company_logo_image(key: str, db: Session = Depends(get_db)):
    """A company's logo: the site's browser-tab icon, else its social profile picture or the logo in the site header.
    Cached for a day."""
    client = the_client(db)
    found = None
    for info, snaps in all_companies(db, client):
        if info['key'] == key:
            found = (info, snaps)
    if found is None and key.isdigit():
        # A proposed competitor has no captures yet: its site icon still works.
        row = db.get(WatchCompetitor, int(key))
        if row is not None and row.client_id == client.id:
            found = ({'key': key, 'website': row.website or ''}, {})
    if found is None:
        raise HTTPException(404, 'Company not found')
    info, snaps = found
    candidates = [snaps[k]['snapshot'].metrics.get('avatar') for k in ('linkedin', 'facebook', 'instagram')
                  if k in snaps and (snaps[k]['snapshot'].metrics or {}).get('avatar')]
    candidates += [e['snapshot'].metrics.get('logo') for n, e in sorted(snaps.items()) if n.startswith('page:')
                   and (e['snapshot'].metrics or {}).get('logo')]
    cache_key = (client.id, key, tuple(candidates), info['website'])
    hit = _logos.get(cache_key)
    if hit is None or datetime.utcnow() - hit[0] > timedelta(hours=24 if hit[1] else 1):
        hit = (datetime.utcnow(), await logo_bytes(candidates, info['website']))
        _logos[cache_key] = hit
    if hit[1] is None:
        raise HTTPException(404, 'No logo found for this company')
    content, mime = hit[1]
    return Response(content, media_type=mime, headers={
        'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox"})


def known_image(db: Session, client: WatchClient, url: str) -> bool:
    return any(i['url'] == url for _, snaps in all_companies(db, client) for i in image_links(snaps))


@router.get('/image', dependencies=[Depends(reader), Depends(rate_limit('images', env_int('LIMIT_IMAGES_PER_MIN', 240), 60))])
async def saved_image(u: str = Query(..., max_length=4000), download: bool = False, db: Session = Depends(get_db)):
    """One saved picture through the app, so it can be downloaded. Only links stored in this client's captures."""
    from api.watch import pictures
    from api.watch.collect import is_picture_link
    if u.startswith('shot:'):   # a full-page screenshot of a watched page, kept as a JPEG on this computer
        client = the_client(db)
        known = any((e['snapshot'].metrics or {}).get('screenshot') == u for _, snaps in all_companies(db, client) for e in snaps.values())
        content = pictures.shot(u) if known else None
        if content is None:
            raise HTTPException(404, 'This screenshot is not saved.')
        return Response(content, media_type='image/jpeg', headers={
            'Content-Disposition': f'{"attachment" if download else "inline"}; filename="{u.rsplit("/", 2)[-2]}-{u.rsplit("/", 1)[-1]}"',
            'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; sandbox"})
    if not is_picture_link(u):   # a Facebook/Instagram page saved by older collectors: answer without fetching it
        raise HTTPException(404, 'This link is a post page, not a picture.')
    if not known_image(db, the_client(db), u):
        raise HTTPException(404, 'This image is not in the saved data.')
    content, mime = await pictures.get(u, icons=True)   # client logos are often SVG; the sandbox header keeps them inert
    ext = mime.split('/')[-1].replace('jpeg', 'jpg')
    name = re.sub(r'[^a-z0-9]+', '-', urlsplit(u).path.rsplit('/', 1)[-1].rsplit('.', 1)[0].lower()).strip('-')[:60] or 'image'
    return Response(content, media_type=mime, headers={
        'Content-Disposition': f'{"attachment" if download else "inline"}; filename="{name}.{ext}"',
        'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; sandbox"})


@router.get('/data.zip', dependencies=[Depends(reader), Depends(rate_limit('image_zip', env_int('LIMIT_IMAGE_ZIPS_PER_10_MIN', 6), 600))])
async def data_zip(company: str | None = None, images: bool = True, db: Session = Depends(get_db)):
    """All scraped data as one zip: data.json, one CSV of items per company, and the pictures in folders."""
    import csv, io, json, zipfile
    from fastapi.encoders import jsonable_encoder
    from api.watch import pictures
    client = the_client(db)
    rows = [(info, snaps) for info, snaps in all_companies(db, client) if company in (None, '', info['key'])]
    if not rows:
        raise HTTPException(404, 'Company not found')
    slug = lambda v: re.sub(r'[^a-z0-9]+', '-', str(v).lower()).strip('-') or 'company'
    buffer = io.BytesIO()
    jobs = [(info, i) for info, snaps in rows for i in image_links(snaps)][:300] if images else []
    gate = asyncio.Semaphore(6)

    async def get(job):
        async with gate:
            try:
                if job[1]['url'].startswith('shot:'):
                    shot = pictures.shot(job[1]['url'])
                    if shot is None:
                        return job, 'The screenshot is no longer saved.'
                    return job, (shot, 'image/jpeg', 'jpg')
                content, mime = await pictures.get(job[1]['url'])
                return job, (content, mime, mime.split('/')[-1].replace('jpeg', 'jpg'))
            except HTTPException as exc:
                return job, exc.detail
    got = await asyncio.gather(*(get(j) for j in jobs))
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        data = [{**info, **company_data(snaps), 'images': image_links(snaps)} for info, snaps in rows]
        z.writestr('data.json', json.dumps(jsonable_encoder({'client': client.name, 'companies': data}), ensure_ascii=False, indent=2))
        for d in data:
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(['source', 'kind', 'date', 'title or caption', 'likes', 'comments', 'shares', 'url', 'images'])
            for p in d['pages']:
                w.writerow(['website', p['page_kind'], p['captured_at'], (p['fields'] or {}).get('headline', ''), '', '', '', p['url'],
                            ' '.join(p['images'])])
            for kind, soc in d['social'].items():
                for x in soc['posts'] or []:
                    w.writerow([kind, x.get('format'), x.get('date'), x.get('caption'), x.get('likes'), x.get('comments'),
                                x.get('shares'), x.get('url'), ' '.join(x.get('images') or [])])
            for x in (d['ads'] or {}).get('items') or []:
                w.writerow(['ads', 'live' if x.get('active') else 'ended', x.get('start'), f"{x.get('headline') or ''} {x.get('body') or ''}".strip(),
                            '', '', '', x.get('url'), ' '.join(x.get('images') or [])])
            for x in (d['mentions'] or {}).get('items') or []:
                w.writerow(['web', x.get('kind'), x.get('date'), x.get('title'), '', '', '', x.get('url'), ''])
            for j in d['jobs'] or []:
                w.writerow(['jobs', 'role', '', j, '', '', '', '', ''])
            z.writestr(f"{slug(d['name'])}/items.csv", '\ufeff' + out.getvalue())
        failed, n = [], 0
        for (info, i), result in got:
            if isinstance(result, tuple):
                n += 1
                content, _, ext = result
                z.writestr(f"{slug(info['name'])}/images/{i['source']}-{n:03d}.{ext}", content)
            else:
                failed.append(f"{info['name']} · {i['label'] or i['source']}: {result}\n  {i['url']}")
        z.writestr('README.txt', f"Odynza Radar · {client.name}\n{n} of {len(jobs)} pictures saved."
                   + ('\n\nNot saved (the link expired or the site refused):\n' + '\n'.join(failed) if failed else ''))
    name = f"radar-{slug(client.name)}" + (f"-{slug(rows[0][0]['name'])}" if company else '')
    return Response(buffer.getvalue(), media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="{name}.zip"', 'Cache-Control': 'private, no-store'})


@router.get('/snapshots/{snapshot_id}', dependencies=[Depends(reader)])
def read_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    snap = get_or_404(db, WatchSnapshot, snapshot_id, 'Capture')
    source = db.get(WatchSource, snap.source_id)
    return {'id': snap.id, 'source': {'kind': source.kind, 'url': source.url, 'page_kind': source.page_kind},
            'captured_at': snap.captured_at, 'text': snap.text, 'fields': snap.fields, 'metrics': snap.metrics,
            'items': snap.items}


# ---- Sources, runs and health ------------------------------------------------------------------

@router.get('/sources', dependencies=[Depends(reader)])
def list_sources(db: Session = Depends(get_db)):
    client = the_client(db)
    names = names_of(db, client.id)
    rows = db.query(WatchSource).filter_by(client_id=client.id).order_by(WatchSource.competitor_id, WatchSource.kind).all()
    out = [source_out(s, names) for s in rows]
    return {'sources': out, 'healthy': sum(1 for s in out if s['enabled'] and s['healthy']),
            'enabled': sum(1 for s in out if s['enabled']), 'budget': engine.budget(db),
            'visits': [{'id': v.id, 'trigger': v.trigger, 'status': v.status, 'error': v.error, 'started_at': v.started_at,
                        'finished_at': v.finished_at, 'changes': sum((e.get('changes') or 0) for e in (v.report or {}).values())}
                       for v in db.query(WatchVisit).filter_by(client_id=client.id).order_by(WatchVisit.id.desc()).limit(15)]}


@router.post('/sources', dependencies=[Depends(watcher)])
def add_source(body: SourceIn, db: Session = Depends(get_db)):
    client = the_client(db)
    if body.competitor_id is not None:
        get_or_404(db, WatchCompetitor, body.competitor_id, 'Competitor')
    row = engine.add_source(db, client.id, body.competitor_id, body.kind, body.url,
                            body.page_kind or ('homepage' if body.kind == 'page' else None))
    db.commit()
    return source_out(row, names_of(db, client.id))


@router.patch('/sources/{source_id}', dependencies=[Depends(watcher)])
def toggle_source(source_id: int, body: SourcePatch, db: Session = Depends(get_db)):
    row = get_or_404(db, WatchSource, source_id, 'Source')
    row.enabled = body.enabled
    if body.enabled:
        row.next_run_at = datetime.utcnow()
    db.commit()
    return source_out(row, names_of(db, row.client_id))


@router.post('/run', status_code=202, dependencies=[Depends(limited('run', env_int('LIMIT_WATCH_RUNS_PER_HOUR', 12), 3600))])
async def run_now(body: RunIn, db: Session = Depends(get_db)):
    client = the_client(db)
    q = db.query(WatchSource).filter_by(client_id=client.id, enabled=True)
    if body.source_ids:
        q = q.filter(WatchSource.id.in_(body.source_ids))
    elif body.competitor_id is not None:
        q = q.filter(WatchSource.competitor_id == body.competitor_id)
    elif not body.everything:
        return {'started': False, 'message': 'Choose sources, a competitor, or everything.'}
    rows = []
    for s in q.all():
        if s.competitor_id is not None:
            comp = db.get(WatchCompetitor, s.competitor_id)
            if comp is None or comp.status != 'confirmed':
                continue
        rows.append(s.id)
    if not rows:
        return {'started': False, 'message': 'Nothing to collect: confirm a competitor or enable its sources first.'}
    background(engine.run_visit(rows, 'run_now'))
    return {'started': True, 'sources': len(rows), 'message': f'Collecting {len(rows)} sources now. Pages take a few '
                                                              'seconds each; Apify sources up to a few minutes.'}


@router.post('/visits/{visit_id}/resend', dependencies=[Depends(staff)])
async def resend(visit_id: int, db: Session = Depends(get_db)):
    visit = get_or_404(db, WatchVisit, visit_id, 'Visit')
    visit.status, visit.error = 'scoring', None
    db.commit()
    error = await engine.send_to_n8n(visit_id, 'rescore' if visit.trigger == 'rescore' else 'changes')
    if error:
        raise HTTPException(502, error)
    return {'visit_id': visit_id, 'status': 'scoring'}


# ---- Overview, signals and scores ------------------------------------------------------------------

@router.get('/overview')
def overview(user: AuthUser = Depends(reader), db: Session = Depends(get_db)):
    client = the_client(db)
    names = names_of(db, client.id)
    seen_row = db.get(WatchState, f'seen:{user.id}')
    since = datetime.fromisoformat(seen_row.value) if seen_row and seen_row.value else datetime.utcnow() - timedelta(days=7)
    rows = signals_query(db, client.id).filter(WatchSignal.created_at >= since).all()
    rows.sort(key=lambda r: (effective_score(r[1]) or 0, r[0].captured_at), reverse=True)
    top = [signal_out(s, sc, ch, names) for s, sc, ch in rows if (effective_score(sc) or 0) >= 2][:5]
    card = scorecard(db, client)
    sources = db.query(WatchSource).filter_by(client_id=client.id, enabled=True).all()
    next_run = min((s.next_run_at for s in sources if s.next_run_at), default=None)
    brief = (db.query(WatchBrief).filter_by(client_id=client.id, status='ready')
             .order_by(WatchBrief.week_start.desc(), WatchBrief.id.desc()).first())
    return {'client': client.name, 'since': since, 'items': top, 'item_cap': 5, 'quiet': not top,
            'brief': brief_out(brief) if brief else None, 'snapshot': week_snapshot(db, client),
            'watched': db.query(WatchCompetitor).filter_by(client_id=client.id, status='confirmed').count(),
            'next_check': next_run, 'new_opportunities': db.query(WatchOpportunity).filter_by(client_id=client.id, status='new').count(),
            'new_entrants': db.query(WatchCompetitor).filter_by(client_id=client.id, status='proposed').count(),
            'review_due': db.query(WatchCompetitor).filter(WatchCompetitor.client_id == client.id,
                                                           WatchCompetitor.status == 'confirmed',
                                                           WatchCompetitor.review_at <= datetime.utcnow()).count(),
            'sources': {'healthy': sum(1 for s in sources if not s.last_error), 'total': len(sources)},
            'budget': engine.budget(db), 'scorecard': card['rows'],
            'alerts': [{'rule': a.rule, 'message': a.message, 'competitor': names.get(a.competitor_id), 'at': a.created_at}
                       for a in db.query(WatchAlert).filter_by(client_id=client.id).order_by(WatchAlert.id.desc()).limit(5)]}


@router.post('/overview/seen')
def mark_seen(user: AuthUser = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(WatchState, f'seen:{user.id}') or WatchState(key=f'seen:{user.id}')
    row.value = datetime.utcnow().isoformat()
    db.merge(row)
    db.commit()
    return {'seen_at': row.value}


@router.get('/signals', dependencies=[Depends(reader)])
def list_signals(competitor_id: int | None = None, min_score: int = Query(1, ge=1, le=5),
                 days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    client = the_client(db)
    q = signals_query(db, client.id).filter(WatchSignal.created_at >= datetime.utcnow() - timedelta(days=days))
    if competitor_id is not None:
        q = q.filter(WatchSignal.competitor_id == competitor_id)
    names = names_of(db, client.id)
    rows = [signal_out(s, sc, ch, names) for s, sc, ch in q.order_by(WatchSignal.captured_at.desc()).limit(300)]
    return [r for r in rows if (r['score'] or 0) >= min_score]


@router.patch('/signals/{signal_id}/score')
def correct_score(signal_id: int, body: ScoreIn, user: AuthUser = Depends(watcher), db: Session = Depends(get_db)):
    """Corrections are kept apart from the AI score and sent to the impact agent as examples."""
    get_or_404(db, WatchSignal, signal_id, 'Signal')
    score = db.get(WatchScore, signal_id)
    if score is None:
        raise HTTPException(409, 'This signal has no score yet.')
    score.corrected_score, score.corrected_reason = body.score, body.reason or None
    score.corrected_by, score.corrected_at = user.username, datetime.utcnow()
    db.commit()
    return {'signal_id': signal_id, 'score': body.score, 'ai_score': score.score, 'corrected_by': user.username}


@router.post('/rescore', dependencies=[Depends(limited('rescore', 6, 3600))])
async def rescore(days: int = Query(30, ge=1, le=120), db: Session = Depends(get_db)):
    """Sends stored signals back to the impact stage. Nothing is collected again (F20)."""
    client = the_client(db)
    ids = [s.change_id for s in db.query(WatchSignal).filter(WatchSignal.client_id == client.id,
                                                              WatchSignal.created_at >= datetime.utcnow() - timedelta(days=days))]
    if not ids:
        return {'started': False, 'message': 'No signals to rescore yet.'}
    visit = WatchVisit(client_id=client.id, trigger='rescore', status='scoring', report={'change_ids': ids[:60]})
    db.add(visit)
    db.commit()
    error = await engine.send_to_n8n(visit.id, 'rescore')
    if error:
        raise HTTPException(502, error)
    return {'started': True, 'visit_id': visit.id, 'signals': len(ids[:60])}


# ---- Compare and claim map -----------------------------------------------------------------------

def upsert_claim(db, client_id, label, holder, quote, url):
    label = ' '.join(label.split())[:120]
    if not label:
        return None
    rows = db.query(WatchClaim).filter_by(client_id=client_id).all()
    row = next((r for r in rows if r.label.lower() == label.lower() or label.lower() in [s.lower() for s in r.synonyms or []]), None)
    if row is None:
        row = WatchClaim(client_id=client_id, label=label, synonyms=[], holders={})
        db.add(row)
    if holder:
        holders = dict(row.holders or {})
        holders[holder] = {'quote': (quote or '')[:400], 'source_url': url or '', 'at': datetime.utcnow().isoformat()}
        row.holders = holders
    return row


@router.get('/compare', dependencies=[Depends(reader)])
def compare(db: Session = Depends(get_db)):
    client = the_client(db)
    return {'companies': companies(db, client), 'scorecard': scorecard(db, client), 'gaps': content_gaps(db, client),
            'claims': claim_map(db, client)}


@router.post('/claims', dependencies=[Depends(watcher)])
def add_claim(body: ClaimIn, db: Session = Depends(get_db)):
    client = the_client(db)
    row = upsert_claim(db, client.id, body.label, None, '', '')
    row.synonyms = body.synonyms
    db.commit()
    return {'id': row.id, 'label': row.label}


@router.patch('/claims/{claim_id}')
def edit_claim(claim_id: int, body: ClaimIn, user: AuthUser = Depends(watcher), db: Session = Depends(get_db)):
    row = get_or_404(db, WatchClaim, claim_id, 'Claim')
    row.label, row.synonyms, row.edited_by = body.label, body.synonyms, user.username
    db.commit()
    return {'id': row.id, 'label': row.label, 'synonyms': row.synonyms}


@router.post('/claims/{claim_id}/merge/{into_id}', dependencies=[Depends(watcher)])
def merge_claim(claim_id: int, into_id: int, db: Session = Depends(get_db)):
    src, dst = get_or_404(db, WatchClaim, claim_id, 'Claim'), get_or_404(db, WatchClaim, into_id, 'Claim')
    if src.id == dst.id:
        raise HTTPException(422, 'Choose a different claim to merge into.')
    dst.holders = {**(src.holders or {}), **(dst.holders or {})}
    dst.synonyms = sorted({*(dst.synonyms or []), *(src.synonyms or []), src.label})
    db.delete(src)
    db.commit()
    return {'id': dst.id, 'label': dst.label}


@router.put('/claims/{claim_id}/holders', dependencies=[Depends(watcher)])
def set_holder(claim_id: int, body: HolderIn, db: Session = Depends(get_db)):
    row = get_or_404(db, WatchClaim, claim_id, 'Claim')
    holders = dict(row.holders or {})
    if body.holds:
        holders[body.company] = {'quote': body.quote, 'source_url': '', 'at': datetime.utcnow().isoformat(), 'by_hand': True}
    else:
        holders.pop(body.company, None)
    row.holders = holders
    db.commit()
    return {'id': row.id, 'holders': row.holders}


# ---- Brief ----------------------------------------------------------------------------------------

def brief_out(b: WatchBrief):
    return {'id': b.id, 'week_start': b.week_start, 'status': b.status, 'headline': b.headline, 'items': b.items or [],
            'quiet': b.quiet, 'error': b.error, 'emailed_at': b.emailed_at, 'email_error': b.email_error,
            'created_at': b.created_at, 'updated_at': b.updated_at}


@router.get('/briefs', dependencies=[Depends(reader)])
def list_briefs(db: Session = Depends(get_db)):
    client = the_client(db)
    return {'briefs': [brief_out(b) for b in db.query(WatchBrief).filter_by(client_id=client.id)
                       .order_by(WatchBrief.week_start.desc()).limit(52)],
            'email_ready': email_ready(), 'recipients': client.brief_emails or [], 'snapshot': week_snapshot(db, client)}


@router.post('/briefs/make', dependencies=[Depends(limited('brief', 6, 3600))])
async def make_brief(db: Session = Depends(get_db)):
    client = the_client(db)
    brief_id, error = await scheduler.start_weekly(client.id, scheduler.brief_week(), force=True)
    if error:
        raise HTTPException(502, error)
    return {'brief_id': brief_id, 'status': 'running'}


@router.get('/briefs/{brief_id}/view', response_class=HTMLResponse, dependencies=[Depends(reader)])
def view_brief(brief_id: int, db: Session = Depends(get_db)):
    b = get_or_404(db, WatchBrief, brief_id, 'Brief')
    client = the_client(db)
    return HTMLResponse(brief_html(client.name, brief_out(b), snapshot=week_snapshot(db, client)))


@router.get('/briefs/{brief_id}/pdf', dependencies=[Depends(reader)])
async def brief_pdf_download(brief_id: int, db: Session = Depends(get_db)):
    b = get_or_404(db, WatchBrief, brief_id, 'Brief')
    if b.status != 'ready':
        raise HTTPException(409, 'Only a finished brief can be downloaded.')
    try:
        client = the_client(db)
        pdf = await brief_pdf(client.name, brief_out(b), week_snapshot(db, client))
    except Exception as exc:
        raise HTTPException(503, 'The PDF could not be created. Install the browser once with '
                                 f'`python -m playwright install chromium`. ({type(exc).__name__})') from None
    return Response(pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="competitor-brief-{b.week_start}.pdf"'})


@router.post('/briefs/{brief_id}/email', dependencies=[Depends(limited('email', 10, 3600))])
async def email_now(brief_id: int):
    error = await scheduler.email_brief(brief_id)
    if error:
        raise HTTPException(502, error)
    return {'sent': True}


# ---- Opportunities and the strategy handoff -----------------------------------------------------------

def opportunity_out(o: WatchOpportunity, db):
    plan = db.get(StrategyPlan, o.plan_id) if o.plan_id else None
    out = {k: getattr(o, k) for k in ('id', 'week_start', 'rank', 'angle', 'trigger', 'claim', 'audience', 'why_now',
                                      'competitors_saying', 'wrong_if', 'confidence', 'expires_on', 'evidence', 'status',
                                      'decided_by', 'plan_id', 'outcome', 'created_at')}
    out['plan_status'] = plan.status if plan else None
    return out


@router.get('/opportunities', dependencies=[Depends(reader)])
def list_opportunities(status: str | None = None, db: Session = Depends(get_db)):
    client = the_client(db)
    q = db.query(WatchOpportunity).filter_by(client_id=client.id)
    if status:
        q = q.filter(WatchOpportunity.status == status)
    rows = q.order_by(WatchOpportunity.week_start.desc(), WatchOpportunity.rank).limit(100).all()
    for o in rows:
        if o.plan_id:
            plan = db.get(StrategyPlan, o.plan_id)
            if plan and plan.status in ('completed', 'failed'):
                o.outcome = ('Strategy plan ready: ' + (plan.plan or {}).get('executive_summary', '')[:300]
                             if plan.status == 'completed' else f'Strategy plan failed: {plan.error or ""}'[:400])
    db.commit()
    return [opportunity_out(o, db) for o in rows]


@router.patch('/opportunities/{opportunity_id}')
def decide_opportunity(opportunity_id: int, body: DecisionIn, user: AuthUser = Depends(watcher), db: Session = Depends(get_db)):
    o = get_or_404(db, WatchOpportunity, opportunity_id, 'Opportunity')
    if o.status in ('acted', 'expired'):
        raise HTTPException(409, f'This opportunity is already {o.status}.')
    o.status, o.decided_by = body.status, user.username
    db.commit()
    return opportunity_out(o, db)


@router.post('/opportunities/{opportunity_id}/act', dependencies=[Depends(limited('act', 12, 3600))])
async def act(opportunity_id: int, request: Request, db: Session = Depends(get_db)):
    """Opens a new strategy plan built around the opportunity; the plan id is written back."""
    from api.routers.radar_plans import start_radar_plan
    from api.strategy_plan import RadarPlanRequest
    o = get_or_404(db, WatchOpportunity, opportunity_id, 'Opportunity')
    if o.status in ('rejected', 'expired'):
        raise HTTPException(409, f'This opportunity is {o.status}.')
    client = the_client(db)
    start = date.today() + timedelta(days=1)
    try:
        expires = date.fromisoformat(o.expires_on)
    except ValueError:
        expires = start
    end = max(start + timedelta(days=30), min(start + timedelta(days=89), expires + timedelta(days=30)))
    plan_req = RadarPlanRequest(
        goal='Leads', objective=f'{o.angle} (claim: {o.claim})'[:600], audience=o.audience[:300],
        start_date=start, end_date=end, opportunity_id=o.id,
        constraints=(f'Why now: {o.why_now}. What would make this wrong: {o.wrong_if}.')[:600])
    plan = await start_radar_plan(db, request, client, plan_req)
    o.status, o.plan_id, o.outcome = 'acted', plan['plan_id'], 'The strategy plan is being written.'
    db.commit()
    return opportunity_out(o, db)


@router.get('/alerts', dependencies=[Depends(reader)])
def alerts(db: Session = Depends(get_db)):
    client = the_client(db)
    names = names_of(db, client.id)
    return [{'id': a.id, 'rule': a.rule, 'message': a.message, 'competitor': names.get(a.competitor_id), 'at': a.created_at}
            for a in db.query(WatchAlert).filter_by(client_id=client.id).order_by(WatchAlert.id.desc()).limit(50)]


# ---- n8n callbacks (X-Radar-Token or a direct local call) ----------------------------------------------

class SignalIn(BaseModel):
    change_id: int
    type: str = Field(min_length=2, max_length=30)
    theme: str = Field(default='', max_length=120)
    title: str = Field(default='', max_length=300)
    meaning: str = Field(default='', max_length=1200)
    claims: list[str] = Field(default_factory=list, max_length=8)
    score: int = Field(ge=1, le=5)
    reason: str = Field(default='', max_length=600)


class SignalsResult(BaseModel):
    signals: list[SignalIn] = Field(max_length=80)
    model: str = Field(default='', max_length=100)


class Failure(BaseModel):
    error: str = Field(min_length=1, max_length=2000)


class BriefItemIn(BaseModel):
    signal_id: int
    move: str = Field(default='', max_length=400)


class ClaimSeen(BaseModel):
    company: str = Field(max_length=20)
    label: str = Field(min_length=2, max_length=120)
    quote: str = Field(default='', max_length=400)


class OpportunityIn(BaseModel):
    rank: int = Field(ge=1, le=20)
    angle: str = Field(default='', max_length=600)
    trigger: str = Field(default='', max_length=600)
    claim: str = Field(default='', max_length=200)
    audience: str = Field(default='', max_length=400)
    why_now: str = Field(default='', max_length=600)
    competitors_saying: str = Field(default='', max_length=600)
    wrong_if: str = Field(default='', max_length=600)
    confidence: str = Field(default='', max_length=10)
    expires_on: str = Field(default='', max_length=10)
    evidence: list[str] = Field(default_factory=list, max_length=12)


class BriefResult(BaseModel):
    headline: str = Field(default='', max_length=300)
    quiet: bool = False
    items: list[BriefItemIn] = Field(default_factory=list, max_length=10)
    claims: list[ClaimSeen] = Field(default_factory=list, max_length=200)
    opportunities: list[OpportunityIn] = Field(default_factory=list, max_length=10)
    model: str = Field(default='', max_length=100)


def n8n_only(request: Request, x_radar_token: str | None = Header(default=None)):
    callback_allowed(request, x_radar_token)


def profile_text(c: WatchClient) -> str:
    return (f'{c.name} ({c.website}), sector {c.sector}, market {c.market}. Sells: {c.offer or "not given"}. '
            f'To: {c.audience or "not given"}. Positioning: {c.positioning or "not given"}. Price position: {c.price_position}. '
            f'Claims it makes: {", ".join(c.claims or []) or "none listed"}. Channels: {", ".join(c.channels or []) or "not given"}.')


@n8n.get('/visits/{visit_id}/pack', dependencies=[Depends(n8n_only)])
def visit_pack(visit_id: int, db: Session = Depends(get_db)):
    visit = get_or_404(db, WatchVisit, visit_id, 'Visit')
    client = db.get(WatchClient, visit.client_id)
    names = names_of(db, client.id)
    tiers = {c.id: c.tier for c in db.query(WatchCompetitor).filter_by(client_id=client.id)}
    if visit.trigger == 'rescore':
        ids = (visit.report or {}).get('change_ids') or []
        changes = db.query(WatchChange).filter(WatchChange.id.in_(ids)).all() if ids else []
    else:
        changes = (db.query(WatchChange).join(WatchSource, WatchSource.id == WatchChange.source_id)
                   .filter(WatchSource.client_id == client.id, WatchChange.status == 'new')
                   .order_by(WatchChange.id).limit(60).all())
    corrections = (db.query(WatchScore, WatchSignal).join(WatchSignal, WatchSignal.id == WatchScore.signal_id)
                   .filter(WatchSignal.client_id == client.id, WatchScore.corrected_score.isnot(None))
                   .order_by(WatchScore.corrected_at.desc()).limit(10).all())
    rows = []
    for ch in changes:
        s = db.get(WatchSource, ch.source_id)
        snap = db.get(WatchSnapshot, ch.after_snapshot_id)
        rows.append({'change_id': ch.id, 'company': names.get(ch.competitor_id, client.name) if ch.competitor_id else
                     f'{client.name} (the client itself)', 'tier': tiers.get(ch.competitor_id, 'client'),
                     'source': {'page': f'website {s.page_kind or "page"}', 'web': 'web and news search'}.get(s.kind, s.kind),
                     'url': s.url,
                     'field': ch.field, 'kind': ch.kind, 'before': (ch.before or '')[:600], 'after': (ch.after or '')[:600],
                     'captured_at': snap.captured_at.isoformat() if snap else None})
    lines = '\n'.join(f"[{r['change_id']}] {r['company']} ({r['tier']}) · {r['source']} · {r['field']} {r['kind']}: "
                      f"BEFORE «{r['before']}» AFTER «{r['after']}»" for r in rows)
    examples = '\n'.join(f'- "{sig.title}": the AI said {sc.score}, the client corrected it to {sc.corrected_score}'
                         + (f' because {sc.corrected_reason}' if sc.corrected_reason else '') for sc, sig in corrections)
    return {'visit_id': visit.id, 'mode': visit.trigger, 'client_id': client.id, 'count': len(rows), 'changes': rows,
            'changes_text': lines or 'none', 'profile': profile_text(client), 'scale': SCALE,
            'corrections': examples or 'none yet', 'claims': ', '.join(STARTER_CLAIMS + [c.label for c in
                                                                                          db.query(WatchClaim).filter_by(client_id=client.id)])}


@n8n.post('/visits/{visit_id}/signals', dependencies=[Depends(n8n_only)])
def save_signals(visit_id: int, body: SignalsResult, db: Session = Depends(get_db)):
    visit = get_or_404(db, WatchVisit, visit_id, 'Visit')
    client = db.get(WatchClient, visit.client_id)
    saved, rejected = 0, []
    for item in body.signals:
        change = db.get(WatchChange, item.change_id)
        source = db.get(WatchSource, change.source_id) if change else None
        if change is None or source is None or source.client_id != client.id:
            rejected.append(f'{item.change_id}: unknown change')
            continue
        if item.type.lower() == 'noise':
            change.status = 'ignored'
            continue
        if not item.meaning.strip() or not item.title.strip():
            rejected.append(f'{item.change_id}: no "what it means for you" line')   # consequence, not summary
            continue
        snap = db.get(WatchSnapshot, change.after_snapshot_id)
        signal = db.query(WatchSignal).filter_by(change_id=change.id).first()
        if signal is None:
            signal = WatchSignal(change_id=change.id, client_id=client.id, competitor_id=change.competitor_id,
                                 captured_at=snap.captured_at if snap else datetime.utcnow(), source_url=source.url)
            db.add(signal)
        signal.type, signal.theme = item.type.lower()[:30], item.theme[:120]
        signal.title, signal.meaning, signal.claims = item.title[:300], item.meaning, item.claims
        db.flush()
        rival = db.get(WatchCompetitor, change.competitor_id) if change.competitor_id else None
        tier = 'client' if change.competitor_id is None else (rival.tier if rival else 'emerging')
        value, note = adjust(signal.type, tier, item.score, source.kind == 'ads')
        if source.kind == 'ads':
            signal.type = 'ad'
        score = db.get(WatchScore, signal.id)
        if score is None:
            score = WatchScore(signal_id=signal.id, score=value)
            db.add(score)
        score.score, score.model = value, body.model[:100]
        score.reason = (f'{item.reason} ({note})' if item.reason else note)[:600] if note else item.reason
        change.status = 'signalled'
        holder = 'client' if change.competitor_id is None else str(change.competitor_id)
        for label in item.claims:
            upsert_claim(db, client.id, label, holder, (change.after or '')[:300], source.url)
        saved += 1
    visit.status = 'done'
    visit.error = ('Some results were refused: ' + '; '.join(rejected[:6])) if rejected else None
    db.commit()
    run_alerts(db, client)
    return {'saved': saved, 'rejected': rejected}


@n8n.post('/visits/{visit_id}/fail', dependencies=[Depends(n8n_only)])
def visit_failed(visit_id: int, body: Failure, db: Session = Depends(get_db)):
    visit = get_or_404(db, WatchVisit, visit_id, 'Visit')
    visit.status, visit.error = 'failed', body.error
    db.commit()
    return {'visit_id': visit_id, 'status': 'failed'}


def week_signals(db, client, week_start):
    start = datetime.fromisoformat(week_start) - timedelta(days=7)
    rows = signals_query(db, client.id).filter(WatchSignal.created_at >= start).all()
    return [(s, sc, ch) for s, sc, ch in rows if (effective_score(sc) or 0) >= 3]


@n8n.get('/briefs/{brief_id}/pack', dependencies=[Depends(n8n_only)])
def brief_pack(brief_id: int, db: Session = Depends(get_db)):
    brief = get_or_404(db, WatchBrief, brief_id, 'Brief')
    client = db.get(WatchClient, brief.client_id)
    names = names_of(db, client.id)
    rows = week_signals(db, client, brief.week_start)
    rows.sort(key=lambda r: effective_score(r[1]) or 0, reverse=True)
    signals = '\n'.join(f'[{s.id}] score {effective_score(sc)} · {names.get(s.competitor_id, "You") if s.competitor_id else "You"}'
                        f' · {s.type} · {s.title}. Means: {s.meaning}' for s, sc, _ in rows[:25]) or 'none'
    gaps = content_gaps(db, client)
    claims = claim_map(db, client)
    data = latest(db, client.id)
    texts = []
    for c in companies(db, client):
        snaps = data.get(c['key'], {})
        parts = []
        home = snaps.get('page:homepage')
        if home:
            f = home['snapshot'].fields or {}
            parts.append('Headline: ' + (f.get('headline') or '') + '. Headings: ' + '; '.join((f.get('headings') or [])[:15]))
        ads = snaps.get('ads')
        if ads:
            parts.append('Ads: ' + ' | '.join(f"{a.get('headline')} {a.get('body')}"[:200] for a in (ads['snapshot'].items or [])
                                             if a.get('active'))[:1200])
        for k in ('instagram', 'linkedin', 'facebook'):
            if k in snaps and (snaps[k]['snapshot'].metrics or {}).get('bio'):
                parts.append(f"{k} bio: {snaps[k]['snapshot'].metrics['bio'][:300]}")
        if parts:
            texts.append(f"[{c['key']}] {c['name']}: " + ' '.join(parts)[:2000])
    previous = [o.angle for o in db.query(WatchOpportunity).filter_by(client_id=client.id)
                .order_by(WatchOpportunity.id.desc()).limit(10)]
    gap_text = '\n'.join(f"[gap:{i + 1}] {g['label']}: {g['detail']} Rivals: {', '.join(g['rivals'])}"
                         for i, g in enumerate(gaps)) or 'none'
    claim_text = '\n'.join(f"[claim:{c['id']}] {c['label']}: {c['status']}, {c['rival_count']} rivals, "
                           f"client {'claims it' if c['client_claims'] else 'does not claim it'}" for c in claims) or 'none'
    return {'brief_id': brief.id, 'week_start': brief.week_start, 'today': date.today().isoformat(),
            'profile': profile_text(client), 'signal_count': len(rows), 'signals': signals, 'gaps': gap_text,
            'claim_map': claim_text, 'company_texts': '\n'.join(texts) or 'none',
            'starter_claims': ', '.join(STARTER_CLAIMS), 'previous_opportunities': '; '.join(previous) or 'none'}


@n8n.post('/briefs/{brief_id}/result', dependencies=[Depends(n8n_only)])
def save_brief(brief_id: int, body: BriefResult, db: Session = Depends(get_db)):
    brief = get_or_404(db, WatchBrief, brief_id, 'Brief')
    client = db.get(WatchClient, brief.client_id)
    names = names_of(db, client.id)
    allowed = {s.id: (s, sc, ch) for s, sc, ch in week_signals(db, client, brief.week_start)}
    errors, items = [], []
    for it in body.items[:7]:
        if it.signal_id not in allowed:
            errors.append(f'Item {it.signal_id} is not one of this week\'s signals scoring 3 or more.')
            continue
        s, sc, _ = allowed[it.signal_id]
        if any(x['signal_id'] == s.id for x in items):
            continue
        items.append({'signal_id': s.id, 'score': effective_score(sc), 'type': s.type, 'title': s.title, 'meaning': s.meaning,
                      'move': it.move, 'source_url': s.source_url, 'captured_at': s.captured_at.isoformat(),
                      'competitor': names.get(s.competitor_id, 'You') if s.competitor_id else 'You'})
    items.sort(key=lambda x: x['score'], reverse=True)
    quiet = not items
    # Never padded: a quiet week is only accepted when there really were no signals scoring 3 or more.
    if quiet and allowed:
        brief.status, brief.error = 'failed', 'The brief had no valid items although this week has signals. ' + ' '.join(errors[:3])
        db.commit()
        raise HTTPException(422, {'errors': [brief.error]})
    brief.items, brief.quiet = items, quiet
    brief.headline = (body.headline.strip() or ('Quiet week' if quiet else items[0]['title']))[:300]
    for c in body.claims:
        key = c.company if c.company == 'client' or c.company.isdigit() else None
        if key and (key == 'client' or int(key) in names):
            upsert_claim(db, client.id, c.label, key, c.quote, '')
    gap_count = len(content_gaps(db, client))
    claim_ids = {str(c.id) for c in db.query(WatchClaim).filter_by(client_id=client.id)}
    signal_ids = {str(i) for i, in db.query(WatchSignal.id).filter(WatchSignal.client_id == client.id)}
    db.query(WatchOpportunity).filter_by(client_id=client.id, week_start=brief.week_start, status='new').delete()
    kept, dropped = 0, []
    for o in sorted(body.opportunities, key=lambda o: o.rank):
        problem = None
        try:
            expires = date.fromisoformat(o.expires_on)
        except ValueError:
            expires, problem = None, 'no valid expiry date'
        if expires and expires < date.today():
            problem = 'already expired'
        empty = [f for f in ('angle', 'trigger', 'claim', 'audience', 'why_now', 'competitors_saying', 'wrong_if')
                 if not getattr(o, f).strip()]
        if empty:
            problem = 'missing ' + ', '.join(empty)
        evidence = []
        for ref in o.evidence:
            ref = ref.strip().lower()
            if (ref.isdigit() and ref in signal_ids) or (ref.startswith('claim:') and ref[6:] in claim_ids) or \
                    (ref.startswith('gap:') and ref[4:].isdigit() and 1 <= int(ref[4:]) <= gap_count):
                evidence.append(ref)
        if not evidence:
            problem = problem or 'no evidence that exists in Radar'
        if o.confidence.lower() not in ('high', 'medium', 'low'):
            problem = problem or 'confidence must be high, medium or low'
        if problem:
            dropped.append(f'#{o.rank} {o.angle[:60]}: {problem}')
            continue
        kept += 1
        db.add(WatchOpportunity(client_id=client.id, week_start=brief.week_start, rank=kept, angle=o.angle, trigger=o.trigger,
                                claim=o.claim, audience=o.audience, why_now=o.why_now,
                                competitors_saying=o.competitors_saying, wrong_if=o.wrong_if,
                                confidence=o.confidence.lower(), expires_on=o.expires_on, evidence=evidence))
    brief.status = 'ready'
    brief.error = ('Opportunities refused: ' + '; '.join(dropped[:5])) if dropped else None
    db.commit()
    return {'brief_id': brief.id, 'items': len(items), 'quiet': quiet, 'opportunities': kept, 'refused': dropped}


@n8n.post('/briefs/{brief_id}/fail', dependencies=[Depends(n8n_only)])
def brief_failed(brief_id: int, body: Failure, db: Session = Depends(get_db)):
    brief = get_or_404(db, WatchBrief, brief_id, 'Brief')
    brief.status, brief.error = 'failed', body.error
    db.commit()
    return {'brief_id': brief_id, 'status': 'failed'}
