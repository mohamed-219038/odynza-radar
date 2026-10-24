"""M2 Content from a strategy plan: posting slots from the plan's weekly rhythm, the content pack the n8n
"Odynza Radar Content" agents write from, the checks shown on each draft, and the media buying plan clean-up.

Plain Python over saved data (the plan and the latest Radar captures). No model calls here.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import BaseModel, Field

from api.strategy_plan import LANGUAGE, PLATFORMS, _cut, _rescale

DAY = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
# Egypt's work week is Sunday to Thursday; these are the default posting days for n posts a week.
POST_DAYS = {1: [1], 2: [6, 2], 3: [6, 1, 3], 4: [6, 0, 1, 3], 5: [6, 0, 1, 2, 3], 6: [6, 0, 1, 2, 3, 4],
             7: [6, 0, 1, 2, 3, 4, 5]}
MAX_TEXT = {'LinkedIn': 3000, 'Instagram': 2200, 'Facebook': 3000}
MAX_TAGS = {'LinkedIn': 5, 'Instagram': 10, 'Facebook': 4}
DEFAULT_RHYTHM = {'LinkedIn': 3, 'Instagram': 4, 'Facebook': 3}
DEFAULT_TIME = {'LinkedIn': '10:00', 'Instagram': '20:00', 'Facebook': '19:00'}
FORMATS = {'LinkedIn': ('post', 'document'), 'Instagram': ('post', 'carousel'), 'Facebook': ('post', 'carousel')}
ASPECT = {'LinkedIn': '1:1', 'Instagram': '4:5', 'Facebook': '4:5', 'reel': '9:16', 'story': '9:16'}

RULES = {
    'LinkedIn': ('LinkedIn, in English: B2B decision makers. Hook in the first line (under 140 characters, it shows before '
                 '"see more"). 600 to 1,300 characters, short paragraphs, one idea, one clear CTA. 3 to 5 hashtags. No '
                 'emojis in the hook. A "document" post is a PDF carousel: 5 to 7 slides (slide 1 = hook, last = CTA).'),
    'Instagram': ('Instagram, in Egyptian Arabic (English terms like AI or CRM are fine): visual first. Caption hook in the '
                  'first line, 300 to 1,000 characters, line breaks, a CTA such as "ابعتلنا DM" or "اللينك في البايو". 5 to 10 '
                  'hashtags mixing Arabic and English. A carousel has 4 to 7 slides. A reel is 5 to 8 seconds, vertical, one '
                  'striking motion idea that animates the key frame. A story is 3 to 5 vertical frames: each frame one short '
                  'line (headline) and an optional sticker idea (body, such as a poll or a question box); the last frame '
                  'asks for a reply or a link tap.'),
    'Facebook': ('Facebook, in Egyptian Arabic: SME owners and managers in Egypt, warm and practical. Open with an everyday '
                 'pain point, 300 to 900 characters, one CTA (message us, book a call or the website link). 2 to 4 '
                 'hashtags. Questions that invite comments work well.'),
}


def slot_days(start: date, weeks: int, per_week: int, best: list[str]) -> list[date]:
    """Posting days: the plan's best slots first (such as "Sun 19:00"), filled up with the default work days."""
    wanted = []
    for slot in best or []:
        d = DAY.get(str(slot).strip()[:3].lower())
        if d is not None and d not in wanted:
            wanted.append(d)
    for d in POST_DAYS[per_week]:
        if len(wanted) >= per_week:
            break
        if d not in wanted:
            wanted.append(d)
    wanted = set(wanted[:per_week])
    end = start + timedelta(days=7 * weeks - 1)
    return [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() in wanted]


def slot_time(best: list[str], day: date, platform: str) -> str:
    for slot in best or []:
        m = re.match(r'\s*([A-Za-z]{3})\w*\s+(\d{1,2}:\d{2})', str(slot))
        if m and DAY.get(m.group(1).lower()) == day.weekday():
            return m.group(2).zfill(5)
    return DEFAULT_TIME[platform]


