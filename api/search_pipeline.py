"""Building blocks for company and competitor search.

- A persistent cache (SQLite table discovery_cache) for company profiles, homepage reads and finished searches.
- Parallel Serper (Google results API) searches, including Arabic queries for Arabic-speaking markets.
- Rule-based cleanup that removes directories, news, job and social sites, articles, duplicates and the
  user's own company before any website is read or any model is asked.
"""
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy.exc import SQLAlchemyError

from api.competitors import (DIRECTORY_HOSTS, MARKETS, clean_terms, homepage, host, local_site, market_info,
                             official_social, same_site)
from api.gemini import GeminiError

PROFILE_TTL = timedelta(days=7)
PAGE_TTL = timedelta(days=3)
RESULT_TTL = timedelta(days=1)


# ---- Persistent cache -----------------------------------------------------------------------

def cache_key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def enabled():
    # DISCOVERY_CACHE=0 turns the cache off (the tests do this so they never touch the real database).
    return os.getenv('DISCOVERY_CACHE', '1').strip() != '0'


def _cache_get(key, max_age):
    from db.database import SessionLocal, DiscoveryCache
    try:
        with SessionLocal() as db:
            row = db.get(DiscoveryCache, key)
            if row is not None and row.created_at >= datetime.utcnow() - max_age:
                return row.value
    except SQLAlchemyError:
        pass
    return None


def _cache_put(key, kind, value):
    from db.database import SessionLocal, DiscoveryCache
    try:
        with SessionLocal() as db:
            db.merge(DiscoveryCache(key=key, kind=kind, value=value, created_at=datetime.utcnow()))
            db.commit()
    except SQLAlchemyError:
        pass  # The cache only saves time; a failed write never fails the search.


async def cache_get(key, max_age):
    return await asyncio.to_thread(_cache_get, key, max_age) if enabled() else None


async def cache_put(key, kind, value):
    if enabled():
        await asyncio.to_thread(_cache_put, key, kind, value)


# ---- Markets and queries --------------------------------------------------------------------

# country words -> (Google country code, Arabic name). Arabic queries are added only for these markets.
def identify_searches(name, context):
    gl, _ = market_info(context)
    name, context = clean_terms(name, 12), clean_terms(context, 12)
    searches = [{'q': f'{name} {context} official website'.strip()}, {'q': f'"{name}" {context}'.strip()},
                {'q': f'{name} {context} LinkedIn Facebook Instagram'.strip()}]
    return [{**s, 'gl': gl} if gl else s for s in searches]


def competitor_searches(request, profile):
    """Focused searches: category in the market and in Arabic first (location comes first), then worldwide ones."""
    market = profile.get('market', '')
    gl, arabic_market = market_info(market, request.context)
    local = request.market_scope != 'global' and bool(market)
    local_searches, world = [], []
    for offering in profile.get('offerings', [])[:2]:
        category = offering['search_terms']
        if local:
            local_searches.append({'q': f'{category} companies {market}', **({'gl': gl} if gl else {})})
            arabic = offering.get('search_terms_ar')
            if arabic_market and arabic:
                local_searches.append({'q': f'شركات {arabic} في {arabic_market}', 'gl': gl, 'hl': 'ar'})
        if request.market_scope != 'local_only':
            world.append({'q': f'{category} companies'})
            world.append({'q': f'{category} alternatives'})
    name = clean_terms(request.company_name, 12)
    searches = local_searches + [{'q': f'"{name}" competitors alternatives', **({'gl': gl} if gl and local else {})}] + world
    unique = {json.dumps(s, sort_keys=True, ensure_ascii=False): s for s in searches}
    return list(unique.values())[:8]


# ---- Serper ---------------------------------------------------------------------------------

SERPER_URL = 'https://google.serper.dev/search'


async def serper_search(client, key, searches):
    """Run every search at once. Returns appearances [(search index, rank, hit)]; one failed query is skipped."""
    async def one(search):
        response = await client.post(SERPER_URL, headers={'X-API-KEY': key}, json={'num': 10, **search})
        if response.status_code in (401, 403):
            raise GeminiError('Serper rejected SERPER_API_KEY. Check the key in .env.')
        if response.status_code in (402, 429):
            raise GeminiError('Serper credits or rate limit are exhausted. Check your Serper dashboard.')
        if response.status_code >= 400:
            return []
        body = response.json()
        return (body.get('organic') or []) if isinstance(body, dict) else []
    results = await asyncio.gather(*(one(s) for s in searches), return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]
    if failures and len(failures) == len(results):
        raise failures[0] if isinstance(failures[0], GeminiError) else GeminiError('Serper search could not be reached.')
    appearances = []
    for index, rows in enumerate(results):
        if isinstance(rows, BaseException):
            continue
        for rank, row in enumerate(rows[:10]):
            link = row.get('link') if isinstance(row, dict) else None
            try:
                parsed = urlsplit(link or '')
            except ValueError:
                continue
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                continue
            appearances.append((index, rank, {'url': link, 'title': str(row.get('title', ''))[:180],
                                              'description': str(row.get('snippet', ''))[:500]}))
    return appearances


