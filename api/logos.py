"""Company logos for reports: the site's sharpest own icon (web-app manifest, phone icon, logo image), else Google's
favicon service; cached in memory."""
import asyncio
import io
import json
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException

from api.media import fetch_public, image_type

_cache: dict[str, tuple[float, tuple[bytes, str] | None]] = {}
CACHE_SECONDS = 24 * 3600
MISS_SECONDS = 3600


MIN_SIDE = 64   # smaller pictures look blurry on cards, so a bigger one is tried first


def _side(sizes):
    found = [int(s.split('x')[0]) for s in (sizes or '').lower().split() if s.split('x')[0].isdigit()]
    return max(found) if found else None


class IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []
        self.manifest = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}
        rel = a.get('rel', '').lower().split()
        if tag == 'link' and a.get('href') and ('icon' in rel or 'apple-touch-icon' in rel):
            score = _side(a.get('sizes')) or (180 if 'apple-touch-icon' in rel else 32)
            self.icons.append((score, a['href']))
        elif tag == 'link' and a.get('href') and 'manifest' in rel:
            self.manifest = a['href']
        elif tag == 'meta' and a.get('content') and (a.get('itemprop', '').lower() == 'logo'
                                                    or a.get('property', '').lower() == 'og:logo'):
            self.icons.append((150, a['content']))
        elif tag == 'img' and a.get('src') and a.get('itemprop', '').lower() == 'logo':
            self.icons.append((150, a['src']))


def _pixels(data):
    """Width of the picture, or None when it cannot be told (SVG is sharp at any size)."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            if getattr(im, 'format', '') == 'ICO':
                return max(w for w, _ in im.info.get('sizes', {im.size}))
            return min(im.size)
    except Exception:
        return None


async def _manifest_icons(url):
    try:
        raw, final = await fetch_public(url, accept='application/manifest+json,application/json', limit=300_000, total=8)
        icons = json.loads(raw.decode('utf-8', 'ignore')).get('icons') or []
    except (HTTPException, ValueError, AttributeError):
        return []
    out = []
    for icon in icons if isinstance(icons, list) else []:
        if isinstance(icon, dict) and isinstance(icon.get('src'), str) and 'monochrome' not in str(icon.get('purpose', '')):
            out.append((_side(icon.get('sizes')) or 96, urljoin(final, icon['src'])))
    return out


def site_root(website):
    parts = urlsplit(website or '')
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return None
    return f'{parts.scheme}://{parts.netloc}/'


async def _find_logo(root):
    candidates = []
    try:
        html, final = await fetch_public(root, accept='text/html', limit=1_500_000, total=12)
        parser = IconLinks()
        parser.feed(html.decode('utf-8', 'ignore'))
        found = [(n, urljoin(final, href)) for n, href in parser.icons]
        if parser.manifest:
            found += await _manifest_icons(urljoin(final, parser.manifest))
        # Sharpest first, but past 512px the file only gets heavier.
        found.sort(key=lambda f: -min(f[0], 512))
        candidates += [u for _, u in found[:5]]
    except HTTPException:
        pass
    host = urlsplit(root).hostname
    candidates += [urljoin(root, '/apple-touch-icon.png'),
                   f'https://www.google.com/s2/favicons?domain={host}&sz=128']
    small = None
    for url in dict.fromkeys(candidates):
        try:
            data, _ = await fetch_public(url, limit=2_000_000, total=10)
            mime, _ = image_type(data, icons=True)
        except HTTPException:
            continue
        # Google answers unknown sites with a 16px globe; anything this small is not worth showing.
        if len(data) <= 400:
            continue
        side = _pixels(data)
        if side is None or side >= MIN_SIDE:
            return data, mime
        small = small or (data, mime)   # a blurry icon still beats initials
    return small


async def company_logo(website):
    root = site_root(website)
    if root is None:
        return None
    hit = _cache.get(root)
    if hit and time.time() - hit[0] < (CACHE_SECONDS if hit[1] else MISS_SECONDS):
        return hit[1]
    try:
        found = await asyncio.wait_for(_find_logo(root), 25)
    except asyncio.TimeoutError:
        found = None
    _cache[root] = (time.time(), found)
    return found