def entry_on(calendar: list, campaign: dict | None, day: date) -> str:
    """The plan's own calendar entry nearest to the day for this campaign (holidays and sales days included)."""
    near = []
    for e in calendar or []:
        try:
            gap = abs((date.fromisoformat(e['date']) - day).days)
        except (KeyError, ValueError):
            continue
        if e.get('kind') in ('holiday', 'shopping', 'tech', 'season') and gap <= 3:
            near.append((gap, f"{e['title']} on {e['date']}"))
        elif campaign and e.get('campaign_id') == campaign.get('id') and e.get('kind') != 'campaign' and gap <= 7:
            near.append((gap, e['title']))
    return '; '.join(t for _, t in sorted(near)[:2])


def campaign_on(campaigns, day):
    running = [c for c in campaigns if str(c.get('start_date', '')) <= day.isoformat() <= str(c.get('end_date', ''))]
    if running:
        return running[0]
    # Outside every campaign: use the one that starts or ends closest to this day.
    def distance(c):
        try:
            return min(abs((date.fromisoformat(str(c[k])) - day).days) for k in ('start_date', 'end_date'))
        except (KeyError, ValueError):
            return 10 ** 6
    return min(campaigns, key=distance) if campaigns else None



def plan_slots(plan: dict, platforms: list, start: date, weeks: int, rhythm: dict, reels_per_month: int,
               stories_per_week: int) -> list[dict]:
    campaigns = plan.get('campaigns') or []
    calendar = plan.get('calendar') or []
    plan_rhythm = {r['platform']: r for r in (plan.get('content_plan') or {}).get('rhythm') or []}
    slots, reels = [], {}
    for platform in platforms:
        per_week = int(rhythm.get(platform) or round((plan_rhythm.get(platform) or {}).get('per_week') or 0)
                       or DEFAULT_RHYTHM[platform])
        per_week = max(1, min(7, per_week))
        best = (plan_rhythm.get(platform) or {}).get('best_slots') or []
        for n, day in enumerate(slot_days(start, weeks, per_week, best)):
            campaign = campaign_on(campaigns, day)
            fmt = 'post'
            if platform == 'Instagram' and reels.get((day.year, day.month), 0) < reels_per_month:
                reels[(day.year, day.month)] = reels.get((day.year, day.month), 0) + 1
                fmt = 'reel'
            elif n % 2:
                fmt = FORMATS[platform][1]
            slots.append(_slot(platform, day, fmt, campaign, calendar, slot_time(best, day, platform)))
    if 'Instagram' in platforms and stories_per_week:
        for day in slot_days(start, weeks, max(1, min(7, stories_per_week)), []):
            slots.append(_slot('Instagram', day, 'story', campaign_on(campaigns, day), calendar, '13:00', 'st'))
    slots.sort(key=lambda s: (s['date'], s['time'], s['platform']))
    return slots


def _slot(platform, day, fmt, campaign, calendar, time, prefix=None):
    return {'slot_id': f"{prefix or platform[:2].lower()}-{day.isoformat()}", 'platform': platform,
            'date': day.isoformat(), 'time': time, 'format': fmt,
            'campaign_id': (campaign or {}).get('id', ''), 'campaign_name': (campaign or {}).get('name', ''),
            'key_message': (campaign or {}).get('key_message', '') or (campaign or {}).get('hook', ''),
            'plan_action': entry_on(calendar, campaign, day)}


def _posts_of(snaps: dict, platform: str, n: int):
    snap = (snaps.get(platform.lower()) or {}).get('snapshot')
    if not snap:
        return []
    posts = sorted(snap.items or [], key=lambda p: -(p.get('engagement_total') or 0))
    return [p for p in posts if p.get('caption')][:n]


