"""Scraped pictures are saved on this computer when they are collected, so they keep showing after the platform's
link expires (Facebook and Instagram links stop working within days). Files are named by a hash of their link."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

logger = logging.getLogger(__name__)

DIR = Path(os.getenv('WATCH_PICTURES_DIR') or Path(__file__).resolve().parents[2] / 'data' / 'pictures')
MAX_PER_RUN = 600


def path_for(url: str) -> Path:
    return DIR / hashlib.sha256(url.encode('utf-8')).hexdigest()[:40]


def saved(url: str) -> bytes | None:
    p = path_for(url)
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def keep(url: str, data: bytes) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    p = path_for(url)
    tmp = p.with_suffix('.part')
    tmp.write_bytes(data)
    tmp.replace(p)


# ---- Screenshots of watched pages: real JPEG files, one folder per page, newest KEEP_SHOTS kept ----------------

SHOT_DIR = DIR / 'screenshots'
KEEP_SHOTS = int(os.getenv('WATCH_KEEP_SCREENSHOTS', '5') or 5)
SHOT_KEY = re.compile(r'^shot:([a-z0-9-]{1,80})/([a-z0-9-]{1,80})/(\d{4}-\d{2}-\d{2}_\d{4})\.jpg$')


def slug(value: str, limit: int = 60) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')[:limit].strip('-')


def keep_shot(url: str, data: bytes, when: datetime) -> str:
    """Saves a page screenshot as data/pictures/screenshots/<site>/<page>/<date_time>.jpg and returns its key."""
    parts = urlsplit(url)
    folder = SHOT_DIR / (slug(parts.hostname or 'site', 80) or 'site') / (slug(parts.path, 80) or 'home')
    folder.mkdir(parents=True, exist_ok=True)
    name = f'{when:%Y-%m-%d_%H%M}.jpg'
    (folder / name).write_bytes(data)
    for old in sorted(folder.glob('*.jpg'))[:-KEEP_SHOTS]:
        try:
            old.unlink()
        except OSError:
            pass
    return f'shot:{folder.parent.name}/{folder.name}/{name}'


def shot(key: str) -> bytes | None:
    """The screenshot behind a key from keep_shot; anything else (paths, ..) is refused."""
    m = SHOT_KEY.match(key or '')
    if not m:
        return None
    p = SHOT_DIR / m.group(1) / m.group(2) / f'{m.group(3)}.jpg'
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


# ---- A browsable copy: every saved picture as a normal file under library/<company>/<platform>/ ------------

LIBRARY = DIR / 'library'
EXT = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif', 'image/svg+xml': 'svg', 'image/avif': 'avif'}
PLATFORM_FOLDER = {'page': 'website', 'web': 'news', 'ads': 'ads'}


def _ext(data: bytes) -> str:
    from api.media import image_type
    try:
        return EXT.get(image_type(data, icons=True)[0], 'img')
    except Exception:   # noqa: BLE001
        return 'img'


def library_entries(company: str, kind: str, metrics: dict | None, items: list | None, page_url: str = '') -> list[tuple[str, Path]]:
    """(picture link, file name without extension) for one capture, named by date and what the picture shows."""
    folder = LIBRARY / (slug(company, 60) or 'company') / PLATFORM_FOLDER.get(kind, kind)
    out = []
    metrics = metrics or {}
    if kind == 'page':
        page = slug(urlsplit(page_url).path, 40) or 'home'
        named = [(p.get('url'), p.get('name') or p.get('label') or 'picture') for p in metrics.get('pictures') or [] if isinstance(p, dict)]
        named += [(u, 'cover') for u in metrics.get('images') or []]
        for n, (u, label) in enumerate(named, 1):
            out.append((u, folder / f'{page}_{slug(label, 40) or "picture"}_{n}'))
    for key in ('avatar', 'logo'):
        if metrics.get(key):
            out.append((metrics[key], folder / ('profile-picture' if key == 'avatar' else 'site-logo')))
    for item in items or []:
        if not isinstance(item, dict):
            continue
        day = slug(str(item.get('date') or item.get('start') or '')[:10], 10) or 'undated'
        words = item.get('caption') or item.get('headline') or item.get('title') or item.get('body') or item.get('id') or 'post'
        for n, u in enumerate(item.get('images') or [], 1):
            tag = hashlib.sha256(u.encode('utf-8')).hexdigest()[:6]   # two posts can share a day and first words
            out.append((u, folder / f'{day}_{slug(words, 40) or "post"}_{n}-{tag}'))
    return [(u, f) for u, f in out if isinstance(u, str) and u.startswith(('https://', 'http://'))]


def build_library(db) -> int:
    """Copies every saved picture of each source's latest capture into the library folders. Returns new files."""
    from db.watch_models import WatchClient, WatchCompetitor, WatchSnapshot, WatchSource
    made = 0
    for s in db.query(WatchSource).all():
        snap = (db.query(WatchSnapshot).filter_by(source_id=s.id)
                .order_by(WatchSnapshot.captured_at.desc(), WatchSnapshot.id.desc()).first())
        if snap is None:
            continue
        owner = db.get(WatchCompetitor, s.competitor_id) if s.competitor_id else db.get(WatchClient, s.client_id)
        for u, base in library_entries(getattr(owner, 'name', '') or 'company', s.kind, snap.metrics, snap.items, s.url):
            if any(base.parent.glob(base.name + '.*')):
                continue
            data = saved(u)
            if data is None:
                continue
            try:
                base.parent.mkdir(parents=True, exist_ok=True)
                base.with_name(f'{base.name}.{_ext(data)}').write_bytes(data)
                made += 1
            except OSError:
                pass
    return made


