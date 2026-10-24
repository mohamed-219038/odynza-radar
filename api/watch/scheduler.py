"""Runs inside the Radar server (no extra service): every minute it collects what is due, starts the weekly brief on Sunday
night, emails it on Monday 08:00 Cairo time and catches up on anything missed while the PC was off."""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import httpx
from loguru import logger

from api.watch import engine
from api.watch.brief import brief_pdf, email_ready, send_brief_email
from api.watch.insight import week_snapshot
from api.watch.insight import run_alerts
from db.database import SessionLocal
from db.watch_models import WatchBrief, WatchClient, WatchOpportunity, WatchVisit

CAIRO = timezone(timedelta(hours=int(os.getenv('WATCH_UTC_OFFSET_HOURS', '3') or 3)))
TICK_SECONDS = 60
_task: asyncio.Task | None = None


def cairo_now() -> datetime:
    return datetime.now(CAIRO)


def brief_week(now: datetime | None = None) -> str:
    """The Monday a brief is sent on. From Sunday 22:00 the coming Monday's brief is due."""
    now = (now or cairo_now()) + timedelta(hours=2)
    day = now.date()
    return (day - timedelta(days=day.weekday())).isoformat()


async def start_weekly(client_id: int, week_start: str, force=False) -> tuple[int | None, str | None]:
    """Creates the brief row and asks n8n for the brief, claims and opportunities. Returns (brief id, error)."""
    with SessionLocal() as db:
        client = db.get(WatchClient, client_id)
        if client is None:
            return None, 'No client profile yet.'
        run_alerts(db, client)
        brief = db.query(WatchBrief).filter_by(client_id=client_id, week_start=week_start).first()
        if brief and brief.status in ('running', 'ready') and not force:
            return brief.id, None
        if brief is None:
            brief = WatchBrief(client_id=client_id, week_start=week_start)
            db.add(brief)
        brief.status, brief.error = 'running', None
        db.commit()
        brief_id = brief.id
    hook = (os.getenv('N8N_WEEKLY_WEBHOOK_URL') or '').strip() or 'http://localhost:5678/webhook/radar-weekly'
    error = None
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            r = await client.post(hook, json={'brief_id': brief_id, 'client_id': client_id, 'week_start': week_start,
                                              'app_base_url': engine.app_url()})
        if r.status_code >= 400:
            error = f'n8n answered HTTP {r.status_code}.' + (' Publish (activate) the "Odynza Radar Signals" workflow.'
                                                              if r.status_code == 404 else '')
    except httpx.HTTPError:
        error = f'Could not reach n8n at {hook}. Start n8n, then use "Make brief now".'
    if error:
        with SessionLocal() as db:
            row = db.get(WatchBrief, brief_id)
            row.status, row.error = 'failed', error
            db.commit()
    return brief_id, error


async def email_brief(brief_id: int) -> str | None:
    with SessionLocal() as db:
        brief = db.get(WatchBrief, brief_id)
        client = db.get(WatchClient, brief.client_id) if brief else None
        if brief is None or client is None or brief.status != 'ready':
            return 'Only a finished brief can be emailed.'
        data = {'week_start': brief.week_start, 'headline': brief.headline, 'items': brief.items, 'quiet': brief.quiet}
        name, recipients = client.name, list(client.brief_emails or [])
        snap = week_snapshot(db, client)
    try:
        try:
            pdf = await brief_pdf(name, data, snap)
        except Exception:   # no Chromium: still send the email, without the attachment
            logger.warning('[watch] brief PDF could not be made; sending the email without it')
            pdf = None
        await asyncio.to_thread(send_brief_email, name, data, pdf, recipients, snap)
        error = None
    except RuntimeError as exc:
        error = str(exc)
    with SessionLocal() as db:
        brief = db.get(WatchBrief, brief_id)
        brief.email_error = error
        if not error:
            brief.emailed_at = datetime.utcnow()
        db.commit()
    return error


async def tick(now: datetime | None = None):
    now = now or cairo_now()
    with SessionLocal() as db:
        due = [s.id for s in engine.due_sources(db)][:40]
        clients = [c.id for c in db.query(WatchClient).all()]
        stale = datetime.utcnow() - timedelta(minutes=30)
        for v in db.query(WatchVisit).filter(WatchVisit.status == 'scoring', WatchVisit.updated_at < stale):
            v.status, v.error = 'failed', 'n8n did not send the scores back. Open the latest n8n execution to see which node stopped.'
        for b in db.query(WatchBrief).filter(WatchBrief.status == 'running', WatchBrief.updated_at < stale):
            b.status, b.error = 'failed', 'n8n did not send the brief back. Open the latest n8n execution to see which node stopped.'
        today = date.today().isoformat()
        for o in db.query(WatchOpportunity).filter(WatchOpportunity.status.in_(('new', 'accepted')),
                                                   WatchOpportunity.expires_on < today):
            o.status = 'expired'
        db.commit()
    if due:
        await engine.run_visit(due, 'schedule')
    week = brief_week(now)
    monday_8 = datetime.fromisoformat(week).replace(hour=8, tzinfo=CAIRO)
    for client_id in clients:
        with SessionLocal() as db:
            brief = db.query(WatchBrief).filter_by(client_id=client_id, week_start=week).first()
            brief_id = brief.id if brief else None
            state = (brief.status, brief.emailed_at, brief.email_error) if brief else None
        if state is None:
            await start_weekly(client_id, week)
        elif state[0] == 'ready' and not state[1] and not state[2] and now >= monday_8 and email_ready():
            await email_brief(brief_id)


async def loop():
    await asyncio.sleep(5)   # let the app finish starting
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('[watch] scheduler tick failed')
        await asyncio.sleep(TICK_SECONDS)


def start():
    global _task
    if os.getenv('WATCH_SCHEDULER', '1').strip() in ('0', 'false', 'off', 'no'):
        logger.info('[watch] scheduler is off (WATCH_SCHEDULER=0)')
        return
    _task = asyncio.create_task(loop())
    logger.info('[watch] scheduler started')


async def stop():
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
