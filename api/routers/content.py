"""M2 Social content: drafts written by the n8n platform agents (LinkedIn, Instagram, Facebook) from an M1 plan.

Radar plans the posting slots, gives n8n a ready content pack, checks and saves the drafts n8n posts back,
then makes the images. Reels are made by hand from the key frame and prompt shown here, then uploaded.
Nothing is published: approved drafts are copied or downloaded and posted by hand.
"""
import io
import os
import re
import shutil
import zipfile
from datetime import date, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from api.content_media import (MAX_UPLOAD, UPLOAD_TYPES, image_maker, image_prompt, is_quota_error, media_dir,
                               media_file, plain_image_error, save_media, sniff)
from api.content_plan import (ASPECT, DEFAULT_RHYTHM, MAX_TAGS, MAX_TEXT, PLATFORMS, clean_media_buying, content_pack,
                              media_money, plan_slots, review_checks)
from api.routers.strategy import callback_allowed
from api.security import env_int, lookup_session, rate_limit, require_user
from db.database import ContentItem, ContentRun, StrategyPlan, get_db

router = APIRouter()
STALE_AFTER = timedelta(minutes=20)
DEFAULT_BRAND_LOOK = ('Match the logo and the company\'s own past posts (sent as reference images): same colours, '
                      'clean modern layout, bold sans-serif headlines, plenty of white space, premium tech feel.')


class RunRequest(BaseModel):
    plan_id: str = Field(pattern=r'^[0-9a-fA-F-]{36}$')
    start_date: date | None = None
    weeks: int = Field(default=2, ge=1, le=4)
    posts_per_week: int = Field(default=2, ge=1, le=5)
    reels_per_month: int = Field(default=1, ge=0, le=4)
    platforms: list[Literal['LinkedIn', 'Instagram', 'Facebook']] = Field(min_length=1, max_length=3)
    brand_look: str = Field(default='', max_length=600)
    notes: str = Field(default='', max_length=600)
    # Radar plans (version 2) only: posts a week per platform, Instagram stories and the media buying plan.
    rhythm: dict[Literal['LinkedIn', 'Instagram', 'Facebook'], int] = Field(default_factory=dict)
    stories_per_week: int = Field(default=0, ge=0, le=7)
    media_buying: bool = True


class Loose(BaseModel):
    model_config = {'extra': 'ignore'}


class Slide(Loose):
    headline: str = Field(default='', max_length=200)
    body: str = Field(default='', max_length=500)


class Draft(Loose):
    slot_id: str = Field(min_length=1, max_length=40)
    hook: str = Field(default='', max_length=300)
    text: str = Field(min_length=1, max_length=6000)
    hashtags: list[str] = Field(default_factory=list)
    cta: str = Field(default='', max_length=300)
    language: str = Field(default='', max_length=40)
    image_prompt: str = Field(default='', max_length=2000)
    on_image_text: str = Field(default='', max_length=160)
    slides: list[Slide] = Field(default_factory=list, max_length=10)
    higgsfield_prompt: str = Field(default='', max_length=1500)
    reel_seconds: int | None = Field(default=None, ge=0, le=15)   # 0 = not a reel
    why: str = Field(default='', max_length=500)


class DraftResult(BaseModel):
    posts: list[dict] = Field(default_factory=list, max_length=200)
    media_buying: dict | None = None
    model: str = Field(default='', max_length=100)


class RunFailure(BaseModel):
    error: str = Field(min_length=1, max_length=2000)


class ItemEdit(BaseModel):
    status: Literal['draft', 'approved', 'rejected', 'posted'] | None = None
    text: str | None = Field(default=None, max_length=6000)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    image_prompt: str | None = Field(default=None, max_length=2000)
    on_image_text: str | None = Field(default=None, max_length=160)
    higgsfield_prompt: str | None = Field(default=None, max_length=1500)


# ---- Helpers ----------------------------------------------------------------------------

