"""M1 Strategy: New plan defaults, starting the n8n "Odynza Radar Strategy" workflow, the pack it reads,
campaign key visuals (FLUX) and the Results tab (ad numbers typed by hand). Reading, deleting and the n8n
callbacks for a plan are in api/routers/strategy.py.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.content_media import UPLOAD_TYPES, image_maker, plain_image_error, sniff
from api.routers.strategy import callback_allowed, get_plan, serialize
from api.routers.watch import pick_client, staff, the_client
from api.security import AuthUser, env_int, lookup_session, rate_limit, require_user
from api.strategy_plan import (LANGUAGE, PLATFORMS, RadarPlanRequest, ResultIn, defaults, radar_pack,
                                results_report)
from db.database import StrategyPlan, StrategyResult, get_db
from db.watch_models import WatchClient, WatchCompetitor

router = APIRouter()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def radar_plan(db, plan_id) -> StrategyPlan:
    plan = get_plan(db, plan_id)
    if (plan.inputs or {}).get('version') != 2:
        raise HTTPException(409, 'This plan was made by an older version and cannot be opened here.')
    return plan


def owned(db, plan: StrategyPlan):
    """A plan of another Radar client is hidden, as Watch rows are."""
    wanted = db.info.get('watch_client')
    if wanted is not None and (plan.inputs or {}).get('client_id') != wanted:
        raise HTTPException(404, 'Strategy plan not found')
    return plan


@router.get('/radar/defaults', dependencies=[Depends(pick_client), Depends(staff)])
def radar_defaults(db: Session = Depends(get_db)):
    return defaults(db, the_client(db))


@router.get('/radar/plans', dependencies=[Depends(pick_client), Depends(staff)])
def radar_plans(db: Session = Depends(get_db)):
    client = the_client(db)
    rows = (db.query(StrategyPlan).filter(StrategyPlan.company_id == f'watch:{client.id}')
            .order_by(StrategyPlan.created_at.desc()).limit(100).all())
    from api.routers.strategy import expire_stale
    expire_stale(db, rows)
    return [{**serialize(r), 'version': 2, 'goal': (r.inputs or {}).get('goal'),
             'summary': ((r.plan or {}).get('overview') or {}).get('summary', '')} for r in rows]


async def start_radar_plan(db: Session, request: Request, client: WatchClient, body: RadarPlanRequest) -> dict:
    inputs = body.model_dump(mode='json')
    inputs['voices'] = {p: {'key': v.key, 'label': v.describe()[0], 'style': v.describe()[1],
                            'language': LANGUAGE[p]} for p, v in body.voices.items()}
    inputs.update(version=2, client_id=client.id, budget_total=body.total_budget(),
                  channels=list(PLATFORMS) + list(body.paid))
    plan = StrategyPlan(session_id='', company_id=f'watch:{client.id}', company_name=client.name,
                        inputs=inputs)
    db.add(plan)
    db.commit()
    webhook = os.getenv('N8N_STRATEGY_WEBHOOK_URL', '').strip() or 'http://localhost:5678/webhook/radar-strategy'
    app_url = os.getenv('RADAR_CALLBACK_URL', '').strip() or str(request.base_url).rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
            response = await http.post(webhook, json={'plan_id': plan.id, 'app_base_url': app_url, 'version': 2})
        if response.status_code >= 400:
            hint = (' The workflow is not active: in n8n open "Odynza Radar Strategy" and click Publish.'
                    if response.status_code == 404 else '')
            raise RuntimeError(f'n8n answered HTTP {response.status_code}.{hint}')
    except (httpx.HTTPError, RuntimeError) as exc:
        plan.status = 'failed'
        plan.error = (str(exc) if isinstance(exc, RuntimeError) else
                      f'Could not reach n8n at {webhook}. Start n8n and check N8N_STRATEGY_WEBHOOK_URL in .env.')
        db.commit()
        raise HTTPException(502, plan.error) from None
    plan.status = 'running'
    db.commit()
    return {**serialize(plan), 'version': 2}


@router.post('/radar/plans', status_code=202,
             dependencies=[Depends(pick_client), Depends(rate_limit('plans', env_int('LIMIT_PLANS_PER_HOUR', 12), 3600))])
async def create_radar_plan(body: RadarPlanRequest, request: Request, user: AuthUser = Depends(staff),
                            db: Session = Depends(get_db)):
    return await start_radar_plan(db, request, the_client(db), body)


@router.get('/plans/{plan_id}/pack')
def plan_pack(plan_id: str, request: Request, db: Session = Depends(get_db),
              x_radar_token: str | None = Header(default=None)):
    """What n8n reads for a Radar plan: only while the plan is being written, or for a signed-in user."""
    plan = radar_plan(db, plan_id)
    if lookup_session(db, request) is None:
        if plan.status not in ('queued', 'running'):
            raise HTTPException(401, 'Sign in to continue.')
        callback_allowed(request, x_radar_token)
    try:
        return radar_pack(db, {**plan.inputs, 'plan_id': plan.id})
    except LookupError as exc:
        return {'ready': False, 'message': str(exc)}


# ---- Campaign key visuals ------------------------------------------------------------------------------

def visual_path(plan_id: str, campaign_id: str, ext: str | None = None):
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', plan_id) or not re.fullmatch(r'[A-Za-z0-9_-]{1,12}', campaign_id):
        raise HTTPException(404, 'Not found')
    folder = os.path.join(ROOT, 'data', 'strategy', plan_id)
    if ext:
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f'{campaign_id}.{ext}')
    for e in UPLOAD_TYPES['image'].values():
        path = os.path.join(folder, f'{campaign_id}.{e}')
        if os.path.exists(path):
            return path
    return None


async def own_pictures(db: Session, client_id: int) -> list[tuple[bytes, str]]:
    """Up to two of the client's own post pictures, so the key visual matches the brand."""
    from api.watch import pictures
    from api.watch.insight import latest
    found = []
    for kind in ('instagram', 'facebook', 'linkedin'):
        snap = (latest(db, client_id).get('client', {}).get(kind) or {}).get('snapshot')
        items = sorted(snap.items or [], key=lambda p: -(p.get('engagement_total') or 0)) if snap else []
        for item in items:
            for url in (item.get('images') or [])[:1]:
                try:
                    found.append(await pictures.get(url))
                except Exception:
                    continue
            if len(found) >= 2:
                return found
    return found


