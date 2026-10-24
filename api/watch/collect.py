"""Collectors for the Watch module: website pages (Playwright), Instagram (Meta Business Discovery, or Apify when Meta
is not set up), Facebook and LinkedIn (Apify), Meta ads (Apify Ad Library actor). No AI.

Every collector returns {'text', 'fields', 'metrics', 'items', 'cost'} or raises CollectError with a plain message.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx
from loguru import logger

from api.netguard import guard_context, url_is_public
from api.watch.fields import extract, page_images

APIFY = 'https://api.apify.com/v2'
TERMINAL = {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}
CAIRO = timezone(timedelta(hours=3))   # Egypt summer time; slots are coarse (morning / afternoon / evening / night)


class CollectError(RuntimeError):
    """A plain, user-facing reason that a source could not be collected. Shown in Source health."""


def env(name, default=''):
    return (os.getenv(name) or default).strip()


def actor(name, default):
    return env(name, default).replace('/', '~')


# ---- Website pages --------------------------------------------------------------------------

async def load_pages(urls: list[str]) -> dict[str, str | Exception]:
    """Loads each URL once in one browser. Windows needs Playwright on a Proactor loop in its own thread."""
    if sys.platform == 'win32':
        def run():
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_load_pages(urls))
            finally:
                loop.close()
        return await asyncio.to_thread(run)
    return await _load_pages(urls)


async def _scrolled(page, steps: int = 8) -> str:
    """Scrolls down the page in steps so pictures that load only when seen (client logos, galleries) are in the html."""
    try:
        for _ in range(steps):
            done = await page.evaluate(
                "() => { window.scrollBy(0, window.innerHeight); return window.scrollY + window.innerHeight >= document.body.scrollHeight - 4; }")
            await page.wait_for_timeout(350)
            if done:
                break
        await page.wait_for_timeout(600)
        return await page.content()
    except Exception:  # a page that closes or blocks scripts keeps the html already loaded
        return ''


SHOTS: dict[str, bytes] = {}   # the last full-page screenshot of each loaded page, taken by _load_pages
SHOT_MAX_HEIGHT = 9000


async def _screenshot(page) -> bytes | None:
    """The whole page as it looked, as a JPEG (very long pages are cut at SHOT_MAX_HEIGHT pixels)."""
    if env('WATCH_SCREENSHOTS', '1') == '0':
        return None
    try:
        await page.evaluate('() => window.scrollTo(0, 0)')
        size = await page.evaluate('() => [document.documentElement.clientWidth, document.body.scrollHeight]')
        width, height = int(size[0] or 1280), min(int(size[1] or 0), SHOT_MAX_HEIGHT)
        if height < 200:
            return None
        return await page.screenshot(type='jpeg', quality=70, full_page=True, timeout=20000,
                                     clip={'x': 0, 'y': 0, 'width': width, 'height': height})
    except Exception:   # a screenshot is a bonus; the page text is already saved
        return None


async def _load_pages(urls):
    from playwright.async_api import async_playwright
    from api.watch.browser import USER_AGENT, load_page
    out: dict[str, str | Exception] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=USER_AGENT)
            await guard_context(context)
            for url in urls:
                if not await url_is_public(url):
                    out[url] = CollectError('This address is not on the public internet, so it is not loaded.')
                    continue
                page = await context.new_page()
                try:
                    out[url] = await load_page(page, url, 2000)
                    out[url] = await _scrolled(page) or out[url]
                    shot = await _screenshot(page)
                    if shot:
                        SHOTS[url] = shot
                except Exception as exc:  # Playwright has many error types; the reason is shown in Source health
                    out[url] = CollectError(f'The page did not load ({type(exc).__name__}). It may be down or blocking robots.')
                finally:
                    await page.close()
        finally:
            await browser.close()
    return out


def page_snapshot(html: str, url: str, kind: str) -> dict:
    data = extract(html, url, kind)
    if len(data['text']) < 40 and not data['fields'].get('prices'):
        raise CollectError('The page loaded but showed almost no text. It may need a login or block robots.')
    return {'text': data['text'], 'fields': data['fields'],
            'metrics': {'words': len(data['text'].split()), **page_images(html, url, kind)}, 'items': [], 'cost': 0.0}


# ---- Apify ----------------------------------------------------------------------------------

class Apify:
    """Starts one Actor run, waits for it and returns (rows, cost in USD). A run is never retried automatically,
    because a lost answer can still be a paid run."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client
        self.token = env('APIFY_API_TOKEN') or env('APIFY_TOKEN')

    async def _call(self, client, method, path, **kw):
        try:
            r = await client.request(method, APIFY + path, headers={'Authorization': f'Bearer {self.token}'}, **kw)
        except httpx.RequestError:
            raise CollectError('Apify could not be reached. Check the internet connection.') from None
        if r.status_code in (401, 403):
            raise CollectError('Apify refused the token. Check APIFY_API_TOKEN in .env.')
        if r.status_code == 402:
            raise CollectError('Apify says the monthly credit is used up. Collection from Apify waits for next month.')
        if r.status_code >= 400:
            raise CollectError(f'Apify answered HTTP {r.status_code}. Check the actor in the Apify Console.')
        try:
            return r.json()
        except ValueError:
            raise CollectError('Apify returned something that is not JSON.') from None

    async def run(self, actor_id: str, payload: dict, max_usd: float, limit: int = 50) -> tuple[list, float]:
        if not self.token or self.token.startswith('your_'):
            raise CollectError('Set APIFY_API_TOKEN in .env to collect Facebook, LinkedIn and ads.')
        own = self.client is None
        client = self.client or httpx.AsyncClient(timeout=60)
        timeout = int(env('APIFY_RUN_TIMEOUT_SECONDS', '180') or 180)
        try:
            started = await self._call(client, 'POST', f'/acts/{actor_id}/runs', json=payload,
                                       params={'timeout': timeout, 'maxItems': limit, 'maxTotalChargeUsd': max_usd})
            run = (started or {}).get('data') or {}
            if not run.get('id'):
                raise CollectError('Apify did not start the run.')
            path = '/actor-runs/' + quote(run['id'], safe='')
            deadline = time.monotonic() + timeout + 30
            while run.get('status') not in TERMINAL:
                if time.monotonic() > deadline:
                    await self._call(client, 'POST', path + '/abort')
                    raise CollectError('The Apify run took too long and was stopped.')
                run = (await self._call(client, 'GET', path, params={'waitForFinish': 20})).get('data') or {}
            cost = float(run.get('usageTotalUsd') or 0)
            if run.get('status') != 'SUCCEEDED':
                raise CollectError(f"The Apify run ended with {run.get('status')}. Open it in the Apify Console to see why.")
            rows = await self._call(client, 'GET', f"/datasets/{quote(run.get('defaultDatasetId') or '', safe='')}/items",
                                    params={'format': 'json', 'limit': limit, 'clean': 'true'})
            return (rows if isinstance(rows, list) else []), cost
        finally:
            if own:
                await client.aclose()