def get_run(db, run_id):
    run = db.get(ContentRun, run_id)
    if run is None:
        raise HTTPException(404, 'Content batch not found')
    return run


def get_item(db, item_id):
    item = db.get(ContentItem, item_id)
    if item is None:
        raise HTTPException(404, 'Draft not found')
    return item


def expire_stale(db, rows):
    now, changed = datetime.utcnow(), False
    for row in rows:
        if row.status in ('queued', 'running') and row.updated_at and now - row.updated_at > STALE_AFTER:
            row.status, row.error = 'failed', 'n8n did not send the drafts. Open the latest n8n execution to see which agent stopped.'
            changed = True
    if changed:
        db.commit()


def tags(values, platform):
    out = []
    for value in values or []:
        word = re.sub(r'[^\w]', '', str(value), flags=re.UNICODE)
        if word and word.casefold() not in {t.casefold() for t in out}:
            out.append(word)
    return ['#' + t for t in out[:MAX_TAGS[platform]]]


def aspect_of(item):
    if item.format in ('reel', 'story'):
        return '9:16'
    return ASPECT[item.platform]


def serialize_item(item, run_id):
    image, video = media_file(run_id, item.id, 'image'), media_file(run_id, item.id, 'video')
    base = f'/content/items/{item.id}/media'
    return {'id': item.id, 'slot_id': item.slot_id, 'platform': item.platform, 'date': item.post_date,
            'format': item.format, 'campaign_id': item.campaign_id, 'status': item.status, 'content': item.content or {},
            'aspect': aspect_of(item),
            'image_status': item.image_status, 'image_error': item.image_error, 'video_status': item.video_status,
            'image_url': f'{base}/image?v={int(image.stat().st_mtime)}' if image else None,
            'video_url': f'{base}/video?v={int(video.stat().st_mtime)}' if video else None}


def serialize_run(run, db, full=False):
    items = db.query(ContentItem).filter_by(run_id=run.id).order_by(ContentItem.post_date, ContentItem.platform).all()
    out = {'run_id': run.id, 'plan_id': run.plan_id, 'company_name': run.company_name, 'status': run.status,
           'error': run.error, 'created_at': run.created_at, 'updated_at': run.updated_at,
           'platforms': run.inputs.get('platforms', []), 'start_date': run.inputs.get('start_date'),
           'end_date': run.inputs.get('end_date'), 'missing_slots': run.inputs.get('missing_slots', []),
           'counts': {s: sum(i.status == s for i in items) for s in ('draft', 'approved', 'rejected', 'posted')},
           'total': len(items), 'version': run.inputs.get('version', 1)}
    if full:
        out['media_buying'] = run.inputs.get('media_buying_plan')
        out['voices'] = run.inputs.get('voices') or {}
        out['items'] = [serialize_item(i, run.id) for i in items]
        out['brand_look'] = run.inputs.get('brand_look', '')
    return out


def load_pack(db, run):
    plan = db.get(StrategyPlan, run.plan_id)
    if plan is None or not plan.plan:
        raise HTTPException(409, 'The strategy plan for this batch is missing.')
    return content_pack(db, run, plan)


async def make_images(make_session, run_id, item_ids=None):
    """Background job: one image per draft (a 9:16 key frame for reels). Stops early when the free allowance is used up."""
    with make_session() as db:
        run = db.get(ContentRun, run_id)
        if run is None:
            return
        query = db.query(ContentItem).filter(ContentItem.run_id == run_id)
        query = query.filter(ContentItem.id.in_(item_ids)) if item_ids else query.filter(ContentItem.image_status == 'pending')
        items = query.order_by(ContentItem.post_date).all()
        if not items:
            return
        try:
            from api.routers.radar_plans import own_pictures
            maker = image_maker()
            refs = await own_pictures(db, run.inputs.get('client_id'))
        except Exception as exc:
            for item in items:
                item.image_status, item.image_error = 'failed', plain_image_error(exc)
            db.commit()
            return
        stop = None
        for item in items:
            if stop:
                item.image_status, item.image_error = 'failed', stop
                continue
            aspect = aspect_of(item)
            try:
                data, mime = await maker.make(image_prompt(item.content or {}, run.inputs.get('brand_look', ''), aspect), aspect, refs)
                save_media(run.id, item.id, 'image', data, UPLOAD_TYPES['image'][mime])
                item.image_status, item.image_error = 'ready', None
            except Exception as exc:
                item.image_status, item.image_error = 'failed', plain_image_error(exc)
                if is_quota_error(exc):
                    stop = item.image_error
            db.commit()
        db.commit()