def content_pack(db, run, plan_row) -> dict:
    """Text blocks for the platform agents and the media buyer, built from the Radar plan and captures."""
    from api.watch.insight import companies, latest
    from db.watch_models import WatchClient

    plan = plan_row.plan or {}
    inputs = plan_row.inputs or {}
    client = db.get(WatchClient, inputs.get('client_id'))
    voices = inputs.get('voices') or {}
    pos = plan.get('positioning') or {}
    ov = plan.get('overview') or {}

    brief = [f'Company: {plan_row.company_name}',
             f"Goal: {inputs.get('goal', '')}. {inputs.get('objective', '')}",
             f"Audience: {inputs.get('audience') or (client.audience if client else '') or 'see the plan'}",
             f"Big idea: {ov.get('big_idea', '')}",
             f"Positioning: {pos.get('statement', '')}",
             f"Positioning in Arabic: {pos.get('statement_ar', '')}",
             f"Core message: {pos.get('core_message', '')}",
             'Pillars:'] + [f"- {p.get('name')}: {p.get('message', '')} (proof: {p.get('proof', '') or 'none yet'})"
                            for p in pos.get('pillars') or []]
    brief += ['Campaigns:'] + [f"- {c['id']}: {c.get('name')} ({c.get('start_date')} to {c.get('end_date')}). Idea: "
                               f"{c.get('idea', '')}. Hook: {c.get('hook', '')} / {c.get('hook_ar', '')}. Offer: "
                               f"{c.get('offer', '')}. Message: {c.get('key_message', '')}"
                               for c in plan.get('campaigns') or []]
    mix = (plan.get('content_plan') or {}).get('mix') or []
    if mix:
        brief.append('Content mix: ' + ', '.join(f"{m['label']} {m['percent']:g}%" for m in mix))
    if run.inputs.get('notes'):
        brief.append(f"Extra notes from the user for this batch: {run.inputs['notes']}")

    voice = {}
    for p in PLATFORMS:
        v = voices.get(p) or {}
        line = next((r.get('line') for r in pos.get('by_platform') or [] if r.get('platform') == p), '')
        voice[p] = (f"Voice: {v.get('label', 'Friendly guide')} ({v.get('style', '')}). Language: {LANGUAGE[p]}. "
                    f"Platform line from the plan: {line}")

    data = latest(db, client.id) if client else {}
    own = []
    for p in PLATFORMS:
        for post in _posts_of(data.get('client', {}), p, 2):
            own.append(f"- {p}, {post.get('engagement_total') or 0} interactions: {_cut(post.get('caption'), 220)}")
    brand = ['Its own best posts (match the voice, do not copy):'] + (own or ['- none collected yet'])
    brand.append(f"Brand look for images: {run.inputs.get('brand_look', '')}")

    proof = [f"- {p.get('proof')}" for p in pos.get('pillars') or [] if p.get('proof') and 'needed' not in p['proof'].lower()]
    if client and client.claims:
        proof += [f'- The client says: {c}' for c in client.claims[:6]]
    edge = ((plan.get('competitive_brief') or {}).get('battlecard') or {}).get('our_edge') or []
    proof += [f'- Edge over rivals: {e}' for e in edge[:4]]

    rivals = {}
    comps = companies(db, client)[1:] if client else []
    for p in PLATFORMS:
        lines = []
        for c in comps:
            for post in _posts_of(data.get(c['key'], {}), p, 2):
                lines.append(f"- {c['name']} ({post.get('engagement_total') or 0} interactions, "
                             f"{post.get('type') or post.get('format') or 'post'}): {_cut(post.get('caption'), 200)}")
        rivals[p] = '\n'.join(lines[:6]) or '- no rival posts collected on this platform yet'

    ads = []
    for c in comps:
        ad = data.get(c['key'], {}).get('ads')
        if ad:
            for a in [a for a in ad['snapshot'].items or [] if a.get('active')][:3]:
                ads.append(f"- {c['name']} since {a.get('start') or '?'}: {_cut(a.get('headline'), 100)} — {_cut(a.get('body'), 200)}")

    slots = run.inputs.get('slots', [])
    by_platform = {p: '\n'.join(
        f"- slot_id {s['slot_id']} | {s['date']} {s.get('time', '')} | format {s['format']} | campaign {s['campaign_id']} "
        f"{s['campaign_name']} | message: {s['key_message']} | plan says: {s['plan_action'] or 'nothing special'}"
        for s in slots if s['platform'] == p) for p in PLATFORMS}

    money = media_money(plan, inputs)
    buying = [f"Plan period: {inputs.get('start_date')} to {inputs.get('end_date')}. Currency: {inputs.get('currency', '')}.",
              'Paid budget for the whole plan: ' + (', '.join(f'{k}: {v:,.0f}' for k, v in money.items()) or 'none'),
              f"Paid channels allowed: {', '.join(inputs.get('paid') or []) or 'none'}",
              'KPIs: ' + '; '.join(f"{k.get('name')} {k.get('target')}" for k in plan.get('kpis') or []),
              'Campaigns: ' + '; '.join(f"{c['id']} {c.get('name')} {c.get('start_date')} to {c.get('end_date')} "
                                        f"({c.get('budget_percent')}% of budget, goal {c.get('goal', '')}, audience "
                                        f"{c.get('audience', '')})" for c in plan.get('campaigns') or []),
              'Drafts in this batch that can be used as ads: ' + ', '.join(
                  s['slot_id'] for s in slots if s['format'] in ('post', 'carousel', 'reel', 'document')),
              'Live rival ads:'] + (ads or ['- none'])
    return {
        'run_id': run.id, 'company_name': plan_row.company_name, 'version': 2,
        'brief': '\n'.join(brief), 'brand': '\n'.join(brand),
        'proof': '\n'.join(proof) or '- No published proof yet: use placeholders such as [Client] and [X hours].',
        'voice': voice, 'rules': RULES, 'rivals': rivals, 'slots': by_platform,
        'slot_counts': {p: sum(s['platform'] == p for s in slots) for p in PLATFORMS},
        'media_buying': '\n'.join(buying), 'make_media_buying': bool(run.inputs.get('media_buying') and money),
    }