@router.post('/plans/{plan_id}/visuals/{campaign_id}',
             dependencies=[Depends(pick_client), Depends(rate_limit('visuals', env_int('LIMIT_VISUALS_PER_HOUR', 20), 3600))])
async def make_visual(plan_id: str, campaign_id: str, user: AuthUser = Depends(staff), db: Session = Depends(get_db)):
    plan = owned(db, radar_plan(db, plan_id))
    campaign = next((c for c in (plan.plan or {}).get('campaigns') or [] if c.get('id') == campaign_id), None)
    if campaign is None:
        raise HTTPException(404, 'Campaign not found in this plan.')
    prompt = (campaign.get('visual_prompt') or f"Key visual for the campaign {campaign.get('name')}: {campaign.get('idea')}")
    prompt += (f" Brand: {plan.company_name}. Clean premium tech look, one strong focal subject, room for a headline. "
               'No text in the picture, no logos of other companies.')
    try:
        maker = image_maker()
        data, mime = await maker.make(prompt, '4:5',
                                      await own_pictures(db, plan.inputs['client_id']))
    except Exception as exc:
        raise HTTPException(502, plain_image_error(exc)) from None
    old = visual_path(plan_id, campaign_id)
    if old:
        os.remove(old)
    with open(visual_path(plan_id, campaign_id, UPLOAD_TYPES['image'][mime]), 'wb') as f:
        f.write(data)
    return {'campaign_id': campaign_id, 'ready': True}


@router.put('/plans/{plan_id}/visuals/{campaign_id}', dependencies=[Depends(pick_client)])
async def upload_visual(plan_id: str, campaign_id: str, request: Request, user: AuthUser = Depends(staff),
                        db: Session = Depends(get_db)):
    owned(db, radar_plan(db, plan_id))
    data = await request.body()
    mime = sniff(data, 'image') if data else None
    if not mime or len(data) > 15 * 1024 * 1024:
        raise HTTPException(400, 'Upload a PNG, JPEG or WebP picture under 15 MB.')
    old = visual_path(plan_id, campaign_id)
    if old:
        os.remove(old)
    with open(visual_path(plan_id, campaign_id, UPLOAD_TYPES['image'][mime]), 'wb') as f:
        f.write(data)
    return {'campaign_id': campaign_id, 'ready': True}


@router.get('/plans/{plan_id}/visuals/{campaign_id}', dependencies=[Depends(require_user)])
def read_visual(plan_id: str, campaign_id: str):
    path = visual_path(plan_id, campaign_id)
    if not path:
        raise HTTPException(404, 'No key visual yet.')
    with open(path, 'rb') as f:
        data = f.read()
    return Response(data, media_type=sniff(data, 'image') or 'image/png',
                    headers={'Cache-Control': 'private, no-cache', 'X-Content-Type-Options': 'nosniff'})


def visuals_of(plan: StrategyPlan) -> list[str]:
    return [c['id'] for c in (plan.plan or {}).get('campaigns') or [] if visual_path(plan.id, c['id'])]


@router.get('/radar/plans/{plan_id}', dependencies=[Depends(pick_client), Depends(require_user)])
def read_radar_plan(plan_id: str, db: Session = Depends(get_db)):
    from api.routers.strategy import expire_stale
    plan = owned(db, radar_plan(db, plan_id))
    expire_stale(db, [plan])
    return {**serialize(plan, full=True), 'version': 2, 'visuals': visuals_of(plan), 'logos': logos_of(db, plan)}


def logos_of(db, plan: StrategyPlan) -> dict:
    """Company name -> the id /watch/logo/{id} serves, so rivals show their real logo instead of a letter."""
    client_id = (plan.inputs or {}).get('client_id')
    out = {plan.company_name: 'client'}
    for c in db.query(WatchCompetitor).filter_by(client_id=client_id).all():
        out[c.name] = c.id
    return out