# ---- Endpoints --------------------------------------------------------------------------

@router.get('/plans/{plan_id}/defaults', dependencies=[Depends(require_user)])
def run_defaults(plan_id: str, db: Session = Depends(get_db)):
    plan = db.get(StrategyPlan, plan_id)
    if plan is None:
        raise HTTPException(404, 'Strategy plan not found')
    inputs = plan.inputs or {}
    start = max(date.today(), date.fromisoformat(inputs.get('start_date') or date.today().isoformat()))
    rhythm = {r['platform']: max(1, min(7, round(r.get('per_week') or 0) or DEFAULT_RHYTHM[r['platform']]))
              for r in ((plan.plan or {}).get('content_plan') or {}).get('rhythm') or []}
    return {'plan_id': plan_id, 'company_name': plan.company_name, 'platforms': list(PLATFORMS), 'version': 2,
            'start_date': start.isoformat(), 'weeks': 1, 'reels_per_month': 2, 'stories_per_week': 3,
            'rhythm': {p: rhythm.get(p, DEFAULT_RHYTHM[p]) for p in PLATFORMS}, 'brand_look': DEFAULT_BRAND_LOOK,
            'voices': inputs.get('voices') or {}, 'media_buying': bool(media_money(plan.plan or {}, inputs)),
            'paid_budget': media_money(plan.plan or {}, inputs), 'currency': inputs.get('currency', '')}


@router.post('/runs', status_code=202, dependencies=[Depends(rate_limit('content', env_int('LIMIT_CONTENT_RUNS_PER_HOUR', 6), 3600))])
async def create_run(body: RunRequest, request: Request, db: Session = Depends(get_db)):
    plan = db.get(StrategyPlan, body.plan_id)
    if plan is None:
        raise HTTPException(404, 'Strategy plan not found')
    if plan.status != 'completed' or not plan.plan:
        raise HTTPException(409, 'Finish the strategy plan first; content is written from a completed plan.')
    start = body.start_date or max(date.today(), date.fromisoformat((plan.inputs or {}).get('start_date') or date.today().isoformat()))
    platforms = [p for p in PLATFORMS if p in body.platforms]
    if (plan.inputs or {}).get('version') != 2:
        raise HTTPException(409, 'This plan was made by an older version and cannot be used for content.')
    slots = plan_slots(plan.plan, platforms, start, body.weeks, body.rhythm, body.reels_per_month, body.stories_per_week)
    inputs = {**body.model_dump(mode='json'), 'platforms': platforms, 'start_date': start.isoformat(),
              'end_date': (start + timedelta(days=7 * body.weeks - 1)).isoformat(),
              'brand_look': body.brand_look.strip() or DEFAULT_BRAND_LOOK, 'slots': slots}
    inputs.update(version=2, client_id=plan.inputs.get('client_id'), voices=plan.inputs.get('voices') or {})
    run = ContentRun(plan_id=plan.id, session_id=plan.session_id, company_name=plan.company_name, inputs=inputs)
    db.add(run)
    db.commit()
    webhook = os.getenv('N8N_CONTENT_WEBHOOK_URL', '').strip() or 'http://localhost:5678/webhook/radar-content'
    app_url = os.getenv('RADAR_CALLBACK_URL', '').strip() or str(request.base_url).rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.post(webhook, json={'run_id': run.id, 'app_base_url': app_url})
        if response.status_code >= 400:
            hint = (' The content workflow is not active: in n8n open "Odynza Radar Content" and click Publish.'
                    if response.status_code == 404 else '')
            raise RuntimeError(f'n8n answered HTTP {response.status_code}.{hint}')
    except (httpx.HTTPError, RuntimeError) as exc:
        run.status = 'failed'
        run.error = (str(exc) if isinstance(exc, RuntimeError) else
                     f'Could not reach n8n at {webhook}. Start n8n and check N8N_CONTENT_WEBHOOK_URL in .env.')
        db.commit()
        raise HTTPException(502, run.error) from None
    run.status = 'running'
    db.commit()
    return serialize_run(run, db)