# ---- Posts and metrics --------------------------------------------------------------------------

def num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        v = value.strip().lower().replace(',', '')
        m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([km])?', v)
        if m:
            return int(float(m.group(1)) * {'k': 1000, 'm': 1_000_000}.get(m.group(2) or '', 1))
    return None


def when(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
        text = str(value).strip().replace('Z', '+00:00')
        if re.fullmatch(r'\d{10,13}', text):
            return when(int(text))
        dt = datetime.fromisoformat(text.replace('+0000', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def slot(dt: datetime) -> str:
    local = dt.astimezone(CAIRO)
    part = 'morning' if 6 <= local.hour < 12 else 'afternoon' if local.hour < 17 else 'evening' if local.hour < 22 else 'night'
    return f"{local.strftime('%a')} {part}"


def post(pid, url, dt, fmt, caption, likes, comments, shares=None, views=None, images=None):
    total = sum(v for v in (likes, comments, shares) if v)
    out = {'id': str(pid or url), 'url': url or '', 'date': dt.isoformat() if dt else None, 'format': fmt,
           'caption': (caption or '')[:2200], 'likes': likes, 'comments': comments, 'shares': shares,
           'views': views, 'engagement_total': total}
    pics = pictures(images)
    if pics:
        out['images'] = pics   # image links are left out of the content hash, so a refreshed CDN link is not a change
    return out


# Links to a platform's own pages (a Facebook photo or reel page, an Instagram post) are not pictures.
PAGE_HOSTS = {'facebook.com', 'www.facebook.com', 'web.facebook.com', 'm.facebook.com', 'fb.com', 'fb.me',
              'instagram.com', 'www.instagram.com', 'linkedin.com', 'www.linkedin.com'}


def is_picture_link(v) -> bool:
    return isinstance(v, str) and v.startswith(('https://', 'http://')) and urlsplit(v).hostname not in PAGE_HOSTS


def pictures(values, cap=4) -> list[str]:
    """Picture links from an actor's mixed list of strings and objects, http(s) only, no duplicates. In an object the
    picture itself (photo_image, image, thumbnail) wins over its 'url', which on Facebook is the photo's page."""
    out = []
    for v in values if isinstance(values, list) else [values]:
        if isinstance(v, dict):
            found = [(v.get('photo_image') or {}).get('uri') if isinstance(v.get('photo_image'), dict) else None,
                     (v.get('image') or {}).get('uri') if isinstance(v.get('image'), dict) else v.get('image'),
                     v.get('thumbnail'), v.get('uri'), v.get('src'), v.get('url')]
            v = next((f for f in found if is_picture_link(f)), None)
        if is_picture_link(v) and v not in out:
            out.append(v)
    return out[:cap]


def with_avatar(metrics: dict, *values) -> dict:
    """The account's profile picture (usually its logo), kept in metrics so it never counts as a change."""
    found = pictures([v for v in values if v], cap=1)
    if found:
        metrics['avatar'] = found[0]
    return metrics


def post_metrics(posts: list[dict], followers: int | None, bio=None, name=None, now: datetime | None = None,
                 shares_public=True) -> dict:
    """Engagement rate = (likes + comments + shares) ÷ followers per post, averaged over the last 30 days."""
    now = now or datetime.now(timezone.utc)
    dated = [(p, when(p.get('date'))) for p in posts]
    recent = [p for p, d in dated if d and now - d <= timedelta(days=30)]
    last28 = [p for p, d in dated if d and now - d <= timedelta(days=28)]
    latest = max((d for _, d in dated if d), default=None)
    totals = [p['engagement_total'] for p in recent]
    rate = None
    if followers and recent:
        rate = round(sum(t / followers for t in totals) / len(totals) * 100, 2)
        for p in recent:
            p['engagement_rate'] = round(p['engagement_total'] / followers * 100, 2)
    tags, mentions = Counter(), Counter()
    for p in posts:
        tags.update(t.lower() for t in re.findall(r'#([\w؀-ۿ]{2,40})', p.get('caption') or ''))
        mentions.update(m.lower() for m in re.findall(r'@([\w.]{2,40})', p.get('caption') or ''))
    best = sorted(recent, key=lambda p: p['engagement_total'], reverse=True)[:3]
    return {'name': name, 'bio': bio, 'followers': followers, 'posts_30d': len(recent),
            'posts_per_week': round(len(last28) / 4, 1),
            'days_since_last_post': (now - latest).days if latest else None,
            'format_mix': dict(Counter(p['format'] for p in recent)),
            'slots': dict(Counter(slot(d) for p, d in dated if d and now - d <= timedelta(days=30))),
            'avg_engagement': round(sum(totals) / len(totals), 1) if totals else 0,
            'engagement_rate': rate, 'best_posts': [p['id'] for p in best],
            'hashtags': [t for t, _ in tags.most_common(10)], 'mentions': [m for m, _ in mentions.most_common(10)],
            'shares_public': shares_public, 'video_completion': 'not public'}


def handle(url: str, platform: str) -> str:
    path = [p for p in urlsplit(url).path.split('/') if p]
    if not path:
        raise CollectError(f'This {platform} link has no account name in it.')
    if platform == 'linkedin' and path[0] in ('company', 'school', 'showcase') and len(path) > 1:
        return path[1]
    return path[0].lstrip('@')


# ---- Instagram ------------------------------------------------------------------------------

IG_FORMAT = {'VIDEO': 'reel', 'REELS': 'reel', 'CAROUSEL_ALBUM': 'carousel', 'IMAGE': 'image',
             'Video': 'reel', 'Sidecar': 'carousel', 'Image': 'image', 'clips': 'reel'}


def meta_ready() -> bool:
    return bool(env('META_ACCESS_TOKEN') and env('META_IG_USER_ID') and 'xxxx' not in env('META_ACCESS_TOKEN'))


async def instagram(url: str, apify: Apify, max_usd: float) -> dict:
    username = handle(url, 'Instagram')
    if meta_ready():
        got = await instagram_meta(username)
        # Meta sometimes gives the profile without its posts; Apify still sees them.
        if got['items'] or not (env('APIFY_API_TOKEN') or env('APIFY_TOKEN')):
            return got
    extra = [k for k in ('posts', 'reels') if ig_limit(k)]
    share = max_usd / (1 + len(extra))
    rows, cost = await apify.run(actor('WATCH_ACTOR_INSTAGRAM', 'apify~instagram-profile-scraper'),
                                 {'usernames': [username], 'resultsLimit': 24}, share, limit=1)
    if not rows or not isinstance(rows[0], dict) or rows[0].get('error'):
        raise CollectError('Instagram returned no profile. Check that the account is public and the link is right.')
    p = rows[0]
    found = [x for x in p.get('latestPosts') or [] if isinstance(x, dict)]
    missed = []
    # The profile carries only its newest dozen posts; the post and reel scrapers reach further back.
    for kind in extra:
        try:
            more, spent = await apify.run(actor(f'WATCH_ACTOR_INSTAGRAM_{kind.upper()}', f'apify~instagram-{kind[:-1]}-scraper'),
                                          {'username': [username], 'resultsLimit': ig_limit(kind)}, share, limit=ig_limit(kind))
            cost += spent
            found += [x for x in more if isinstance(x, dict) and (x.get('shortCode') or x.get('id')) and not x.get('followersCount')
                      and not x.get('error')]
        except CollectError as exc:   # the profile and its newest posts are still worth keeping
            missed.append(f'{kind}: {exc}')
    posts, seen = [], set()
    for x in found:
        key = x.get('shortCode') or x.get('id')
        if key in seen:
            continue
        seen.add(key)
        posts.append(post(x.get('id') or x.get('shortCode'), x.get('url') or f"https://www.instagram.com/p/{x.get('shortCode')}/",
                          when(x.get('timestamp')), IG_FORMAT.get(x.get('productType')) or IG_FORMAT.get(x.get('type'), 'image'),
                          x.get('caption'), num(x.get('likesCount')), num(x.get('commentsCount')), None,
                          num(x.get('videoPlayCount') or x.get('videoViewCount')),
                          [x.get('displayUrl')] + list(x.get('images') or [])))
    posts.sort(key=lambda i: i.get('date') or '', reverse=True)
    metrics = with_avatar(post_metrics(posts, num(p.get('followersCount')), p.get('biography') or '', p.get('fullName'),
                                       shares_public=False), p.get('profilePicUrlHD'), p.get('profilePicUrl'))
    metrics['reels'] = sum(1 for i in posts if i.get('format') == 'reel')
    if missed:
        metrics['missed'] = missed
    return {'text': '', 'fields': {}, 'metrics': metrics, 'items': posts, 'cost': cost}


def ig_limit(kind: str) -> int:
    """How many posts (WATCH_IG_POSTS, default 24) and reels (WATCH_IG_REELS, default 12) to ask Apify for; 0 skips."""
    try:
        return max(0, min(100, int(env(f'WATCH_IG_{kind.upper()}', '24' if kind == 'posts' else '12'))))
    except ValueError:
        return 0


async def instagram_meta(username: str) -> dict:
    """Business Discovery: public data of any business or creator account, read through your own IG business account."""
    version = env('META_API_VERSION', 'v21.0')
    fields = ('business_discovery.username(%s){name,biography,followers_count,media_count,profile_picture_url,'
              'media.limit(30){id,caption,like_count,comments_count,media_type,media_product_type,timestamp,permalink,'
              'media_url,thumbnail_url}}') % username
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"https://graph.facebook.com/{version}/{env('META_IG_USER_ID')}",
                                 params={'fields': fields, 'access_token': env('META_ACCESS_TOKEN')})
    except httpx.RequestError:
        raise CollectError('Meta could not be reached. Check the internet connection.') from None
    data = r.json() if r.headers.get('content-type', '').startswith(('application/json', 'text/javascript')) else {}
    if r.status_code >= 400 or 'error' in data:
        message = ((data.get('error') or {}).get('message') or '')[:160]
        if 'expired' in message.lower() or r.status_code == 401:
            raise CollectError('The Meta access token has expired. Make a new one and put it in META_ACCESS_TOKEN.')
        raise CollectError(f'Meta refused the Instagram request: {message or "HTTP " + str(r.status_code)}. '
                           'Only public business or creator accounts can be read.')
    b = data.get('business_discovery') or {}
    posts = [post(m.get('id'), m.get('permalink'), when(m.get('timestamp')),
                  IG_FORMAT.get(m.get('media_product_type')) if m.get('media_product_type') == 'REELS'
                  else IG_FORMAT.get(m.get('media_type'), 'image'),
                  m.get('caption'), num(m.get('like_count')), num(m.get('comments_count')), None, None,
                  [m.get('thumbnail_url') or (m.get('media_url') if m.get('media_type') != 'VIDEO' else None)])
             for m in (b.get('media') or {}).get('data') or []]
    metrics = with_avatar(post_metrics(posts, num(b.get('followers_count')), b.get('biography') or '', b.get('name'),
                                       shares_public=False), b.get('profile_picture_url'))
    return {'text': '', 'fields': {}, 'metrics': metrics, 'items': posts, 'cost': 0.0}


# ---- Facebook and LinkedIn (Apify) -----------------------------------------------------------------

async def facebook(url: str, apify: Apify, max_usd: float) -> dict:
    page_rows, cost1 = await apify.run(actor('WATCH_ACTOR_FACEBOOK_PAGE', 'apify~facebook-pages-scraper'),
                                       {'startUrls': [{'url': url}]}, max_usd / 2, limit=1)
    rows, cost2 = await apify.run(actor('WATCH_ACTOR_FACEBOOK_POSTS', 'apify~facebook-posts-scraper'),
                                  {'startUrls': [{'url': url}], 'resultsLimit': 15, 'captionText': False}, max_usd / 2, limit=15)
    page = page_rows[0] if page_rows and isinstance(page_rows[0], dict) else {}
    followers = num(page.get('followers')) or num(page.get('followersCount')) or num(page.get('likes'))
    posts = []
    for x in rows:
        if not isinstance(x, dict) or x.get('error'):
            continue
        media = x.get('media') or []
        fmt = 'reel' if x.get('isVideo') or any(isinstance(m, dict) and m.get('__typename') == 'Video' for m in media) \
            else 'carousel' if len(media) > 1 else 'image' if media else 'text'
        posts.append(post(x.get('postId') or x.get('id'), x.get('url') or x.get('postUrl'), when(x.get('time') or x.get('timestamp')),
                          fmt, x.get('text') or x.get('message'), num(x.get('likes')), num(x.get('comments')),
                          num(x.get('shares')), num(x.get('viewsCount')), media + [x.get('thumb'), x.get('image')]))
    if not posts and not followers:
        raise CollectError('Facebook returned no page data. Check that the page is public and the link is right.')
    bio = page.get('intro') or page.get('info') or page.get('about') or ''
    bio = ' '.join(bio) if isinstance(bio, list) else str(bio)
    return {'text': '', 'fields': {}, 'items': posts, 'cost': cost1 + cost2,
            'metrics': with_avatar(post_metrics(posts, followers, bio[:600], page.get('title') or page.get('name')),
                                   page.get('profilePictureUrl'), page.get('profilePhoto'))}


async def linkedin(url: str, apify: Apify, max_usd: float) -> dict:
    company_rows, cost1 = await apify.run(actor('WATCH_ACTOR_LINKEDIN_COMPANY', 'harvestapi~linkedin-company'),
                                          {'companies': [url]}, max_usd / 2, limit=1)
    rows, cost2 = await apify.run(actor('WATCH_ACTOR_LINKEDIN_POSTS', 'harvestapi~linkedin-company-posts'),
                                  {'targetUrls': [url], 'maxPosts': 12, 'scrapeComments': False, 'scrapeReactions': False,
                                   'includeReposts': False, 'includeQuotePosts': False}, max_usd / 2, limit=12)
    company = company_rows[0] if company_rows and isinstance(company_rows[0], dict) else {}
    followers = num(company.get('followerCount')) or num(company.get('followers')) or num(company.get('followersCount'))
    posts = []
    for x in rows:
        if not isinstance(x, dict) or x.get('type') not in (None, 'post'):
            continue
        e = x.get('engagement') if isinstance(x.get('engagement'), dict) else {}
        fmt = 'video' if x.get('video') else 'document' if x.get('document') else 'image' if x.get('postImages') else 'text'
        posted = x.get('postedAt') if isinstance(x.get('postedAt'), dict) else {}
        posts.append(post(x.get('id'), x.get('linkedinUrl'), when(posted.get('timestamp') or posted.get('date') or x.get('postedAt')),
                          fmt, x.get('content'), num(e.get('likes')), num(e.get('comments')), num(e.get('shares')),
                          None, list(x.get('postImages') or [])))
    if not posts and not followers:
        raise CollectError('LinkedIn returned no company data. Check that the link is a public company page.')
    return {'text': '', 'fields': {}, 'items': posts, 'cost': cost1 + cost2,
            'metrics': with_avatar(post_metrics(posts, followers, (company.get('description') or company.get('tagline') or '')[:600],
                                                company.get('name')), company.get('logo'), company.get('logoUrl'))}


# ---- Web and news mentions (Serper) -------------------------------------------------------------------

SERPER = 'https://google.serper.dev'


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or '').lower().removeprefix('www.')
    except ValueError:
        return ''


SOCIAL_HOSTS = ('facebook.com', 'instagram.com', 'linkedin.com', 'x.com', 'twitter.com', 'tiktok.com', 'youtube.com', 'threads.net')


async def web_mentions(name: str, website: str, client=None) -> dict:
    """Google news and web results from the last month that name the company, from other sites than its own.
    Two Serper queries per run (the free plan has 2,500)."""
    key = env('SERPER_API_KEY')
    if not key:
        raise CollectError('Web and news search needs SERPER_API_KEY in .env (the same key the competitor search uses).')
    own = _host(website)
    country = env('WATCH_SEARCH_COUNTRY', 'eg').lower()
    quoted = f'"{name}"'
    searches = [('news', 'news', {'q': quoted, 'gl': country, 'tbs': 'qdr:m', 'num': 10}),
                ('web', 'search', {'q': f'{quoted} -site:{own}' if own else quoted, 'gl': country, 'tbs': 'qdr:m', 'num': 10})]
    items, seen = [], set()
    async with (client or httpx.AsyncClient(timeout=20)) as http:
        for kind, path, body in searches:
            r = await http.post(f'{SERPER}/{path}', headers={'X-API-KEY': key}, json=body)
            if r.status_code in (401, 403):
                raise CollectError('Serper rejected SERPER_API_KEY. Check the key in .env.')
            if r.status_code in (402, 429):
                raise CollectError('Serper credits or rate limit are used up. Check your Serper dashboard.')
            if r.status_code >= 400:
                raise CollectError(f'Serper returned HTTP {r.status_code}.')
            data = r.json() if r.content else {}
            for row in (data.get('news' if kind == 'news' else 'organic') or [])[:10]:
                link = row.get('link') if isinstance(row, dict) else None
                host = _host(link or '')
                if not link or not link.startswith(('http://', 'https://')) or not host or (own and host.endswith(own)):
                    continue
                if host.endswith(SOCIAL_HOSTS):   # the company's own posts there are watched by their own sources
                    continue
                ident = link.split('#')[0].rstrip('/')
                if ident in seen:
                    continue
                seen.add(ident)
                pic = row.get('imageUrl') or row.get('thumbnailUrl')
                items.append({'id': ident, 'url': link, 'kind': kind, 'title': str(row.get('title') or '')[:300],
                              'snippet': str(row.get('snippet') or '')[:600], 'site': str(row.get('source') or host)[:120],
                              'date': str(row.get('date') or '')[:40],
                              'images': [pic] if is_picture_link(pic) and not str(pic).startswith('data:') else []})
    await add_previews(items)
    return {'text': '', 'fields': {}, 'items': items, 'cost': 0.0,
            'metrics': {'mentions': len(items), 'news': sum(1 for i in items if i['kind'] == 'news'),
                        'sites': len({_host(i['url']) for i in items})}}


PREVIEW_MAX = 20


def _meta(html: str, *names) -> str:
    for n in names:
        m = (re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']+)' % re.escape(n), html, re.I)
             or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(n), html, re.I))
        if m:
            import html as h
            return h.unescape(m.group(1)).strip()
    return ''