# ---- Media buying ----------------------------------------------------------------------------------

def media_money(plan: dict, inputs: dict) -> dict:
    """Paid budget per platform from the plan's budget lines (amounts computed by Radar, never the model)."""
    out = {}
    allowed = set(inputs.get('paid') or [])
    for line in plan.get('budget') or []:
        name = str(line.get('channel', '')).lower()
        platform = 'Meta ads' if re.search(r'meta|facebook|instagram', name) else \
            'LinkedIn ads' if 'linkedin' in name else None
        if platform and platform in allowed and line.get('amount'):
            out[platform] = out.get(platform, 0) + line['amount']
    return out


class Loose(BaseModel):
    model_config = {'extra': 'ignore'}


class AdIn(Loose):
    name: str = ''
    format: str = ''
    primary_text: str = ''
    headline: str = ''
    cta: str = ''
    draft_slot_id: str = ''


class AdSetIn(Loose):
    name: str
    audience: str = ''
    locations: list[str] = Field(default_factory=list)
    ages: str = ''
    gender: str = ''
    languages: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)
    placements: list[str] = Field(default_factory=list)
    optimization: str = ''
    budget_percent: float = 0
    ads: list[AdIn] = Field(default_factory=list)


class AdCampaignIn(Loose):
    platform: str
    name: str
    objective: str = ''
    campaign_id: str = ''
    budget_percent: float = 0
    start_date: date | None = None
    end_date: date | None = None
    bidding: str = ''
    ad_sets: list[AdSetIn] = Field(default_factory=list)


class TestIn(Loose):
    name: str
    variable: str = ''
    a: str = ''
    b: str = ''
    metric: str = ''
    duration: str = ''


class MediaBuyingIn(Loose):
    summary: str = ''
    campaigns: list[AdCampaignIn] = Field(default_factory=list)
    ab_tests: list[TestIn] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    tracking: list[str] = Field(default_factory=list)


BENCHMARKS = [
    {'platform': 'Meta ads', 'metric': 'Click rate (CTR)', 'range': '0.9% to 1.5%', 'note': 'Lead and traffic ads, B2B in MENA.'},
    {'platform': 'Meta ads', 'metric': 'Frequency', 'range': 'under 3 a week', 'note': 'Above that, refresh the creative.'},
    {'platform': 'LinkedIn ads', 'metric': 'Click rate (CTR)', 'range': '0.44% to 0.65%', 'note': 'Single image sponsored content.'},
    {'platform': 'LinkedIn ads', 'metric': 'Lead form completion', 'range': '10% to 15%', 'note': 'Of people who open the form.'},
    {'platform': 'All', 'metric': 'Creative life', 'range': '2 to 4 weeks', 'note': 'Plan the next creative before results drop.'},
]
CHECKLIST = ['Meta Pixel and LinkedIn Insight Tag installed and firing on the thank-you page.',
             'UTM tags on every ad link (utm_source, utm_medium=paid, utm_campaign = the plan campaign id).',
             'Lead forms tested end to end: a test lead reaches the inbox or CRM.',
             'Ad account payment method, currency and time zone (Africa/Cairo) checked.',
             'Every ad approved by a person before it goes live; no ad is published from this page.']