def search_hits(appearances):
    """Unique result pages for the 'All web search results' list, with source IDs."""
    hits, seen = [], set()
    for _, _, hit in sorted(appearances, key=lambda a: (a[1], a[0])):
        if hit['url'] not in seen:
            seen.add(hit['url'])
            hits.append({**hit, 'source_id': len(hits) + 1})
    return hits[:40]


# ---- Cleanup --------------------------------------------------------------------------------

NOT_COMPANIES = {
    'wikipedia.org', 'medium.com', 'reddit.com', 'quora.com', 'forbes.com', 'techcrunch.com', 'wamda.com', 'zawya.com',
    'magnitt.com', 'menabytes.com', 'startupscene.me', 'enterprise.press', 'dailynewsegypt.com', 'egypttoday.com',
    'ahram.org.eg', 'youm7.com', 'masrawy.com', 'almasryalyoum.com', 'arabnews.com', 'gulfnews.com', 'thenationalnews.com',
    'reuters.com', 'cnbc.com', 'wsj.com', 'ft.com', 'businesswire.com', 'prnewswire.com', 'globenewswire.com',
    'wuzzuf.net', 'indeed.com', 'bayt.com', 'naukrigulf.com', 'tracxn.com', 'pitchbook.com', 'owler.com', 'cbinsights.com',
    'similarweb.com', 'dnb.com', 'apollo.io', 'rocketreach.co', 'apps.apple.com', 'play.google.com', 'amazon.com',
    'yelp.com', 'tripadvisor.com', 'yellowpages.com.eg', 'gartner.com', 'softwareadvice.com', 'sourceforge.net',
    'producthunt.com', 'f6s.com', 'slideshare.net', 'scribd.com', 'pinterest.com', 'github.com', 'fiverr.com',
    'upwork.com', 'blogspot.com', 'wordpress.com', 'substack.com', 'researchgate.net', 'statista.com', 'trustpilot.com',
    'ensun.io', 'seedtable.com', 'builtin.com', 'failory.com', 'startupblink.com', 'vc4a.com', 'disrupt-africa.com',
}
NOT_COMPANY_SUFFIXES = ('.gov', '.gov.eg', '.gov.sa', '.gov.ae', '.edu', '.edu.eg', '.ac.uk')
ARTICLE = re.compile(r'(?<!\w)(top \d+|top|best|list of|leading|alternatives to|vs|versus|reviews?|ranking|'
                     r'companies in|startups in|أفضل|أهم|قائمة)(?!\w)', re.IGNORECASE)
SOCIAL_HOSTS = {'facebook.com': 'facebook', 'instagram.com': 'instagram', 'linkedin.com': 'linkedin'}


def not_a_company(domain):
    blocked = DIRECTORY_HOSTS | NOT_COMPANIES
    return (not domain or any(domain == d or domain.endswith('.' + d) for d in blocked)
            or domain.endswith(NOT_COMPANY_SUFFIXES))


def compact(value):
    return re.sub(r'\W', '', str(value or '')).casefold()


def name_from_title(title, domain):
    """The brand part of a page title ('Paymob | Online payments' -> 'Paymob'), else the domain label."""
    label = domain.split('.')[0]
    parts = [p.strip() for p in re.split(r'\s+[|\-–—:·•]\s+|\s*\|\s*', title or '') if p.strip()]
    for part in parts:
        if len(part) <= 60 and compact(label) and (compact(label) in compact(part) or compact(part) in compact(label)):
            return part
    # Short domain labels are usually acronyms (bcg.com -> BCG, not Bcg).
    return label.upper() if len(label) <= 4 else label.replace('-', ' ').title()


def article_page(hit):
    path = urlsplit(hit['url']).path.strip('/')
    return bool(path) and bool(ARTICLE.search(hit['title']))