async def preview(url: str) -> dict:
    """The share card of an article: its picture, summary, site name and publish date (Open Graph tags)."""
    from urllib.parse import urljoin
    from api.media import fetch_public
    try:
        body, final = await fetch_public(url, accept='text/html', limit=900_000, total=12)
    except Exception:   # the article blocks robots or is gone: the search result alone stays
        return {}
    html = body.decode('utf-8', 'ignore')
    pic = _meta(html, 'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src')
    pic = urljoin(final, pic) if pic else ''
    return {'image': pic if is_picture_link(pic) else '',
            'summary': _meta(html, 'og:description', 'description', 'twitter:description')[:500],
            'site_name': _meta(html, 'og:site_name')[:120],
            'published': _meta(html, 'article:published_time', 'og:updated_time')[:40]}


async def add_previews(items: list[dict]) -> None:
    """Gives each news and web result its article's picture and summary, four articles at a time."""
    if env('WATCH_PREVIEWS', '1') == '0':
        return
    gate = asyncio.Semaphore(4)

    async def one(item):
        async with gate:
            card = await preview(item['url'])
        if card.get('image') and not item.get('images'):
            item['images'] = [card['image']]
        if card.get('summary') and len(card['summary']) > len(item.get('snippet') or ''):
            item['summary'] = card['summary']
        for k in ('site_name', 'published'):
            if card.get(k):
                item[k] = card[k]
    await asyncio.gather(*(one(i) for i in items[:PREVIEW_MAX]))