def links_of(metrics: dict | None, items: list | None) -> list[str]:
    """Every picture link in one capture: profile picture, site logo and pictures, and each post's or ad's pictures."""
    metrics = metrics or {}
    out = [metrics.get('avatar'), metrics.get('logo'), *(metrics.get('images') or []),
           *[p.get('url') for p in metrics.get('pictures') or [] if isinstance(p, dict)]]
    for item in items or []:
        if isinstance(item, dict):
            out += list(item.get('images') or [])
    return [u for u in dict.fromkeys(out) if isinstance(u, str) and u.startswith(('https://', 'http://'))]


async def get(url: str, icons: bool = False) -> tuple[bytes, str]:
    """The saved copy, or the picture downloaded now and saved for next time. Returns (bytes, mime)."""
    from api.media import fetch_public, image_type
    data = saved(url)
    if data is None:
        data, _ = await fetch_public(url)
        image_type(data, icons=icons)   # refuse anything that is not a picture before keeping it
        keep(url, data)
    return data, image_type(data, icons=icons)[0]


async def save(urls: list[str]) -> int:
    """Downloads the pictures not saved yet, six at a time. Returns how many were newly saved."""
    todo = [u for u in dict.fromkeys(urls) if not path_for(u).is_file()][:MAX_PER_RUN]
    gate = asyncio.Semaphore(6)
    done = 0

    async def one(u):
        nonlocal done
        async with gate:
            try:
                await get(u, icons=True)
                done += 1
            except (HTTPException, OSError):
                pass   # expired or not a picture; the post keeps its link
    await asyncio.gather(*(one(u) for u in todo))
    return done


def drop_page_links(db) -> int:
    """Older collectors stored Facebook/Instagram post page links as pictures. Removes them from every capture, so
    the app stops asking for them; picture links stay out of the content hash, so no change is reported."""
    from api.watch.collect import is_picture_link
    from db.watch_models import WatchSnapshot
    fixed = 0
    for snap in db.query(WatchSnapshot).all():
        changed = False
        items = []
        for item in snap.items or []:
            if isinstance(item, dict) and any(not is_picture_link(u) for u in item.get('images') or []):
                item = {**item, 'images': [u for u in item['images'] if is_picture_link(u)]}
                changed = True
            items.append(item)
        metrics = dict(snap.metrics or {})
        if any(not is_picture_link(u) for u in metrics.get('images') or []):
            metrics['images'] = [u for u in metrics['images'] if is_picture_link(u)]
            changed = True
        if changed:
            snap.items, snap.metrics = items, metrics
            fixed += 1
    if fixed:
        db.commit()
    return fixed


async def backfill() -> int:
    """Saves the pictures of the latest capture of every source, for captures made before pictures were saved."""
    from db.database import SessionLocal
    from db.watch_models import WatchSnapshot, WatchSource
    urls: list[str] = []
    with SessionLocal() as db:
        if n := drop_page_links(db):
            logger.info(f'[watch] removed post page links from {n} older captures')
        for s in db.query(WatchSource).all():
            snap = (db.query(WatchSnapshot).filter_by(source_id=s.id)
                    .order_by(WatchSnapshot.captured_at.desc(), WatchSnapshot.id.desc()).first())
            if snap is not None:
                urls += links_of(snap.metrics, snap.items)
    n = await save(urls)
    if n:
        logger.info(f'[watch] saved {n} scraped pictures to {DIR}')
    with SessionLocal() as db:
        if made := build_library(db):
            logger.info(f'[watch] {made} pictures added to {LIBRARY}')
    return n