def rank_competitor_candidates(appearances, grounded, request, limit, searches=None, market=''):
    """Score each company domain by how often and how high it ranked, plus a bonus for Gemini's Google suggestions.

    Location comes first: outside a worldwide search, results of searches in the market and country domains
    (.eg, .com.eg) count three times as much, so local companies are the ones whose websites get read and verified.
    """
    own_name = compact(request.company_name)
    local = request.market_scope != 'global'
    local_index = {i for i, s in enumerate(searches or []) if s.get('gl')} if local else set()
    entries = {}
    for index, rank, hit in appearances:
        domain = host(hit['url'])
        if not_a_company(domain) or same_site(hit['url'], request.website) or article_page(hit):
            continue
        entry = entries.setdefault(domain, {'name': name_from_title(hit['title'], domain), 'website': homepage(hit['url']),
                                            'score': 0.0, 'searches': set(), 'found_by': ['web search'], 'reason': ''})
        entry['score'] += (3 if index in local_index else 1) / (rank + 1)
        entry['searches'].add(index)
    for item in grounded:
        domain = host(item['website'])
        if not_a_company(domain) or same_site(item['website'], request.website):
            continue
        entry = entries.setdefault(domain, {'name': item['name'], 'website': item['website'], 'score': 0.0,
                                            'searches': set(), 'found_by': [], 'reason': item.get('reason', '')})
        entry['name'], entry['reason'] = item['name'], item.get('reason', '') or entry['reason']
        entry['score'] += 1.5
        entry['found_by'].append('Google AI search')
    ranked = []
    for domain, entry in entries.items():
        if len(own_name) >= 4 and (own_name in compact(domain.split('.')[0]) or compact(entry['name']) == own_name):
            continue
        entry['score'] += 0.5 * len(entry['searches'])
        if local and local_site(entry['website'], market):
            entry['score'] += 1.5
        ranked.append({k: v for k, v in entry.items() if k != 'searches'})
    ranked.sort(key=lambda e: e['score'], reverse=True)
    names, out = set(), []
    for entry in ranked:
        if compact(entry['name']) in names or not entry['website']:
            continue
        names.add(compact(entry['name']))
        out.append(entry)
    return out[:limit]


def identify_candidates(appearances, grounded, name):
    """Official-site candidates whose domain or title carries the company name, best first, plus social links."""
    words = [w for w in re.findall(r'\w+', name.casefold()) if len(w) >= 3]
    key = compact(name)
    def named(text):
        value = str(text or '').casefold()
        return (len(key) >= 3 and key in compact(value)) or (words and all(w in value for w in words[:2]))
    entries, socials = {}, {}
    for index, rank, hit in appearances:
        domain = host(hit['url'])
        channel = next((c for h, c in SOCIAL_HOSTS.items() if domain == h or domain.endswith('.' + h)), None)
        if channel:
            link = official_social(channel, hit['url'])
            if link and named(hit['title'] + ' ' + hit['url']):
                socials.setdefault(channel, link)
            continue
        if not_a_company(domain) or not named(domain + ' ' + hit['title']):
            continue
        entry = entries.setdefault(domain, {'name': name_from_title(hit['title'], domain), 'website': homepage(hit['url']),
                                            'description': hit['description'][:300], 'score': 0.0,
                                            'facebook': '', 'instagram': '', 'linkedin': ''})
        entry['score'] += 1 / (rank + 1) + (1 if key and key in compact(domain) else 0)
    for item in grounded:
        domain = host(item['website'])
        entry = entries.setdefault(domain, {**item, 'score': 0.0})
        entry['name'] = item['name']
        entry['score'] += 1.5
        for channel in ('facebook', 'instagram', 'linkedin'):
            entry[channel] = entry.get(channel) or item.get(channel, '')
        entry['description'] = entry.get('description') or item.get('description', '')
    ranked = sorted(entries.values(), key=lambda e: e['score'], reverse=True)[:4]
    return [{k: v for k, v in e.items() if k != 'score'} for e in ranked], socials


def social_searches(candidates, limit=5):
    """One site search per profile the company's own website does not publish (missing, or only suggested by search),
    for the first `limit` companies: [(candidate index, channel, search)]."""
    sites = {'linkedin': 'linkedin.com/company', 'instagram': 'instagram.com', 'facebook': 'facebook.com'}
    planned = []
    for index, c in enumerate(candidates[:limit]):
        name = clean_terms(c['name'], 8)
        for channel, site in sites.items():
            if name and (c.get('social_checks') or {}).get(channel) != 'on_website':
                planned.append((index, channel, {'q': f'site:{site} "{name}"'}))
    return planned



