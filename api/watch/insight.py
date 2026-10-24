"""Rule-based views over stored captures: scorecard (you vs the set), content gaps, claim map status and movement
alerts. No AI here; themes and claims come from the n8n stages and are only counted."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from db.watch_models import (WatchAlert, WatchChange, WatchClaim, WatchClient, WatchCompetitor, WatchScore,
                             WatchSignal, WatchSnapshot, WatchSource)

STARTER_CLAIMS = ['Fastest setup', 'Lowest price', 'Enterprise security', 'Arabic-first support', 'Industry case studies',
                  'Custom AI for your data', 'Local Egyptian team', 'Integrations with your tools', 'Measurable ROI',
                  '24/7 support', 'Easy to use / no code', 'Proven at scale']
SOCIAL = ('instagram', 'facebook', 'linkedin')
DISCOUNT = re.compile(r'\b\d{1,2}\s?%\s?(off|discount)|\bdiscount|\bfree (first )?month|\bsale\b|\boffer\b|خصم|عرض|مجان', re.I)


def companies(db: Session, client: WatchClient) -> list[dict]:
    """The client first, then confirmed competitors (direct first)."""
    order = {'direct': 0, 'adjacent': 1, 'aspirational': 2, 'emerging': 3}
    comps = db.query(WatchCompetitor).filter_by(client_id=client.id, status='confirmed').all()
    comps.sort(key=lambda c: (order.get(c.tier, 9), c.name.lower()))
    return [{'key': 'client', 'id': None, 'name': client.name, 'tier': 'you', 'you': True}] + \
        [{'key': str(c.id), 'id': c.id, 'name': c.name, 'tier': c.tier, 'you': False} for c in comps]


def latest(db: Session, client_id: int) -> dict:
    """{company key: {kind: latest snapshot}} for the newest capture of each source (one per kind; pages by page kind)."""
    out: dict = defaultdict(dict)
    for s in db.query(WatchSource).filter_by(client_id=client_id, enabled=True).all():
        snap = (db.query(WatchSnapshot).filter_by(source_id=s.id)
                .order_by(WatchSnapshot.captured_at.desc(), WatchSnapshot.id.desc()).first())
        if snap is None:
            continue
        key = 'client' if s.competitor_id is None else str(s.competitor_id)
        name = s.kind if s.kind != 'page' else f'page:{s.page_kind or "homepage"}'
        out[key][name] = {'snapshot': snap, 'source': s}
    return out


def scorecard(db: Session, client: WatchClient) -> dict:
    data = latest(db, client.id)
    rows = []
    for c in companies(db, client):
        snaps = data.get(c['key'], {})
        row = {**c, 'platforms': {}}
        for kind in SOCIAL:
            if kind in snaps:
                m = snaps[kind]['snapshot'].metrics or {}
                row['platforms'][kind] = {k: m.get(k) for k in ('followers', 'engagement_rate', 'posts_per_week', 'posts_30d',
                                                                  'days_since_last_post', 'format_mix', 'shares_public')}
                row['platforms'][kind]['captured_at'] = snaps[kind]['snapshot'].captured_at
        ads = snaps.get('ads')
        if ads and any('page_name' not in a for a in ads['snapshot'].items or []):
            ads = None   # saved before ads were checked against the page
        row['live_ads'] = (ads['snapshot'].metrics or {}).get('live_ads') if ads else None
        row['ads_started_30d'] = (ads['snapshot'].metrics or {}).get('started_30d') if ads else None
        rows.append(row)
    return {'rows': rows, 'note': 'Engagement rate leads, not followers. Instagram shares are not public, so Instagram '
                                  'engagement rate counts likes and comments only.'}


def content_gaps(db: Session, client: WatchClient) -> list[dict]:
    """Formats, posting slots, platforms and themes where at least two rivals are active and the client is not."""
    data = latest(db, client.id)
    rivals = [k for k in data if k != 'client']
    names = {c['key']: c['name'] for c in companies(db, client)}
    mine = data.get('client', {})
    gaps = []

    def add(kind, label, who, detail):
        if len(who) >= 2:
            gaps.append({'kind': kind, 'label': label, 'rivals': [names.get(w, w) for w in who], 'detail': detail})

    for platform in SOCIAL:
        who = [r for r in rivals if platform in data[r]]
        if platform not in mine:
            add('platform', platform.title(), who, f'{len(who)} rivals post on {platform.title()} and you are not watched there.')
            continue
        my_formats = (mine[platform]['snapshot'].metrics or {}).get('format_mix') or {}
        my_slots = (mine[platform]['snapshot'].metrics or {}).get('slots') or {}
        formats, slots = defaultdict(list), defaultdict(list)
        for r in who:
            m = data[r][platform]['snapshot'].metrics or {}
            for f, n in (m.get('format_mix') or {}).items():
                if n:
                    formats[f].append(r)
            for slot in (m.get('slots') or {}):
                slots[slot].append(r)
        for f, who_f in formats.items():
            if not my_formats.get(f):
                add('format', f'{f.title()} on {platform.title()}', who_f,
                    f'{len(who_f)} rivals post {f}s on {platform.title()} in the last 30 days. You posted none.')
        top = sorted(slots.items(), key=lambda kv: len(kv[1]), reverse=True)[:3]
        for slot, who_s in top:
            if not my_slots.get(slot):
                add('timing', f'{slot} on {platform.title()}', who_s,
                    f'{len(who_s)} rivals post on {slot} (Cairo time). You do not post then.')
    month = datetime.utcnow() - timedelta(days=30)
    themes = defaultdict(set)
    for s in db.query(WatchSignal).filter(WatchSignal.client_id == client.id, WatchSignal.created_at >= month).all():
        if s.theme:
            themes[s.theme.strip().lower()].add('client' if s.competitor_id is None else str(s.competitor_id))
    for theme, who in themes.items():
        if 'client' not in who:
            add('theme', theme.capitalize(), sorted(who), f'{len(who)} rivals put out content about {theme} this month.')
    return gaps[:12]


def claim_map(db: Session, client: WatchClient) -> list[dict]:
    rows = db.query(WatchClaim).filter_by(client_id=client.id).order_by(WatchClaim.label).all()
    confirmed = {str(c.id) for c in db.query(WatchCompetitor).filter_by(client_id=client.id, status='confirmed')}
    out = []
    for r in rows:
        holders = {k: v for k, v in (r.holders or {}).items() if k == 'client' or k in confirmed}
        rivals = [k for k in holders if k != 'client']
        status = 'crowded' if len(rivals) >= 3 else 'unclaimed' if not rivals else 'contested'
        out.append({'id': r.id, 'label': r.label, 'synonyms': r.synonyms or [], 'holders': holders,
                    'client_claims': 'client' in holders, 'status': status, 'rival_count': len(rivals)})
    return out


def effective_score(score: WatchScore | None) -> int | None:
    if score is None:
        return None
    return score.corrected_score or score.score


def week_key(day: date | None = None) -> str:
    day = day or date.today()
    return (day - timedelta(days=day.weekday())).isoformat()


def run_alerts(db: Session, client: WatchClient) -> list[WatchAlert]:
    """F19 rules. One alert per rule, competitor and week."""
    week = week_key()
    made = []
    data = latest(db, client.id)
    since = datetime.utcnow() - timedelta(days=30)

    def fire(rule, comp_id, message):
        key = f'{rule}:{comp_id}:{week}'
        if db.query(WatchAlert.id).filter_by(key=key).first():
            return
        row = WatchAlert(client_id=client.id, competitor_id=comp_id, rule=rule, message=message, key=key)
        db.add(row)
        made.append(row)

    for comp in db.query(WatchCompetitor).filter_by(client_id=client.id, status='confirmed'):
        snaps = data.get(str(comp.id), {})
        idle = [(snaps[k]['snapshot'].metrics or {}).get('days_since_last_post') for k in SOCIAL if k in snaps]
        if idle and all(d is not None and d >= 21 for d in idle):
            fire('quiet', comp.id, f'{comp.name} has not posted for {min(idle)} days on any watched platform.')
        changes = db.query(WatchChange).filter(WatchChange.competitor_id == comp.id, WatchChange.created_at >= since).all()
        week_changes = [c for c in changes if c.created_at >= datetime.utcnow() - timedelta(days=7)]
        cut = [c for c in week_changes if c.field.startswith('price:') and c.kind == 'changed' and '(-' in (c.after or '')]
        promo = [c for c in week_changes if c.field == 'ad' and c.kind == 'added' and DISCOUNT.search(c.after or '')]
        if cut or promo:
            fire('discounting', comp.id, f'{comp.name} started discounting: ' +
                 ('a price went down' if cut else 'a new discount ad') + '.')
        if any(c.field == 'headline' and c.kind == 'changed' for c in changes if c.created_at >= datetime.utcnow() - timedelta(days=7)):
            fire('repositions', comp.id, f'{comp.name} changed its homepage headline this week.')
        added = [c for c in changes if c.field.startswith('services:') and c.kind == 'added']
        if len(added) >= 3:
            fire('broadens', comp.id, f'{comp.name} added {len(added)} services in the last 30 days.')
    db.commit()
    return made


def _post_time(post: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(post.get('date') or '').replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def week_snapshot(db: Session, client: WatchClient, now: datetime | None = None) -> dict:
    """What the market did, straight from the latest captures (no AI), so every brief has content even in a quiet
    week: numbers, you against the rivals per platform, the rivals' best posts, news, live ads and plain takeaways."""
    now = now or datetime.utcnow()
    week = now - timedelta(days=7)
    data = latest(db, client.id)
    comps = companies(db, client)
    rivals, posts, news, ads, standing, takeaways = [], [], [], [], [], []
    mine = data.get('client', {})
    for c in comps[1:]:
        snaps = data.get(c['key'], {})
        row = {'key': c['key'], 'name': c['name'], 'tier': c['tier'], 'followers': None, 'platform': None, 'engagement_rate': None,
               'posts_7d': 0, 'live_ads': None, 'news': 0, 'jobs': None, 'prices': None}
        for kind in SOCIAL:
            if kind not in snaps:
                continue
            m = snaps[kind]['snapshot'].metrics or {}
            if (m.get('followers') or 0) > (row['followers'] or 0):
                row.update(followers=m.get('followers'), platform=kind, engagement_rate=m.get('engagement_rate'))
            for p in snaps[kind]['snapshot'].items or []:
                t = _post_time(p)
                if t and t >= week:
                    row['posts_7d'] += 1
                if t and t >= now - timedelta(days=30):
                    posts.append({'company': c['name'], 'key': c['key'], 'platform': kind, 'date': p.get('date'), 'url': p.get('url'),
                                  'caption': (p.get('caption') or '')[:280], 'likes': p.get('likes'),
                                  'comments': p.get('comments'), 'engagement': p.get('engagement_total') or 0,
                                  'this_week': bool(t >= week)})
        ad = snaps.get('ads')
        if ad and not any('page_name' not in a for a in ad['snapshot'].items or []):
            live = [a for a in ad['snapshot'].items or [] if a.get('active')]
            row['live_ads'] = len(live)
            ads += [{'company': c['name'], 'headline': a.get('headline') or '', 'body': (a.get('body') or '')[:220],
                     'start': a.get('start'), 'url': a.get('url')} for a in live[:3]]
        web = snaps.get('web')
        if web:
            items = web['snapshot'].items or []
            row['news'] = len(items)
            news += [{'company': c['name'], **{k: i.get(k) for k in ('title', 'site', 'date', 'url', 'kind')}} for i in items[:3]]
        careers = snaps.get('page:careers')
        if careers:
            row['jobs'] = len((careers['snapshot'].fields or {}).get('jobs') or [])
        pricing = snaps.get('page:pricing')
        if pricing and (pricing['snapshot'].fields or {}).get('prices'):
            row['prices'] = len(pricing['snapshot'].fields['prices'])
        rivals.append(row)

    for kind in SOCIAL:
        theirs = [(r['name'], (data.get(c['key'], {}).get(kind) or {}).get('snapshot')) for r, c in zip(rivals, comps[1:])]
        theirs = [(n, s.metrics.get('engagement_rate')) for n, s in theirs if s and (s.metrics or {}).get('engagement_rate') is not None]
        you = (mine.get(kind) or {}).get('snapshot')
        you_er = (you.metrics or {}).get('engagement_rate') if you else None
        if not theirs and you_er is None:
            continue
        leader = max(theirs, key=lambda x: x[1]) if theirs else (None, None)
        avg = round(sum(x[1] for x in theirs) / len(theirs), 2) if theirs else None
        you_posts = sum(1 for p in (you.items if you else []) or [] if (_post_time(p) or datetime.min) >= week)
        standing.append({'platform': kind, 'you': you_er, 'rivals_avg': avg, 'leader': leader[0], 'leader_rate': leader[1],
                         'you_posts_7d': you_posts if you else None})

    posts.sort(key=lambda p: (p['engagement'], p['this_week']), reverse=True)
    label = {'instagram': 'Instagram', 'facebook': 'Facebook', 'linkedin': 'LinkedIn'}
    busiest = max(rivals, key=lambda r: r['posts_7d'], default=None)
    if busiest and busiest['posts_7d']:
        takeaways.append(f"{busiest['name']} was the most active rival this week with {busiest['posts_7d']} posts.")
    elif rivals:
        takeaways.append('No watched rival posted on social media this week.')
    for s in standing:
        if s['you'] is not None and s['rivals_avg'] is not None:
            side = 'above' if s['you'] >= s['rivals_avg'] else 'below'
            takeaways.append(f"Your {label[s['platform']]} engagement ({s['you']:.2f}%) is {side} the rivals' average "
                             f"({s['rivals_avg']:.2f}%).")
    live_total = sum(r['live_ads'] or 0 for r in rivals)
    checked = [r for r in rivals if r['live_ads'] is not None]
    if checked:
        takeaways.append(f'{live_total} live ads from watched rivals in Egypt.' if live_total
                         else 'No watched rival is running ads in Egypt right now: paid reach is uncontested.')
    hiring = [r for r in rivals if r['jobs']]
    if hiring:
        top = max(hiring, key=lambda r: r['jobs'])
        takeaways.append(f"{top['name']} lists {top['jobs']} open roles, a sign of where it is investing.")
    if posts:
        p = posts[0]
        takeaways.append(f"Best rival post: {p['company']} on {label[p['platform']]} with {p['engagement']} interactions.")
    return {'as_of': now.isoformat(timespec='minutes'), 'rivals': rivals, 'standing': standing, 'posts': posts[:4],
            'news': news[:5], 'ads': ads[:4], 'takeaways': takeaways[:6],
            'numbers': {'rivals': len(rivals), 'posts_7d': sum(r['posts_7d'] for r in rivals),
                        'live_ads': live_total if checked else None, 'news': sum(r['news'] for r in rivals),
                        'jobs': sum(r['jobs'] or 0 for r in rivals)}}
