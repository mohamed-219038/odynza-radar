"""The watch engine: which sources exist per competitor, when each is due, and one visit = collect → snapshot →
detect change → dedupe → hand the new changes to n8n. No AI here."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from api.watch import collect
from api.watch.collect import CollectError
from api.watch.fields import (ad_changes, content_hash, fingerprint, mention_changes, page_changes, propose_pages,
                               social_changes)
from api.watch import pictures
from db.database import SessionLocal
from db.watch_models import (WatchChange, WatchClient, WatchCompetitor, WatchSnapshot, WatchSource, WatchState,
                             WatchVisit)

# Days between visits, by tier and source kind (design 3.4). None = not watched for that tier.
CADENCE = {
    'direct':       {'page': 1, 'instagram': 1, 'facebook': 7, 'linkedin': 7, 'ads': 7, 'web': 3.5},
    'adjacent':     {'page': 3.5, 'instagram': 3.5, 'facebook': 7, 'linkedin': 7, 'ads': 7, 'web': 7},
    'aspirational': {'page': 7, 'instagram': 7, 'facebook': 7, 'linkedin': 7, 'ads': None, 'web': 7},
    'emerging':     {'page': 7, 'instagram': 7, 'facebook': None, 'linkedin': None, 'ads': None, 'web': 7},
    'client':       {'page': 7, 'instagram': 1, 'facebook': 7, 'linkedin': 7, 'ads': None, 'web': 7},
}
APIFY_KINDS = {'facebook', 'linkedin', 'ads'}
_visit_lock = asyncio.Lock()


def app_url() -> str:
    return (os.getenv('RADAR_CALLBACK_URL') or '').strip().rstrip('/') or 'http://127.0.0.1:8000'


def company_name(db: Session, source: WatchSource) -> str:
    if source.competitor_id is None:
        client = db.get(WatchClient, source.client_id)
        return client.name if client else ''
    comp = db.get(WatchCompetitor, source.competitor_id)
    return comp.name if comp else ''


def tier_of(source: WatchSource, db: Session) -> str:
    if source.competitor_id is None:
        return 'client'
    competitor = db.get(WatchCompetitor, source.competitor_id)
    return competitor.tier if competitor else 'direct'


def interval(tier: str, kind: str) -> timedelta | None:
    days = CADENCE.get(tier, CADENCE['direct']).get(kind)
    if days is None:
        return None
    if kind == 'instagram' and not collect.meta_ready():
        days = max(days, 7)   # without Meta, Instagram goes through paid Apify runs: weekly at most
    return timedelta(days=days)


# ---- Apify budget -----------------------------------------------------------------------------

def month_key(now=None):
    return 'apify:' + (now or datetime.utcnow()).strftime('%Y-%m')


def budget(db: Session) -> dict:
    limit = float(os.getenv('WATCH_APIFY_MONTHLY_USD', '5') or 5)
    row = db.get(WatchState, month_key())
    spent = round(row.num or 0, 3) if row else 0.0
    return {'month': month_key()[6:], 'spent_usd': spent, 'limit_usd': limit, 'paused': spent >= 0.9 * limit,
            'per_run_usd': float(os.getenv('WATCH_APIFY_MAX_USD_PER_RUN', '0.25') or 0.25)}


def add_spend(db: Session, usd: float):
    if usd <= 0:
        return
    row = db.get(WatchState, month_key())
    if row is None:
        row = WatchState(key=month_key(), num=0.0)
        db.add(row)
    row.num = (row.num or 0) + usd
    db.commit()


# ---- Sources ---------------------------------------------------------------------------------

def add_source(db, client_id, competitor_id, kind, url, page_kind=None) -> WatchSource | None:
    url = (url or '').strip()
    if not url:
        return None
    existing = db.query(WatchSource).filter_by(client_id=client_id, competitor_id=competitor_id, kind=kind, url=url).first()
    if existing:
        return existing
    row = WatchSource(client_id=client_id, competitor_id=competitor_id, kind=kind, url=url, page_kind=page_kind,
                      next_run_at=datetime.utcnow())
    db.add(row)
    db.flush()
    return row


async def setup_sources(db: Session, client: WatchClient, competitor: WatchCompetitor | None) -> list[WatchSource]:
    """Proposes pages from the homepage links and adds the social accounts and ad library the tier watches."""
    tier = competitor.tier if competitor else 'client'
    website = competitor.website if competitor else client.website
    socials = (competitor.socials if competitor else client.socials) or {}
    cid = competitor.id if competitor else None
    rows = []
    if website:
        pages = [{'page_kind': 'homepage', 'url': website.rstrip('/')}]
        if tier != 'emerging':
            try:
                loaded = await collect.load_pages([website])
            except Exception as exc:   # no browser installed: watch the homepage; pages can be added by hand
                logger.warning(f'[watch] could not read {website} to propose pages: {type(exc).__name__}')
                loaded = {}
            html = loaded.get(website)
            if isinstance(html, str):
                pages = propose_pages(html, website, tier)
        for p in pages:
            rows.append(add_source(db, client.id, cid, 'page', p['url'], p['page_kind']))
        if interval(tier, 'web'):
            rows.append(add_source(db, client.id, cid, 'web', website.rstrip('/')))   # web and news mentions (Serper)
    for kind in ('instagram', 'facebook', 'linkedin'):
        if socials.get(kind) and interval(tier, kind):
            rows.append(add_source(db, client.id, cid, kind, socials[kind]))
    if socials.get('facebook') and interval(tier, 'ads'):
        rows.append(add_source(db, client.id, cid, 'ads', socials['facebook']))
    db.commit()
    return [r for r in rows if r]


def due_sources(db: Session, now: datetime | None = None) -> list[WatchSource]:
    now = now or datetime.utcnow()
    rows = (db.query(WatchSource).filter(WatchSource.enabled.is_(True))
            .filter((WatchSource.next_run_at.is_(None)) | (WatchSource.next_run_at <= now)).all())
    out = []
    for s in rows:
        if s.competitor_id is not None:
            comp = db.get(WatchCompetitor, s.competitor_id)
            if comp is None or comp.status != 'confirmed':   # a human confirms first
                continue
        if interval(tier_of(s, db), s.kind) is None:
            continue
        out.append(s)
    return out


# ---- One visit ---------------------------------------------------------------------------------

def last_snapshot(db, source_id):
    return db.query(WatchSnapshot).filter_by(source_id=source_id).order_by(WatchSnapshot.captured_at.desc(),
                                                                           WatchSnapshot.id.desc()).first()


def detect(source: WatchSource, old: WatchSnapshot | None, new: dict) -> list[dict]:
    if old is None:
        return []   # the first capture is the baseline
    before = {'text': old.text, 'fields': old.fields, 'metrics': old.metrics, 'items': old.items}
    if source.kind == 'page':
        return page_changes(before, new)
    if source.kind == 'ads':
        if any('page_name' not in a for a in old.items or []):
            return []   # captured before ads were checked against the page: start a fresh baseline
        return ad_changes(before, new)
    if source.kind == 'web':
        return mention_changes(before, new)
    return social_changes(before, new)


def store(db: Session, visit: WatchVisit, source: WatchSource, data: dict) -> tuple[WatchSnapshot, list[WatchChange]]:
    old = last_snapshot(db, source.id)
    digest = content_hash(data['text'], data['fields'], data['metrics'], data['items'])
    found = detect(source, old, data)
    if old is not None and old.content_hash == digest and not found:
        # Counters move every day and picture links are refreshed (or newly found); the content itself is unchanged.
        old.metrics, old.items = data['metrics'], data['items']
        return old, []
    snap = WatchSnapshot(source_id=source.id, content_hash=digest, text=data['text'], fields=data['fields'],
                         metrics=data['metrics'], items=data['items'])
    db.add(snap)
    db.flush()
    changes = []
    recent = datetime.utcnow() - timedelta(days=30)
    for c in found:
        fp = fingerprint(source.competitor_id, c['field'], c['kind'], c['before'], c['after'])
        seen = (db.query(WatchChange.id).filter(WatchChange.fingerprint == fp, WatchChange.created_at >= recent)
                .filter(WatchChange.competitor_id.is_(None) if source.competitor_id is None
                        else WatchChange.competitor_id == source.competitor_id).first())
        row = WatchChange(visit_id=visit.id, source_id=source.id, competitor_id=source.competitor_id, field=c['field'][:200],
                          kind=c['kind'], before=c['before'], after=c['after'], before_snapshot_id=old.id if old else None,
                          after_snapshot_id=snap.id, fingerprint=fp, status='duplicate' if seen else 'new')
        if c.get('delta_pct') is not None:
            row.after = f"{row.after} ({c['delta_pct']:+g}%)"
        db.add(row)
        changes.append(row)
    db.flush()
    return snap, changes


async def collect_source(source: WatchSource, html: str | Exception | None, apify: collect.Apify, max_usd: float,
                         name: str = '') -> dict:
    if source.kind == 'page':
        if isinstance(html, Exception):
            raise html
        if html is None:
            raise CollectError('The page was not loaded.')
        return collect.page_snapshot(html, source.url, source.page_kind or 'homepage')
    if source.kind == 'instagram':
        return await collect.instagram(source.url, apify, max_usd)
    if source.kind == 'facebook':
        return await collect.facebook(source.url, apify, max_usd)
    if source.kind == 'linkedin':
        return await collect.linkedin(source.url, apify, max_usd)
    if source.kind == 'ads':
        return await collect.ads(source.url, apify, max_usd, name)
    if source.kind == 'web':
        return await collect.web_mentions(name, source.url)
    raise CollectError(f'Unknown source kind {source.kind}.')


async def run_visit(source_ids: list[int], trigger: str = 'schedule', notify=True) -> int | None:
    """Collects the given sources one after the other (pages share one browser). Returns the visit id."""
    async with _visit_lock:
        with SessionLocal() as db:
            sources = [s for s in (db.get(WatchSource, i) for i in source_ids) if s is not None and s.enabled]
            if not sources:
                return None
            visit = WatchVisit(client_id=sources[0].client_id, trigger=trigger, source_ids=[s.id for s in sources])
            db.add(visit)
            db.commit()
            pages = [s.url for s in sources if s.kind == 'page']
            try:
                html = await collect.load_pages(pages) if pages else {}
            except Exception as exc:  # Playwright not installed, browser crash
                logger.exception('Watch page loading failed')
                html = {u: CollectError(f'The browser could not start ({type(exc).__name__}). Run '
                                        '`python -m playwright install chromium` once.') for u in pages}
            report, total_new, picture_links = {}, 0, []
            apify = collect.Apify()
            for s in sources:
                now = datetime.utcnow()
                s.last_run_at = now
                step = interval(tier_of(s, db), s.kind) or timedelta(days=7)
                entry = {'kind': s.kind, 'url': s.url}
                try:
                    money = budget(db)
                    if s.kind in APIFY_KINDS or (s.kind == 'instagram' and not collect.meta_ready()):
                        if money['paused']:
                            raise CollectError(f"Apify spending this month reached ${money['spent_usd']:.2f} of "
                                               f"${money['limit_usd']:.0f}, so Apify sources wait for next month.")
                    data = await collect_source(s, html.get(s.url), apify, money['per_run_usd'], company_name(db, s))
                    if s.kind == 'page' and (shot := collect.SHOTS.pop(s.url, None)):
                        data['metrics']['screenshot'] = pictures.keep_shot(s.url, shot, now)
                    add_spend(db, data.get('cost') or 0)
                    snap, changes = store(db, visit, s, data)
                    picture_links += pictures.links_of(data['metrics'], data['items'])
                    fresh = [c for c in changes if c.status == 'new']
                    total_new += len(fresh)
                    entry.update(items=len(data['items']) or None, changes=len(fresh), cost=round(data.get('cost') or 0, 3),
                                 snapshot_id=snap.id)
                    s.last_success_at, s.last_error, s.fail_count = now, None, 0
                    s.next_run_at = now + step
                except CollectError as exc:
                    entry['error'] = str(exc)
                    s.last_error, s.fail_count = str(exc)[:1000], (s.fail_count or 0) + 1
                    s.next_run_at = now + min(step, timedelta(hours=6 * s.fail_count))
                except Exception as exc:
                    logger.exception(f'Watch source {s.id} failed')
                    entry['error'] = f'Unexpected error ({type(exc).__name__}). Details are in the server log.'
                    s.last_error, s.fail_count = entry['error'], (s.fail_count or 0) + 1
                    s.next_run_at = now + min(step, timedelta(hours=6 * s.fail_count))
                report[str(s.id)] = entry
                visit.report = dict(report)   # saved as it goes, so the screen can show "5 of 21 done"
                db.commit()
            visit.report = report
            visit.finished_at = datetime.utcnow()
            visit.status = 'scoring' if total_new else 'done'
            if all('error' in e for e in report.values()):
                visit.status, visit.error = 'failed', 'Every source in this visit failed. See Source health.'
            db.commit()
            visit_id = visit.id
    await pictures.save(picture_links)   # kept on this computer: platform picture links expire
    with SessionLocal() as db:
        pictures.build_library(db)   # and as normal files under data/pictures/library/<company>/<platform>/
    if notify and total_new:
        await send_to_n8n(visit_id)
    return visit_id


async def send_to_n8n(visit_id: int, mode: str = 'changes') -> str | None:
    """Starts the n8n "M0 Signals" workflow for one visit. Returns an error message, or None when n8n accepted it."""
    hook = (os.getenv('N8N_SIGNALS_WEBHOOK_URL') or '').strip() or 'http://localhost:5678/webhook/radar-signals'
    error = None
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            r = await client.post(hook, json={'visit_id': visit_id, 'mode': mode, 'app_base_url': app_url()})
        if r.status_code >= 400:
            error = (f'n8n answered HTTP {r.status_code}.' + (' Publish (activate) the "Odynza Radar Signals" workflow.'
                                                               if r.status_code == 404 else ''))
    except httpx.HTTPError:
        error = f'Could not reach n8n at {hook}. Start n8n; the changes are kept and can be sent again.'
    if error:
        with SessionLocal() as db:
            visit = db.get(WatchVisit, visit_id)
            if visit:
                visit.status, visit.error = 'failed', error
                db.commit()
        logger.warning(f'[watch] visit {visit_id}: {error}')
    return error