# ---- Meta ads (Apify Ad Library actor) -------------------------------------------------------------

def _norm(value) -> str:
    return re.sub(r'[^0-9a-z\u0600-\u06ff]', '', str(value or '').lower())


def ad_page(row: dict) -> tuple[str, str, str]:
    """(page id, page name, page link) of one Ad Library row."""
    s = row.get('snapshot') if isinstance(row.get('snapshot'), dict) else {}
    return (str(row.get('page_id') or s.get('page_id') or ''), row.get('page_name') or s.get('page_name') or '',
            s.get('page_profile_uri') or row.get('page_profile_uri') or '')


def ad_is_theirs(row: dict, page_url: str, name: str) -> bool:
    """The actor also returns ads that only MENTION the company, so keep the page's own ads only."""
    pid, pname, puri = ad_page(row)
    parts = urlsplit(page_url)
    wanted_id = re.search(r'(?:^|&)id=(\d+)', parts.query or '')
    if wanted_id and pid == wanted_id.group(1):
        return True
    try:
        h = _norm(handle(page_url, 'Facebook'))
    except CollectError:
        h = ''
    if h in ('profilephp', 'pages', 'people'):
        h = ''
    if puri:
        path = [x for x in urlsplit(puri).path.split('/') if x]
        if path and h and _norm(path[0]) == h:
            return True
    n, cn = _norm(pname), _norm(name)
    if not n:
        return False
    for key in (h, cn):
        if len(key) >= 3 and (n == key or (n.startswith(key) and len(key) >= 5 and not n[len(key):len(key) + 1].isdigit())):
            return True
    return False