@router.post('/runs/{run_id}/again', status_code=202,
             dependencies=[Depends(rate_limit('content', env_int('LIMIT_CONTENT_RUNS_PER_HOUR', 6), 3600))])
async def run_again(run_id: str, request: Request, db: Session = Depends(get_db)):
    """A new batch with the same plan and settings as an earlier one; the old batch stays until it is deleted."""
    old = get_run(db, run_id)
    saved = {k: v for k, v in (old.inputs or {}).items() if k in RunRequest.model_fields}
    saved['plan_id'] = old.plan_id
    if saved.get('start_date') and saved['start_date'] < date.today().isoformat():
        saved['start_date'] = None   # an old start date would plan posts in the past
    try:
        body = RunRequest.model_validate(saved)
    except ValidationError:
        raise HTTPException(409, 'The settings of this batch are incomplete; start a new batch instead.') from None
    return await create_run(body, request, db)


@router.get('/runs', dependencies=[Depends(require_user)])
def list_runs(plan_id: str | None = None, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    query = db.query(ContentRun)
    if plan_id:
        query = query.filter(ContentRun.plan_id == plan_id)
    rows = query.order_by(ContentRun.created_at.desc()).limit(limit).all()
    expire_stale(db, rows)
    return [serialize_run(r, db) for r in rows]


@router.get('/runs/{run_id}', dependencies=[Depends(require_user)])
def read_run(run_id: str, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    expire_stale(db, [run])
    return serialize_run(run, db, full=True)


@router.get('/runs/{run_id}/pack')
def read_pack(run_id: str, request: Request, db: Session = Depends(get_db),
              x_radar_token: str | None = Header(default=None)):
    """What the n8n agents write from. A signed-in user may read it; n8n only while the batch is running."""
    run = get_run(db, run_id)
    if lookup_session(db, request) is None:
        if run.status not in ('queued', 'running'):
            raise HTTPException(401, 'Sign in to continue.')
        callback_allowed(request, x_radar_token)
    return load_pack(db, run)


@router.post('/runs/{run_id}/result')
def save_result(run_id: str, body: DraftResult, request: Request, background_tasks: BackgroundTasks,
                db: Session = Depends(get_db), x_radar_token: str | None = Header(default=None)):
    callback_allowed(request, x_radar_token)
    run = get_run(db, run_id)
    if run.status == 'completed':
        return serialize_run(run, db)
    pack = load_pack(db, run)
    known = ' '.join([pack['brief'], pack['brand'], pack['proof'], pack.get('media_buying', '')])
    drafts = {}
    for raw in body.posts:
        try:
            draft = Draft.model_validate(raw)
        except ValidationError:
            continue
        drafts.setdefault(draft.slot_id, draft)
    missing = []
    for slot in run.inputs.get('slots', []):
        draft = drafts.get(slot['slot_id'])
        if draft is None:
            missing.append(slot['slot_id'])
            continue
        platform = slot['platform']
        text = draft.text.strip()
        checks = review_checks(text, [s.model_dump() for s in draft.slides], known)
        if len(text) > MAX_TEXT[platform]:
            text = text[:MAX_TEXT[platform]].rstrip()
            checks.insert(0, f'The text was shortened to the {platform} limit; read the ending.')
        content = {**draft.model_dump(exclude={'slot_id'}), 'text': text, 'hashtags': tags(draft.hashtags, platform),
                   'slides': [s.model_dump() for s in draft.slides][:7], 'checks': checks,
                   'campaign_name': slot.get('campaign_name', ''), 'key_message': slot.get('key_message', '')}
        content['time'] = slot.get('time', '')
        if slot['format'] != 'reel':
            content['higgsfield_prompt'], content['reel_seconds'] = '', None
        else:
            content['reel_seconds'] = min(max(draft.reel_seconds or 6, 4), 10)
        db.add(ContentItem(run_id=run.id, slot_id=slot['slot_id'], platform=platform, post_date=slot['date'],
                           format=slot['format'], campaign_id=slot.get('campaign_id'), content=content,
                           image_status='pending' if draft.image_prompt.strip() else 'none',
                           video_status='waiting' if slot['format'] == 'reel' else 'none'))
    if len(missing) == len(run.inputs.get('slots', [])):
        run.status, run.error = 'failed', 'The agents returned no usable drafts. Run the batch again.'
        db.commit()
        raise HTTPException(422, {'errors': [run.error]})
    run.inputs = {**run.inputs, 'missing_slots': missing, 'model': body.model}
    if run.inputs.get('media_buying'):
        plan = db.get(StrategyPlan, run.plan_id)
        try:
            buying = clean_media_buying(body.media_buying, plan.plan or {}, plan.inputs or {},
                                        {s['slot_id'] for s in run.inputs.get('slots', [])})
        except ValidationError:
            buying = None
        run.inputs = {**run.inputs, 'media_buying_plan': buying}
    run.status, run.error = 'completed', None
    db.commit()
    background_tasks.add_task(make_images, sessionmaker(bind=db.get_bind()), run.id)
    return serialize_run(run, db)


@router.post('/runs/{run_id}/fail')
def save_failure(run_id: str, body: RunFailure, request: Request, db: Session = Depends(get_db),
                 x_radar_token: str | None = Header(default=None)):
    callback_allowed(request, x_radar_token)
    run = get_run(db, run_id)
    if run.status != 'completed':
        run.status, run.error = 'failed', body.error
        db.commit()
    return serialize_run(run, db)


@router.delete('/runs/{run_id}', dependencies=[Depends(require_user)])
def delete_run(run_id: str, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    db.query(ContentItem).filter_by(run_id=run.id).delete()
    db.delete(run)
    db.commit()
    shutil.rmtree(media_dir(run_id), ignore_errors=True)
    return {'deleted': run_id}


@router.get('/runs/{run_id}/download', dependencies=[Depends(require_user)])
def download_run(run_id: str, approved_only: bool = False, db: Session = Depends(get_db)):
    """Every draft as a folder with its caption, slides, prompts and media, ready for manual posting."""
    run = get_run(db, run_id)
    query = db.query(ContentItem).filter_by(run_id=run.id)
    if approved_only:
        query = query.filter(ContentItem.status == 'approved')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in query.order_by(ContentItem.post_date, ContentItem.platform).all():
            c = item.content or {}
            folder = f'{item.post_date}-{item.platform.lower()}-{item.format}'
            caption = c.get('text', '') + ('\n\n' + ' '.join(c.get('hashtags', [])) if c.get('hashtags') else '')
            archive.writestr(f'{folder}/caption.txt', caption)
            if c.get('slides'):
                archive.writestr(f'{folder}/slides.txt', '\n\n'.join(
                    f"Slide {n}: {s.get('headline', '')}\n{s.get('body', '')}" for n, s in enumerate(c['slides'], 1)))
            if c.get('higgsfield_prompt'):
                archive.writestr(f'{folder}/higgsfield-prompt.txt', c['higgsfield_prompt'])
            if c.get('image_prompt'):
                archive.writestr(f'{folder}/image-prompt.txt', c['image_prompt'])
            for kind in ('image', 'video'):
                path = media_file(run.id, item.id, kind)
                if path:
                    archive.write(path, f'{folder}/{kind}{path.suffix}')
    slug = re.sub(r'[^a-z0-9]+', '-', run.company_name.lower()).strip('-') or 'company'
    return Response(buffer.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="radar-content-{slug}-{run.inputs.get("start_date")}.zip"'})


@router.patch('/items/{item_id}', dependencies=[Depends(require_user)])
def edit_item(item_id: int, body: ItemEdit, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    content = dict(item.content or {})
    if body.status:
        item.status = body.status
    for field in ('text', 'image_prompt', 'on_image_text', 'higgsfield_prompt'):
        value = getattr(body, field)
        if value is not None:
            content[field] = value.strip()
    if body.hashtags is not None:
        content['hashtags'] = tags(body.hashtags, item.platform)
    if body.text is not None:
        run = db.get(ContentRun, item.run_id)
        known = ' '.join(load_pack(db, run).get(k, '') for k in ('brief', 'brand', 'proof', 'media_buying'))
        content['checks'] = review_checks(content['text'], content.get('slides', []), known)
    item.content = content
    db.commit()
    return serialize_item(item, item.run_id)


@router.post('/items/{item_id}/image', dependencies=[Depends(rate_limit('content_images', env_int('LIMIT_CONTENT_IMAGES_PER_HOUR', 30), 3600))])
async def remake_image(item_id: int, db: Session = Depends(get_db)):
    """Make (or remake) this draft's image now and wait for it."""
    item = get_item(db, item_id)
    if not (item.content or {}).get('image_prompt'):
        raise HTTPException(409, 'Add an image prompt first.')
    item.image_status, item.image_error = 'pending', None
    db.commit()
    await make_images(sessionmaker(bind=db.get_bind()), item.run_id, [item.id])
    db.expire_all()
    return serialize_item(get_item(db, item_id), item.run_id)


@router.put('/items/{item_id}/media/{kind}', dependencies=[Depends(require_user)])
async def upload_media(item_id: int, kind: Literal['image', 'video'], request: Request, db: Session = Depends(get_db)):
    """Upload an image made in the Gemini app, or the reel made on Higgsfield (raw file body)."""
    item = get_item(db, item_id)
    data = await request.body()
    if not data:
        raise HTTPException(400, 'The file is empty.')
    if len(data) > MAX_UPLOAD[kind]:
        raise HTTPException(413, f'The {kind} is too large.')
    mime = sniff(data, kind)
    if mime is None:
        raise HTTPException(415, 'Upload a PNG, JPG or WebP image.' if kind == 'image' else 'Upload an MP4, MOV or WebM video.')
    save_media(item.run_id, item.id, kind, data, UPLOAD_TYPES[kind][mime])
    if kind == 'image':
        item.image_status, item.image_error = 'uploaded', None
    else:
        item.video_status = 'uploaded'
    db.commit()
    return serialize_item(item, item.run_id)


@router.get('/items/{item_id}/media/{kind}', dependencies=[Depends(require_user)])
def read_media(item_id: int, kind: Literal['image', 'video'], download: bool = False, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    path = media_file(item.run_id, item.id, kind)
    if path is None:
        raise HTTPException(404, f'No {kind} yet')
    ext = path.suffix.lstrip('.')
    mime = {v: k for k, v in UPLOAD_TYPES[kind].items()}[ext]
    name = f'{item.post_date}-{item.platform.lower()}-{item.format}.{ext}'
    return FileResponse(path, media_type=mime, headers={
        'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f'{"attachment" if download else "inline"}; filename="{name}"'})