# ---- Calendar edits -----------------------------------------------------------------------------------

class CalendarEdit(BaseModel):
    date: date
    end_date: date | None = None
    title: str = Field(min_length=1, max_length=200)
    kind: Literal['campaign', 'content', 'milestone', 'shopping', 'tech', 'holiday', 'season'] = 'content'
    campaign_id: str = Field(default='', max_length=12)
    channel: str = Field(default='', max_length=60)
    note: str = Field(default='', max_length=400)
    confirmed: bool = True
    source: str = Field(default='you', max_length=20)


class CalendarIn(BaseModel):
    entries: list[CalendarEdit] = Field(max_length=300)


@router.put('/radar/plans/{plan_id}/calendar', dependencies=[Depends(pick_client)])
def save_calendar(plan_id: str, body: CalendarIn, user: AuthUser = Depends(staff), db: Session = Depends(get_db)):
    """The Calendar tab saves the whole list after an add, edit or delete. Content batches made later read it."""
    plan = owned(db, radar_plan(db, plan_id))
    if plan.status != 'completed' or not plan.plan:
        raise HTTPException(409, 'Edit the calendar once the plan is ready.')
    start, end = date.fromisoformat(plan.inputs['start_date']), date.fromisoformat(plan.inputs['end_date'])
    ids = {c.get('id') for c in plan.plan.get('campaigns') or []}
    rows = []
    for e in body.entries:
        if not start <= e.date <= end:
            raise HTTPException(422, f'"{e.title}" is on {e.date}, outside the plan ({start} to {end}).')
        if e.end_date and e.end_date < e.date:
            raise HTTPException(422, f'"{e.title}" ends before it starts.')
        if e.campaign_id and e.campaign_id not in ids:
            raise HTTPException(422, f'Campaign {e.campaign_id} is not in this plan.')
        row = e.model_dump(mode='json')
        row['title'], row['note'] = row['title'].strip(), row['note'].strip()
        if row['end_date'] == row['date']:
            row['end_date'] = None
        rows.append(row)
    rows.sort(key=lambda r: (r['date'], r['title']))
    plan.plan = {**plan.plan, 'calendar': rows, 'calendar_edited': {'by': user.username, 'at': datetime.utcnow().isoformat()}}
    db.commit()
    return read_radar_plan(plan_id, db)


# ---- Results ------------------------------------------------------------------------------------------

def result_out(r: StrategyResult) -> dict:
    return {k: getattr(r, k) for k in ('id', 'week_start', 'platform', 'campaign_id', 'spend', 'impressions', 'clicks',
                                       'leads', 'notes', 'created_by', 'updated_at')}


def report_for(db, plan) -> dict:
    rows = db.query(StrategyResult).filter_by(plan_id=plan.id).order_by(StrategyResult.week_start).all()
    report = results_report(plan.plan or {}, plan.inputs or {}, rows, (plan.inputs or {}).get('currency', ''))
    report['entries'] = [result_out(r) for r in rows]
    return report


@router.get('/plans/{plan_id}/results', dependencies=[Depends(pick_client), Depends(require_user)])
def read_results(plan_id: str, db: Session = Depends(get_db)):
    return report_for(db, owned(db, radar_plan(db, plan_id)))


@router.post('/plans/{plan_id}/results', dependencies=[Depends(pick_client)])
def add_result(plan_id: str, body: ResultIn, user: AuthUser = Depends(staff), db: Session = Depends(get_db)):
    """One week of numbers for one platform and campaign. Typing the same week again replaces it."""
    plan = owned(db, radar_plan(db, plan_id))
    if plan.status != 'completed':
        raise HTTPException(409, 'Add results once the plan is ready.')
    ids = {c.get('id') for c in (plan.plan or {}).get('campaigns') or []}
    if body.campaign_id and body.campaign_id not in ids:
        raise HTTPException(422, 'That campaign is not in this plan.')
    week = body.week_start.isoformat()
    row = (db.query(StrategyResult).filter_by(plan_id=plan.id, week_start=week, platform=body.platform,
                                              campaign_id=body.campaign_id).first())
    if row is None:
        row = StrategyResult(plan_id=plan.id, week_start=week, platform=body.platform, campaign_id=body.campaign_id)
        db.add(row)
    row.spend, row.impressions, row.clicks, row.leads = round(body.spend), body.impressions, body.clicks, body.leads
    row.notes, row.created_by, row.updated_at = body.notes.strip(), user.username, datetime.utcnow()
    db.commit()
    return report_for(db, plan)


@router.delete('/plans/{plan_id}/results/{result_id}', dependencies=[Depends(pick_client)])
def delete_result(plan_id: str, result_id: int, user: AuthUser = Depends(staff), db: Session = Depends(get_db)):
    plan = owned(db, radar_plan(db, plan_id))
    row = db.get(StrategyResult, result_id)
    if row is None or row.plan_id != plan.id:
        raise HTTPException(404, 'Result not found')
    db.delete(row)
    db.commit()
    return report_for(db, plan)