def _pic(x) -> str:
    """The Ad Library gives a picture as a plain link or as a record with its sizes."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        for k in ('original_image_url', 'resized_image_url', 'video_preview_image_url', 'watermarked_resized_image_url', 'url'):
            if isinstance(x.get(k), str) and x[k].startswith(('https://', 'http://')):
                return x[k]
    return ''


MEDIA_KEYS = {'images', 'videos', 'cards', 'extra_images', 'extra_videos'}


def ad_images(s: dict) -> list[str]:
    """Every picture of an ad: its images, the cover of each video, the picture of each carousel card or version
    (an ad with several versions keeps them as cards) and the extra pictures of a dynamic ad."""
    out = []
    for key in ('images', 'videos', 'cards', 'extra_images', 'extra_videos'):
        out += [_pic(i) for i in s.get(key) or []]
    return [u for u in dict.fromkeys(out) if u][:10]


def ad_cards(s: dict) -> list[dict]:
    """The cards of a carousel or dynamic ad, each with its own picture and words."""
    cards = []
    for c in s.get('cards') or []:
        if isinstance(c, dict) and (_pic(c) or c.get('title') or c.get('body')):
            cards.append({'image': _pic(c), 'title': str(c.get('title') or '')[:200], 'body': str(c.get('body') or '')[:400],
                          'cta': str(c.get('cta_text') or ''), 'link': str(c.get('link_url') or '')})
    return cards[:10]


async def ads(page_url: str, apify: Apify, max_usd: float, name: str = '') -> dict:
    rows, cost = await apify.run(actor('WATCH_ACTOR_ADS', 'jmlp~meta-ad-library-scraper'),
                                 {'pageIDs': [page_url], 'country': env('WATCH_ADS_COUNTRY', 'EG'), 'activeStatus': 'all',
                                  # Meta's own ad records: the tidy output leaves out the pictures of multi-version ads.
                                  'raw': env('WATCH_ADS_RAW', '1') != '0',
                                  'maxAds': int(env('WATCH_MAX_ADS', '30') or 30)}, max_usd, limit=60)
    rows = [x for x in rows if isinstance(x, dict) and x.get('ad_archive_id')]
    own = [x for x in rows if ad_is_theirs(x, page_url, name)]
    # The page's own ads all share one page id: also keep rows with that id whose name was shortened.
    ids = Counter(ad_page(x)[0] for x in own if ad_page(x)[0])
    if ids:
        top = ids.most_common(1)[0][0]
        own = [x for x in rows if x in own or ad_page(x)[0] == top]
        own = [x for x in own if not ad_page(x)[0] or ad_page(x)[0] == top]
    items = []
    for x in own:
        s = x.get('snapshot') if isinstance(x.get('snapshot'), dict) else {}
        body = s.get('body') if isinstance(s.get('body'), dict) else {}
        start, end = when(x.get('start_date')), when(x.get('end_date'))
        _, pname, puri = ad_page(x)
        items.append({'id': str(x['ad_archive_id']), 'active': bool(x.get('is_active')),
                      'start': start.date().isoformat() if start else None, 'end': end.date().isoformat() if end else None,
                      'platforms': [p.title() for p in x.get('publisher_platform') or [] if isinstance(p, str)],
                      'headline': (s.get('title') or '')[:300], 'body': (body.get('text') or '')[:1500],
                      'cta': s.get('cta_text') or '', 'landing': s.get('link_url') or '', 'format': s.get('display_format') or '',
                      'images': ad_images(s), 'cards': ad_cards(s),
                      'page_name': pname, 'page_url': puri,
                      'url': f"https://www.facebook.com/ads/library/?id={x['ad_archive_id']}"})
    likes = next((num((x.get('snapshot') or {}).get('page_like_count')) for x in own
                  if isinstance(x.get('snapshot'), dict) and x['snapshot'].get('page_like_count')), None)
    active = [a for a in items if a['active']]
    return {'text': '', 'fields': {}, 'items': items, 'cost': cost,
            'metrics': {'live_ads': len(active), 'ads_seen': len(items), 'page_likes': likes,
                        # Field names only (no values), to see where pictures are when an ad arrives without any.
                        'media_keys': sorted({k for x in own if isinstance(x.get('snapshot'), dict)
                                              for k in x['snapshot'] if k in MEDIA_KEYS or 'image' in k or 'video' in k
                                              or 'card' in k}) if items and not any(a['images'] for a in items) else [],
                        'other_pages_dropped': len(rows) - len(items),
                        'started_30d': sum(1 for a in active if a['start'] and
                                           datetime.fromisoformat(a['start']) >= datetime.utcnow() - timedelta(days=30))}}