def clean_media_buying(raw: dict | None, plan: dict, inputs: dict, slot_ids: set[str]) -> dict | None:
    if not raw:
        return None
    m = MediaBuyingIn.model_validate(raw)
    money = media_money(plan, inputs)
    start, end = date.fromisoformat(inputs['start_date']), date.fromisoformat(inputs['end_date'])
    names = {c['id']: c for c in plan.get('campaigns') or []}
    campaigns = []
    for c in m.campaigns[:6]:
        platform = 'Meta ads' if re.search(r'meta|facebook|instagram', c.platform, re.I) else \
            'LinkedIn ads' if 'linkedin' in c.platform.lower() else None
        if platform not in money:
            continue
        plan_c = names.get(c.campaign_id) or {}
        s = c.start_date or (date.fromisoformat(plan_c['start_date']) if plan_c else start)
        e = c.end_date or (date.fromisoformat(plan_c['end_date']) if plan_c else end)
        s, e = max(start, min(s, e)), min(end, max(e, s))
        row = c.model_dump(mode='json')
        row.update(platform=platform, start_date=s.isoformat(), end_date=e.isoformat(), days=(e - s).days + 1,
                   campaign_id=c.campaign_id if c.campaign_id in names else '')
        sets = [a for a in row['ad_sets'] if a['name']][:5]
        if sets and sum(a['budget_percent'] for a in sets) <= 0:
            for a in sets:
                a['budget_percent'] = 100 / len(sets)
        row['ad_sets'] = _rescale(sets, 'budget_percent') if sets else []
        for a in row['ad_sets']:
            a['ads'] = a['ads'][:4]
            for ad in a['ads']:
                if ad['draft_slot_id'] not in slot_ids:
                    ad['draft_slot_id'] = ''
        campaigns.append(row)
    for platform in money:
        mine = [c for c in campaigns if c['platform'] == platform]
        if mine and sum(c['budget_percent'] for c in mine) <= 0:
            for c in mine:
                c['budget_percent'] = 100 / len(mine)
        _rescale(mine, 'budget_percent')
        for c in mine:
            c['amount'] = round(money[platform] * c['budget_percent'] / 100, 2)
            c['daily'] = round(c['amount'] / c['days'], 2)
            for a in c['ad_sets']:
                a['amount'] = round(c['amount'] * a['budget_percent'] / 100, 2)
                a['daily'] = round(a['amount'] / c['days'], 2)
    out = {
        'summary': _cut(m.summary, 600),
        'currency': inputs.get('currency', ''),
        'budget': money,
        'campaigns': campaigns,
        'ab_tests': [t.model_dump() for t in m.ab_tests[:4]],
        'benchmarks': BENCHMARKS,
        'checklist': CHECKLIST + [_cut(x, 200) for x in m.checklist[:6] if x and x not in CHECKLIST],
        'tracking': [_cut(x, 200) for x in m.tracking[:6]],
    }
    return out


def hashtag_limit(platform: str) -> int:
    return MAX_TAGS[platform]


NUMBER = re.compile(r'(?<![\w\[])\d[\d,.]*\s*(?:%|٪|x|k|hours?|days?|minutes?|EGP|USD|\$)?', re.IGNORECASE)


def review_checks(text, slides, pack_text):
    """Things to confirm before posting: numbers not found in the report or plan, and [placeholders] to fill."""
    checks = []
    body = ' '.join([text] + [f"{s.get('headline', '')} {s.get('body', '')}" for s in slides])
    known = {re.sub(r'\D', '', n) for n in re.findall(r'\d[\d,.]*', pack_text)}
    for match in sorted({m.group(0).strip() for m in NUMBER.finditer(body)}):
        digits = re.sub(r'\D', '', match)
        if len(digits) >= 2 and digits not in known:
            checks.append(f'Check the number "{match}": it is not in your report or plan.')
    for holder in sorted(set(re.findall(r'\[[^\]\n]{1,40}\]', body))):
        checks.append(f'Fill in {holder} before posting.')
    return checks[:8]
