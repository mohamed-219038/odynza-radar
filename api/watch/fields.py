"""Rules only, no AI: which pages to watch, what to extract from a page, and what changed between two captures."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

# ---- Which pages to watch ------------------------------------------------------------------

PAGE_WORDS = {
    'pricing': ('pricing', 'prices', 'price', 'plans', 'plan', 'packages', 'subscribe', 'الأسعار', 'اسعار', 'باقات', 'الباقات'),
    'services': ('services', 'service', 'products', 'product', 'solutions', 'solution', 'features', 'platform',
                 'what-we-do', 'خدمات', 'خدماتنا', 'حلول', 'منتجات'),
    'clients': ('customers', 'clients', 'case-studies', 'case-study', 'case studies', 'success', 'portfolio',
                'our-work', 'partners', 'testimonials', 'عملاؤنا', 'عملائنا', 'العملاء', 'شركاؤنا'),
    'about': ('about', 'about-us', 'company', 'who-we-are', 'من نحن', 'عن الشركة'),
    'careers': ('careers', 'career', 'jobs', 'join-us', 'join', 'hiring', 'work-with-us', 'وظائف', 'الوظائف', 'انضم'),
    'news': ('blog', 'news', 'insights', 'press', 'articles', 'resources', 'مدونة', 'أخبار', 'المدونة'),
}
# What each tier watches on the website (Emerging: homepage only).
TIER_PAGES = {'direct': ('pricing', 'services', 'clients', 'about', 'careers', 'news'),
              'adjacent': ('pricing', 'services', 'clients', 'careers'),
              'aspirational': ('pricing', 'services', 'clients'),
              'emerging': (),
              'client': ('pricing', 'services', 'clients')}


# Legal and account pages never say anything about the offer, so they are never watched.
SKIP_PAGE = re.compile(r'(^|[\s/_-])(terms|tos|privacy|policy|policies|legal|cookies?|gdpr|refund|disclaimer|imprint|'
                       r'login|log-in|signin|sign-in|signup|sign-up|register|account|cart|checkout|sitemap)($|[\s/_.-])'
                       r'|شروط|الشروط|الخصوصية|سياسة|الأحكام|تسجيل', re.I)


def _kind_of(words: str) -> str | None:
    for kind, keys in PAGE_WORDS.items():
        for key in keys:
            if re.search(r'(^|[\s/_-])' + re.escape(key) + r'($|[\s/_.-])', words):
                return kind
    return None


def page_match(url: str, text: str = '') -> tuple[str | None, int]:
    """(kind, strength): 2 when the URL itself names the kind, 1 when only a short link text does."""
    path = urlsplit(url).path.lower().strip('/')
    text = (text or '').lower().strip()
    if SKIP_PAGE.search(path.replace('/', ' ')) or SKIP_PAGE.search(text):
        return None, 0
    kind = _kind_of(path.replace('/', ' '))
    if kind:
        return kind, 2
    if text and len(text.split()) <= 4:
        kind = _kind_of(text)
        if kind:
            return kind, 1
    return None, 0


def page_kind(url: str, text: str = '') -> str | None:
    return page_match(url, text)[0]


def propose_pages(html: str, base_url: str, tier: str = 'direct') -> list[dict]:
    """Homepage plus one link per wanted kind, chosen by link text and URL (same site only, shortest path wins)."""
    soup = BeautifulSoup(html or '', 'lxml')
    base = urlsplit(base_url)
    host = (base.hostname or '').removeprefix('www.')
    found: dict[str, str] = {}
    strength: dict[str, int] = {}
    for a in soup.find_all('a', href=True):
        full = urldefrag(urljoin(base_url, a['href']))[0]
        parts = urlsplit(full)
        if parts.scheme not in ('http', 'https') or (parts.hostname or '').removeprefix('www.') != host:
            continue
        if parts.path.strip('/') == '' or re.search(r'\.(pdf|jpg|jpeg|png|zip|docx?)$', parts.path, re.I):
            continue
        kind, power = page_match(full, a.get_text(' ', strip=True))
        if not kind or kind not in TIER_PAGES.get(tier, ()):
            continue
        clean = full.split('?')[0].rstrip('/')
        if clean in found.values() and found.get(kind) != clean:
            continue   # one page is watched once, under its first and strongest kind
        better = kind not in found or power > strength[kind] or \
            (power == strength[kind] and len(urlsplit(clean).path) < len(urlsplit(found[kind]).path))
        if better:
            found[kind], strength[kind] = clean, power
    pages = [{'page_kind': 'homepage', 'url': base_url.rstrip('/') or base_url}]
    pages += [{'page_kind': k, 'url': found[k]} for k in TIER_PAGES.get(tier, ()) if k in found]
    return pages


# ---- Extraction ----------------------------------------------------------------------------

CURRENCY = r'(?:EGP|E£|LE|L\.E\.?|ج\.م\.?|جنيه|USD|US\$|\$|€|EUR|£|GBP|SAR|ر\.س|AED|د\.إ)'
NUMBER = r'\d{1,3}(?:[,\s.]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?'
PRICE = re.compile(rf'({CURRENCY})\s?({NUMBER})|({NUMBER})\s?({CURRENCY})', re.I)
PERIOD = re.compile(r'(/|\bper\b|\ba\b)\s*(mo|month|monthly|yr|year|yearly|annum|user|seat)|شهري|شهر|سنوي|سنة', re.I)
NOISE_LINE = re.compile(r'^(©|copyright|all rights reserved|cookie|we use cookies|accept|privacy policy|terms)'
                        r'|^\W*$|^[\d\s.,:/-]+$|\b(19|20)\d{2}\b.*©', re.I)
NOISE_ATTR = re.compile(r'cookie|consent|gdpr|newsletter-popup|chat-widget|intercom', re.I)
JOB_WORDS = re.compile(r'\b(engineer|developer|manager|sales|designer|specialist|analyst|intern|lead|director|'
                       r'executive|consultant|scientist|architect|marketing|account|support|officer|coordinator)\b|'
                       r'مهندس|مطور|مدير|مبيعات|مصمم|أخصائي|محلل|متدرب', re.I)
CLIENT_CONTAINER = re.compile(r'client|customer|logo|partner|trusted|brand', re.I)


def norm(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip()


def price_number(value: str) -> float | None:
    m = re.search(NUMBER, value or '')
    if not m:
        return None
    raw = m.group(0).replace(' ', '')
    if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+', raw):     # 40,000 or 40.000
        raw = re.sub(r'[.,]', '', raw)
    else:
        raw = raw.replace(',', '')
    try:
        return float(raw)
    except ValueError:
        return None


def _plan_name(node) -> str:
    """The nearest heading in the same pricing card, looking up to five levels."""
    current = node
    for _ in range(5):
        current = current.parent
        if current is None or current.name in ('body', 'html', 'main'):
            break
        heading = current.find(['h1', 'h2', 'h3', 'h4', 'h5', 'strong', 'b'])
        if heading:
            name = norm(heading.get_text(' ', strip=True))
            if name and not PRICE.search(name) and len(name) <= 60:
                return name
    return ''


def extract(html: str, url: str, kind: str = 'homepage') -> dict:
    """Returns {'text': cleaned lines, 'fields': {...}}. The same input always gives the same output."""
    soup = BeautifulSoup(html or '', 'lxml')
    for tag in soup(['script', 'style', 'noscript', 'svg', 'nav', 'footer', 'iframe', 'template']):
        tag.decompose()
    for tag in soup.find_all(attrs={'id': NOISE_ATTR}) + soup.find_all(attrs={'class': NOISE_ATTR}):
        if not tag.decomposed:
            tag.decompose()
    root = soup.find('main') or soup.body or soup
    fields: dict = {}
    h1 = root.find('h1')
    if h1 and norm(h1.get_text(' ')):
        fields['headline'] = norm(h1.get_text(' '))[:200]
    headings = [norm(h.get_text(' ')) for h in root.find_all(['h2', 'h3'])]
    fields['headings'] = sorted({h[:160] for h in headings if 3 <= len(h) <= 160})[:60]
    buttons = [norm(b.get_text(' ')) for b in root.find_all(['button', 'a'])
               if 'btn' in ' '.join(b.get('class') or []).lower() or b.name == 'button']
    if buttons:
        fields['buttons'] = sorted({b for b in buttons if 2 <= len(b) <= 40})[:20]

    prices: dict[str, str] = {}
    for node in root.find_all(string=PRICE):
        text = norm(str(node))
        m = PRICE.search(text)
        if not m or len(text) > 140:
            continue
        value = norm(m.group(0))
        context = norm(node.parent.get_text(' ')) if node.parent else text
        period = PERIOD.search(context[:120])
        if period:
            value += ' / ' + period.group(0).strip('/ ').lower()
        plan = _plan_name(node) or f'price {len(prices) + 1}'
        key = plan
        n = 2
        while key in prices and prices[key] != value:
            key, n = f'{plan} ({n})', n + 1
        prices.setdefault(key, value)
    if prices:
        fields['prices'] = dict(list(prices.items())[:20])

    if kind in ('services', 'homepage'):
        items = [norm(h.get_text(' ')) for h in root.find_all(['h3', 'h4'])]
        if items:
            fields['services'] = sorted({i[:120] for i in items if 3 <= len(i) <= 120})[:60]
    if kind in ('clients', 'homepage'):
        logos = []
        for img in root.find_all('img'):
            alt = norm(img.get('alt') or img.get('title') or '')
            parent_text = ' '.join(' '.join(p.get('class') or []) + ' ' + (p.get('id') or '') for p in img.parents if p.name)
            if alt and 2 <= len(alt) <= 80 and (kind == 'clients' or CLIENT_CONTAINER.search(parent_text)):
                if not re.search(r'logo of us|our logo|icon|arrow|banner|hero', alt, re.I):
                    logos.append(re.sub(r'\s*(logo|شعار)\s*$', '', alt, flags=re.I))
        if logos:
            fields['clients'] = sorted(set(logos))[:80]
    if kind == 'careers':
        jobs = [norm(t.get_text(' ')) for t in root.find_all(['h2', 'h3', 'h4', 'a', 'li'])]
        jobs = [j for j in jobs if 4 <= len(j) <= 90 and JOB_WORDS.search(j)]
        fields['jobs'] = sorted(set(jobs))[:60]

    lines = []
    for line in root.get_text('\n').split('\n'):
        line = norm(line)
        if len(line) >= 3 and not NOISE_LINE.search(line):
            lines.append(line)
    lines = list(dict.fromkeys(lines))
    return {'text': '\n'.join(lines)[:60000], 'fields': fields}


def content_hash(text: str, fields: dict, metrics: dict | None = None, items: list | None = None) -> str:
    """Counters that always move (post likes) are left out of the hash so an unchanged account is not stored daily."""
    stable_items = [{k: v for k, v in i.items() if k in ('id', 'url', 'caption', 'headline', 'body')} for i in (items or [])]
    stable_metrics = {k: v for k, v in (metrics or {}).items() if k in ('bio', 'name')}
    blob = json.dumps([text, fields, stable_metrics, stable_items], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


# ---- Change detection -------------------------------------------------------------------------

LIST_FIELDS = {'headings': 'Heading', 'services': 'Service', 'clients': 'Client', 'jobs': 'Job', 'buttons': 'Button'}


def fingerprint(competitor_id, field: str, kind: str, before, after) -> str:
    key = json.dumps([competitor_id, field.split(':')[0], kind, norm(str(before or '')).lower(),
                      norm(str(after or '')).lower()], ensure_ascii=False)
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _change(field, kind, before, after):
    return {'field': field, 'kind': kind, 'before': None if before is None else str(before)[:2000],
            'after': None if after is None else str(after)[:2000]}


def page_changes(old: dict, new: dict) -> list[dict]:
    """Fields first (prices, lists, headline), then text lines the fields did not explain."""
    out = []
    of, nf = old.get('fields') or {}, new.get('fields') or {}
    if of.get('headline') != nf.get('headline') and (of.get('headline') or nf.get('headline')):
        out.append(_change('headline', 'changed' if of.get('headline') and nf.get('headline') else
                           ('added' if nf.get('headline') else 'removed'), of.get('headline'), nf.get('headline')))
    op, np_ = of.get('prices') or {}, nf.get('prices') or {}
    for plan in sorted(set(op) | set(np_)):
        a, b = op.get(plan), np_.get(plan)
        if a == b:
            continue
        kind = 'changed' if a and b else ('added' if b else 'removed')
        change = _change(f'price:{plan}', kind, a, b)
        x, y = price_number(a or ''), price_number(b or '')
        if x and y:
            change['delta_pct'] = round((y - x) / x * 100, 1)
        out.append(change)
    for name, label in LIST_FIELDS.items():
        a, b = set(of.get(name) or []), set(nf.get(name) or [])
        if not a and not b:
            continue
        if a and b and len(a ^ b) > max(8, 0.6 * max(len(a), len(b))):
            out.append(_change(f'{name}:redesign', 'changed', f'{len(a)} {label.lower()} items', f'{len(b)} {label.lower()} items'))
            continue
        out += [_change(f'{name}:{label}', 'added', None, v) for v in sorted(b - a)]
        out += [_change(f'{name}:{label}', 'removed', v, None) for v in sorted(a - b)]
    explained = {norm(c['after'] or c['before'] or '').lower() for c in out}
    old_lines = [l for l in (old.get('text') or '').split('\n') if len(l) >= 25]
    new_lines = [l for l in (new.get('text') or '').split('\n') if len(l) >= 25]
    added = [l for l in new_lines if l not in set(old_lines) and l.lower() not in explained]
    removed = [l for l in old_lines if l not in set(new_lines) and l.lower() not in explained]
    if old_lines and (len(added) + len(removed)) > max(12, 0.5 * len(old_lines)):
        out.append(_change('text:rewrite', 'changed', f'{len(old_lines)} lines', f'{len(new_lines)} lines, '
                           f'{len(added)} new'))
    else:
        out += [_change('text', 'added', None, l) for l in added[:10]]
        out += [_change('text', 'removed', l, None) for l in removed[:10]]
    return out


def _older_than(value, days: int) -> bool:
    from datetime import datetime, timedelta, timezone
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return False
    now = datetime.now(d.tzinfo) if d.tzinfo else datetime.utcnow()
    return now - d > timedelta(days=days)


def social_changes(old: dict, new: dict) -> list[dict]:
    """Bio, a follower jump of 5% or more, posting pace that halves or doubles, and new posts that clearly outperform."""
    out = []
    om, nm = old.get('metrics') or {}, new.get('metrics') or {}
    if om.get('bio') != nm.get('bio') and nm.get('bio') is not None and om.get('bio') is not None:
        out.append(_change('bio', 'changed', om.get('bio'), nm.get('bio')))
    a, b = om.get('followers'), nm.get('followers')
    if a and b and abs(b - a) / a >= 0.05:
        c = _change('followers', 'changed', a, b)
        c['delta_pct'] = round((b - a) / a * 100, 1)
        out.append(c)
    a, b = om.get('posts_per_week'), nm.get('posts_per_week')
    if a is not None and b is not None and (a or b) and (b >= 2 * max(a, 0.5) or b <= a / 2):
        out.append(_change('posting_pace', 'changed', f'{a} posts a week', f'{b} posts a week'))
    seen = {i.get('id') or i.get('url') for i in old.get('items') or []}
    avg = nm.get('avg_engagement') or 0
    for post in new.get('items') or []:
        key = post.get('id') or post.get('url')
        if key in seen or _older_than(post.get('date'), days=14):   # an older post found by a deeper scrape is not news
            continue
        eng = post.get('engagement_total') or 0
        if avg and eng >= 2 * avg and eng >= 20:
            out.append(_change('top_post', 'added', None, f"{post.get('format', 'post')}: {norm(post.get('caption', ''))[:300]} "
                               f"({eng} interactions, {round(eng / avg, 1)}× their average) {post.get('url', '')}"))
    return out


def mention_changes(old: dict, new: dict, cap: int = 8) -> list[dict]:
    """A web or news result about the company that was not there before. Results seen once are remembered, so an
    article that drops out of the top results and comes back is not counted again."""
    om = old.get('metrics') or {}
    seen = set(om.get('seen') or []) | {i.get('id') for i in old.get('items') or []}
    fresh = [i for i in new.get('items') or [] if i.get('id') not in seen]
    new.setdefault('metrics', {})['seen'] = (list(om.get('seen') or []) + [i['id'] for i in new.get('items') or []
                                                                           if i.get('id') not in (om.get('seen') or [])])[-400:]
    return [_change('mention', 'added', None, norm(f"{'News' if i.get('kind') == 'news' else 'Web'} · {i.get('site', '')}"
                                                     f"{' · ' + i['date'] if i.get('date') else ''}: {i.get('title', '')}. "
                                                     f"{i.get('snippet', '')}")[:600] + f" {i.get('url', '')}")
            for i in fresh[:cap]]


def ad_changes(old: dict, new: dict) -> list[dict]:
    """Each ad is stored by its Ad Library id: a new id is a new ad, an id gone from the active list has stopped."""
    out = []
    before = {a['id']: a for a in old.get('items') or [] if a.get('active')}
    after = {a['id']: a for a in new.get('items') or [] if a.get('active')}
    describe = lambda a: norm(f"{a.get('headline') or ''} — {a.get('body') or ''}".strip(' —'))[:500] + \
        (f" (CTA: {a['cta']})" if a.get('cta') else '') + (f" → {a['landing']}" if a.get('landing') else '')
    out += [_change('ad', 'added', None, describe(after[i])) for i in after if i not in before]
    out += [_change('ad', 'removed', describe(before[i]), None) for i in before if i not in after]
    return out


# ---- Images -----------------------------------------------------------------------------------

SKIP_IMAGE = re.compile(r'pixel|spacer|tracking|blank\.|1x1|sprite|loader|spinner|emoji|/flags?/|arrow|chevron|caret|data:|gravatar|facebook\.com/tr', re.I)
LOGO_HINT = re.compile(r'logo|brand', re.I)
CLIENT_WORDS = re.compile(r'client|customer|trusted|brands? (we|that)|worked with|who uses|used by|success|case stud|portfolio|testimonial|'
                          r'عملاء|عملاؤنا|عملائنا|يثق|شركات تثق', re.I)
PARTNER_WORDS = re.compile(r'partner|integrat|certif|technolog|powered by|accredit|member of|شريك|شركاء|شركاؤنا|معتمد', re.I)
PRODUCT_WORDS = re.compile(r'screenshot|dashboard|mockup|mock-up|interface|\bui\b|\bapp\b|product|feature|screen|demo|preview|لوحة|تطبيق|منتج', re.I)
TEAM_WORDS = re.compile(r'team|founder|ceo|cto|people|staff|portrait|headshot|avatar|member|فريق|مؤسس', re.I)
BG_URL = re.compile(r'background(?:-image)?\s*:[^;]*url\(\s*[\'"]?([^\'")]+)', re.I)
PICTURE_KINDS = {'brand_logo': 'Brand logo', 'client_logo': 'Client logo', 'partner_logo': 'Partner logo', 'logo': 'Other company logo',
                 'product': 'Product screenshot', 'team': 'Team photo', 'banner': 'Banner', 'other': 'Picture'}


def _src(img) -> str:
    src = ''
    for key in ('src', 'data-src', 'data-lazy-src', 'data-original'):
        v = (img.get(key) or '').strip()
        if v and not v.startswith('data:'):
            src = v
            break
    if not src:
        sets = img.get('srcset') or img.get('data-srcset') or ''
        if not sets and img.parent is not None and img.parent.name == 'picture':
            source = img.parent.find('source')
            sets = (source.get('srcset') or source.get('data-srcset') or '') if source else ''
        if sets:
            src = sets.split(',')[0].strip().split(' ')[0]
    if '/_next/image' in src and 'url=' in src:   # Next.js serves pictures through its resizer; keep the original
        from urllib.parse import parse_qs, unquote
        inner = parse_qs(urlsplit(src).query).get('url', [''])[0]
        src = unquote(inner) or src
    return src.strip()


def _heading(tag):
    """The nearest heading above a picture: the title of the section it sits in."""
    h = tag.find_previous(['h1', 'h2', 'h3', 'h4'])
    return norm(h.get_text(' ', strip=True))[:160] if h else ''


def _near(tag) -> str:
    """A little of the text around a picture: its caption, or the words of the smallest block that has some."""
    fig = tag.find_parent('figure')
    if fig is not None and fig.find('figcaption'):
        return norm(fig.find('figcaption').get_text(' ', strip=True))[:220]
    node = tag.parent
    for _ in range(4):
        if node is None or node.name in ('body', 'html', 'main', '[document]'):
            break
        text = norm(node.get_text(' ', strip=True))
        if len(text) >= 30:
            return text[:220]
        node = node.parent
    return ''


def _name_from(url: str, alt: str) -> str:
    if alt:
        return alt
    stem = urlsplit(url).path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    stem = re.sub(r'[-_]+|%20', ' ', stem)
    stem = re.sub(r'\b(logo|img|image|copy|final|white|black|dark|light|color|colour|\d+x\d+|@\dx|v\d+)\b', ' ', stem, flags=re.I)
    words = [w for w in stem.split() if not re.fullmatch(r'[0-9a-f]{6,}|\d+', w, re.I)]
    return ' '.join(words)[:80]


def _in_logo_strip(el) -> bool:
    """A row of four or more small pictures with almost no words between them: how sites show client and partner logos."""
    box = el.parent
    for _ in range(3):
        if box is None or box.name in ('body', 'html', 'main', '[document]'):
            return False
        imgs = box.find_all('img', limit=40)
        if len(imgs) >= 4:
            return len(norm(box.get_text(' ', strip=True))) <= 25 * len(imgs)
        box = box.parent
    return False


def label_picture(url: str, alt: str, hint: str, heading: str, near: str, in_header: bool, strip: bool, page_kind: str = '') -> str:
    """What a picture shows, from page clues only: where it sits, the heading above it, its name and its alt text."""
    hint_all = f'{alt} {hint} {url}'
    looks_logo = bool(LOGO_HINT.search(hint_all)) or url.lower().split('?')[0].endswith('.svg') or strip
    if in_header and looks_logo:
        return 'brand_logo'
    if looks_logo:
        for clue in (hint_all, heading, near[:160]):   # the closest clue wins: the picture itself, then its heading
            partner, client = PARTNER_WORDS.search(clue), CLIENT_WORDS.search(clue)
            if partner and not client:
                return 'partner_logo'
            if client and not partner:
                return 'client_logo'
        return 'client_logo' if page_kind == 'clients' else 'logo'
    if TEAM_WORDS.search(hint_all) or TEAM_WORDS.search(heading):
        return 'team'
    if PRODUCT_WORDS.search(hint_all):
        return 'product'
    return 'other'


def page_images(html: str, url: str, page_kind: str = '') -> dict:
    """The site's logo, its main pictures (share picture first) and every picture with what it shows and the text it
    belongs to. Kept in metrics, not fields, so a new CDN link never counts as a change on the page."""
    soup = BeautifulSoup(html or '', 'lxml')
    logo, images, pictures, seen = None, [], [], set()
    for tag in soup.find_all('meta'):
        if (tag.get('property') or tag.get('name') or '').lower() in ('og:image', 'twitter:image') and tag.get('content'):
            full = urljoin(url, tag['content'].strip())
            images.append(full)
            if full not in seen:
                seen.add(full)
                pictures.append({'url': full, 'kind': 'banner', 'label': PICTURE_KINDS['banner'], 'name': 'Share picture of the page',
                                 'heading': '', 'near': ''})
    found = [(img, _src(img)) for img in soup.find_all('img')]
    found += [(el, m.group(1)) for el in soup.find_all(style=BG_URL) for m in [BG_URL.search(el.get('style') or '')] if m]
    for el, src in found:
        if not src:
            continue
        full = urljoin(url, src)
        if not full.startswith(('https://', 'http://')) or SKIP_IMAGE.search(full) or full in seen:
            continue
        dims = [int(v) for v in (el.get('width'), el.get('height')) if str(v or '').isdigit()]
        if dims and max(dims) < 32:
            continue
        alt = norm(el.get('alt') or el.get('title') or el.get('aria-label') or '')[:160]
        hint = ' '.join([' '.join(el.get('class') or []), el.get('id') or ''] +
                        [' '.join(p.get('class') or []) for p in list(el.parents)[:2] if p is not None and p.name])
        in_header = el.find_parent(['header', 'nav']) is not None
        strip = _in_logo_strip(el)
        heading, near = _heading(el), _near(el)
        kind = label_picture(full, alt, hint, heading, near, in_header, strip, page_kind)
        if kind == 'brand_logo' and logo is None:
            logo = full
        seen.add(full)
        name = _name_from(full, alt)
        pictures.append({'url': full, 'kind': kind, 'label': PICTURE_KINDS[kind], 'heading': heading, 'near': near,
                         'name': (f"{PICTURE_KINDS[kind]}: {name}" if name else PICTURE_KINDS[kind])[:160]})
        if kind not in ('brand_logo', 'client_logo', 'partner_logo', 'logo'):
            images.append(full)
    images = [i for i in dict.fromkeys(images) if i.startswith(('https://', 'http://'))][:16]
    pictures = pictures[:40]
    out = {'images': images, 'pictures': pictures, 'sections': _sections(soup, pictures)}
    if logo and logo.startswith(('https://', 'http://')):
        out['logo'] = logo
    return out


def _sections(soup, pictures: list[dict]) -> list[dict]:
    """The page cut at its headings, each part with its words and the pictures that sit under that heading."""
    out = []
    for h in soup.find_all(['h1', 'h2', 'h3']):
        title = norm(h.get_text(' ', strip=True))[:160]
        if not title or any(s['heading'] == title for s in out):
            continue
        words = []
        for el in h.find_all_next(string=True):
            if el.find_parent(['h1', 'h2', 'h3']) is not None and el.find_parent(['h1', 'h2', 'h3']) is not h:
                break
            if el.find_parent(['script', 'style', 'noscript']) is not None or el.find_parent(['h1', 'h2', 'h3']) is h:
                continue
            t = norm(str(el))
            if t:
                words.append(t)
            if sum(len(w) for w in words) > 420:
                break
        pics = [p['url'] for p in pictures if p['heading'] == title]
        out.append({'heading': title, 'text': ' '.join(words)[:420], 'pictures': pics})
        if len(out) >= 20:
            break
    return out
