"""M1 Strategy from Radar data (plan version 2): the request, the events calendar, the pack n8n reads, the plan
content n8n posts back and the lenient clean-up done before saving, plus the rule-based results report.

No model calls here. The n8n "Odynza Radar Strategy" workflow writes the plan; Radar computes every amount,
keeps dates inside the plan period and adds the known events itself, so the page never shows invented dates or sums.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

PLATFORMS = ('LinkedIn', 'Instagram', 'Facebook')
LANGUAGE = {'LinkedIn': 'English', 'Instagram': 'Egyptian Arabic', 'Facebook': 'Egyptian Arabic'}
VOICES = {
    'formal': ('Formal expert', 'Clear, precise and evidence-led. Short sentences, numbers and proof. No slang, no emojis.'),
    'friendly': ('Friendly guide', 'Warm and helpful. Speaks to one person, explains simply, a light emoji now and then.'),
    'funky': ('Funky and bold', 'Playful, punchy and confident. Short lines, trends and humour; emojis and slang are fine.'),
    'witty': ('Witty storyteller', 'Opens with a small story or a twist, clever wordplay, lands on one clear point.'),
    'visionary': ('Inspiring visionary', 'Big-picture and optimistic. Talks about the future the client makes possible.'),
}
RADAR_INPUTS = ('opportunities', 'moves', 'claims', 'ads', 'posts', 'brief')
PAID = ('Meta ads', 'LinkedIn ads')
EVENT_KINDS = ('campaign', 'content', 'milestone', 'shopping', 'tech', 'holiday', 'season')

# Egypt and MENA dates that matter for marketing. confirmed=False: an Islamic date that depends on the moon, or an
# event whose organiser has not published its dates yet. The page marks those with * so they are checked first.
EVENTS = [
    ('2026-11-08', '2026-11-11', 'Cairo ICT 2026 (EIEC, New Cairo)', 'tech', True),
    ('2026-11-11', None, '11.11 sales day', 'shopping', True),
    ('2026-11-27', None, 'Black Friday / White Friday', 'shopping', True),
    ('2026-12-18', None, 'World Arabic Language Day', 'season', True),
    ('2026-12-31', '2027-01-01', 'New Year', 'holiday', True),
    ('2027-01-07', None, 'Coptic Christmas (public holiday)', 'holiday', True),
    ('2027-01-25', None, 'Revolution and Police Day (public holiday)', 'holiday', True),
    ('2027-02-08', '2027-03-08', 'Ramadan', 'season', False),
    ('2027-02-14', None, "Valentine's Day", 'shopping', True),
    ('2027-03-09', '2027-03-11', 'Eid al-Fitr (public holiday)', 'holiday', False),
    ('2027-03-21', None, "Mother's Day (Egypt)", 'shopping', True),
    ('2027-04-25', None, 'Sinai Liberation Day (public holiday)', 'holiday', True),
    ('2027-05-01', None, 'Labour Day (public holiday)', 'holiday', True),
    ('2027-05-02', '2027-05-03', 'Coptic Easter and Sham El Nessim', 'holiday', True),
    ('2027-05-15', '2027-05-18', 'Arafat Day and Eid al-Adha (public holiday)', 'holiday', False),
    ('2027-06-06', None, 'Islamic New Year (public holiday)', 'holiday', False),
    ('2027-06-30', None, 'June 30 Revolution (public holiday)', 'holiday', True),
    ('2027-07-23', None, 'Revolution Day (public holiday)', 'holiday', True),
    ('2027-08-14', None, "Prophet's Birthday (public holiday)", 'holiday', False),
    ('2027-09-20', '2027-10-05', 'Back to school and new budget season', 'season', False),
    ('2027-10-06', None, 'Armed Forces Day (public holiday)', 'holiday', True),
    ('2027-10-11', '2027-10-15', 'GITEX Global, Dubai', 'tech', False),
    ('2027-11-11', None, '11.11 sales day', 'shopping', True),
    ('2027-11-14', '2027-11-17', 'Cairo ICT 2027', 'tech', False),
    ('2027-11-26', None, 'Black Friday / White Friday', 'shopping', True),
    ('2027-12-18', None, 'World Arabic Language Day', 'season', True),
    ('2027-12-31', '2028-01-01', 'New Year', 'holiday', True),
    ('2028-01-07', None, 'Coptic Christmas (public holiday)', 'holiday', True),
    ('2028-01-25', None, 'Revolution and Police Day (public holiday)', 'holiday', True),
    ('2028-01-28', '2028-02-25', 'Ramadan', 'season', False),
    ('2028-02-14', None, "Valentine's Day", 'shopping', True),
    ('2028-02-26', '2028-02-28', 'Eid al-Fitr (public holiday)', 'holiday', False),
    ('2028-03-21', None, "Mother's Day (Egypt)", 'shopping', True),
    ('2028-04-16', '2028-04-17', 'Coptic Easter and Sham El Nessim', 'holiday', True),
    ('2028-04-25', None, 'Sinai Liberation Day (public holiday)', 'holiday', True),
    ('2028-05-01', None, 'Labour Day (public holiday)', 'holiday', True),
    ('2028-05-04', '2028-05-07', 'Arafat Day and Eid al-Adha (public holiday)', 'holiday', False),
    ('2028-05-25', None, 'Islamic New Year (public holiday)', 'holiday', False),
    ('2028-06-30', None, 'June 30 Revolution (public holiday)', 'holiday', True),
    ('2028-07-23', None, 'Revolution Day (public holiday)', 'holiday', True),
    ('2028-08-03', None, "Prophet's Birthday (public holiday)", 'holiday', False),
    ('2028-10-06', None, 'Armed Forces Day (public holiday)', 'holiday', True),
]


def events_between(start: date, end: date) -> list[dict]:
    out = []
    for day, until, name, kind, confirmed in EVENTS:
        first, last = date.fromisoformat(day), date.fromisoformat(until or day)
        if last >= start and first <= end:
            out.append({'date': day, 'end_date': until, 'title': name, 'kind': kind, 'confirmed': confirmed,
                        'source': 'events'})
    return out


def months_between(start: date, end: date) -> list[dict]:
    """Each calendar month the plan touches, with its share of the plan's days."""
    total = (end - start).days + 1
    out, day = [], start
    while day <= end:
        last = min(end, date(day.year, day.month, monthrange(day.year, day.month)[1]))
        days = (last - day).days + 1
        out.append({'month': day.strftime('%Y-%m'), 'label': day.strftime('%b %Y'), 'days': days, 'share': days / total})
        day = last + timedelta(days=1)
    return out


# ---- The request from the New plan page ------------------------------------------------------------------

class Voice(BaseModel):
    key: Literal['formal', 'friendly', 'funky', 'witty', 'visionary', 'custom'] = 'friendly'
    custom: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def check(self):
        self.custom = self.custom.strip()
        if self.key == 'custom' and len(self.custom) < 3:
            raise ValueError('Describe the custom voice in a few words.')
        return self

    def describe(self) -> tuple[str, str]:
        if self.key == 'custom':
            return 'Custom voice', self.custom
        return VOICES[self.key]


GOALS = ('Leads', 'Awareness', 'Launch', 'Sales', 'Retention', 'Hiring brand')


class RadarPlanRequest(BaseModel):
    goal: Literal['Leads', 'Awareness', 'Launch', 'Sales', 'Retention', 'Hiring brand'] = 'Leads'
    objective: str = Field(default='', max_length=600)          # optional detail, such as "40 demo requests"
    audience: str = Field(default='', max_length=300)
    budget: float | None = Field(default=20000, ge=0, le=1e12)  # per month
    currency: str = Field(default='EGP', max_length=3)
    start_date: date
    end_date: date
    events: str = Field(default='', max_length=600)             # the client's own dates, typed by hand
    voices: dict[str, Voice] = Field(default_factory=dict)
    inputs: list[Literal['opportunities', 'moves', 'claims', 'ads', 'posts', 'brief']] = Field(
        default_factory=lambda: list(RADAR_INPUTS))
    paid: list[Literal['Meta ads', 'LinkedIn ads']] = Field(default_factory=lambda: list(PAID))
    opportunity_id: int | None = None
    constraints: str = Field(default='', max_length=600)

    @model_validator(mode='after')
    def check(self):
        if self.end_date < self.start_date:
            raise ValueError('The end date must be on or after the start date.')
        if (self.end_date - self.start_date).days > 366:
            raise ValueError('Plan at most one year at a time.')
        self.currency = self.currency.strip().upper() or 'EGP'
        if not re.fullmatch(r'[A-Z]{3}', self.currency):
            raise ValueError('Enter a three-letter currency code, such as EGP or USD.')
        unknown = set(self.voices) - set(PLATFORMS)
        if unknown:
            raise ValueError('Voices are set for LinkedIn, Instagram and Facebook only.')
        for p in PLATFORMS:
            self.voices.setdefault(p, Voice(key=suggest_voice(p)[0]))
        self.inputs = list(dict.fromkeys(self.inputs))
        self.paid = list(dict.fromkeys(self.paid))
        return self

    def total_budget(self) -> float | None:
        """The monthly budget over the plan's days (a month counted as 30.4 days)."""
        if self.budget is None:
            return None
        return round(self.budget * ((self.end_date - self.start_date).days + 1) / 30.4, 2)


def suggest_voice(platform: str, rivals: dict | None = None) -> tuple[str, str]:
    """Radar's ★ pick. Rule-based: what fits the platform, nudged away from the tone the rivals already use."""
    rivals = rivals or {}
    if platform == 'LinkedIn':
        if rivals.get('LinkedIn') == 'formal':
            return 'visionary', 'Rivals on LinkedIn all sound formal; a visionary voice stands out and still reads as senior.'
        return 'formal', 'LinkedIn buyers want proof and numbers; a formal expert voice earns trust with decision makers.'
    if platform == 'Instagram':
        return 'funky', 'Instagram rewards short, playful posts and reels; a bold voice wins the scroll.'
    return 'friendly', 'Facebook in Egypt is where people ask questions; a friendly guide answers them and gets leads.'


# ---- Plan content posted back by n8n (lenient: missing parts get defaults, the clean-up fixes the rest) ----

class Loose(BaseModel):
    model_config = {'extra': 'ignore'}


def _s(limit):
    return Field(default='', max_length=limit * 4)   # generous; text is cut to `limit` in clean()


class Overview(Loose):
    summary: str = ''
    smart_goal: str = ''
    big_idea: str = ''
    north_star: str = ''
    north_star_target: str = ''
    highlights: list[str] = Field(default_factory=list)


class RivalProfile(Loose):
    name: str
    tier: str = ''
    positioning: str = ''
    tagline: str = ''
    audience: str = ''
    tone: str = ''
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recent_moves: list[str] = Field(default_factory=list)
    threat: str = ''                    # high | medium | low


class MatrixRow(Loose):
    company: str
    tagline: str = ''
    target_buyer: str = ''
    differentiator: str = ''
    tone: str = ''
    value_prop: str = ''
    you: bool = False


class MapPoint(Loose):
    company: str
    x: float = 50
    y: float = 50
    you: bool = False


class PositionMap(Loose):
    x_low: str = ''
    x_high: str = ''
    y_low: str = ''
    y_high: str = ''
    points: list[MapPoint] = Field(default_factory=list)
    open_space: str = ''


class Gap(Loose):
    topic: str
    who: str = ''
    action: str = ''


class Objection(Loose):
    they_say: str
    we_say: str = ''


class Battlecard(Loose):
    rival: str = ''
    their_pitch: str = ''
    our_edge: list[str] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    landmines: list[str] = Field(default_factory=list)


class CompetitiveBrief(Loose):
    landscape: str = ''
    biggest_opportunity: str = ''
    biggest_threat: str = ''
    rivals: list[RivalProfile] = Field(default_factory=list)
    messaging_matrix: list[MatrixRow] = Field(default_factory=list)
    positioning_map: PositionMap = Field(default_factory=PositionMap)
    content_gaps: list[Gap] = Field(default_factory=list)
    battlecard: Battlecard = Field(default_factory=Battlecard)


class Pillar(Loose):
    name: str
    message: str = ''
    proof: str = ''


class PlatformLine(Loose):
    platform: str
    line: str = ''


class PositioningV2(Loose):
    statement: str = ''
    statement_ar: str = ''
    core_message: str = ''
    pillars: list[Pillar] = Field(default_factory=list)
    by_platform: list[PlatformLine] = Field(default_factory=list)


class CampaignV2(Loose):
    id: str = ''
    name: str
    idea: str = ''
    goal: str = ''
    audience: str = ''
    start_date: date | None = None
    end_date: date | None = None
    budget_percent: float = 0
    channels: list[str] = Field(default_factory=list)
    hook: str = ''
    hook_ar: str = ''
    key_message: str = ''
    offer: str = ''
    kpi: str = ''
    event: str = ''
    visual_prompt: str = ''


class CalendarEntry(Loose):
    date: date
    end_date: date | None = None
    title: str
    kind: str = 'content'
    campaign_id: str = ''
    channel: str = ''
    note: str = ''


class MixLine(Loose):
    label: str
    percent: float = 0


class Rhythm(Loose):
    platform: str
    per_week: float = 0
    formats: list[str] = Field(default_factory=list)
    best_slots: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)


class ContentPlanV2(Loose):
    mix: list[MixLine] = Field(default_factory=list)
    rhythm: list[Rhythm] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)


class BudgetLineV2(Loose):
    channel: str
    percent: float = 0
    purpose: str = ''


class KpiV2(Loose):
    name: str
    stage: str = ''
    baseline: str = 'unknown'
    target: str = ''
    target_value: float | None = None
    unit: str = ''
    how: str = ''
    cadence: str = ''
    campaign_id: str = ''


class Idea(Loose):
    title: str
    platform: str = ''
    format: str = ''
    description: str = ''
    why: str = ''


class Risk(Loose):
    risk: str
    likelihood: str = ''
    mitigation: str = ''


class Step(Loose):
    step: str
    owner: str = ''
    when: str = ''


class PlanV2(Loose):
    overview: Overview = Field(default_factory=Overview)
    competitive_brief: CompetitiveBrief = Field(default_factory=CompetitiveBrief)
    positioning: PositioningV2 = Field(default_factory=PositioningV2)
    campaigns: list[CampaignV2] = Field(default_factory=list)
    calendar: list[CalendarEntry] = Field(default_factory=list)
    content_plan: ContentPlanV2 = Field(default_factory=ContentPlanV2)
    budget: list[BudgetLineV2] = Field(default_factory=list)
    kpis: list[KpiV2] = Field(default_factory=list)
    creative_ideas: list[Idea] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    next_steps: list[Step] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def _cut(value, limit=400):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _clip(rows, n):
    return list(rows)[:n]


def _rescale(rows, key='percent'):
    rows = [r for r in rows if (r.get(key) or 0) > 0]
    total = sum(r[key] for r in rows)
    if not total:
        return rows
    for r in rows:
        r[key] = round(r[key] * 100 / total, 1)
    if rows:   # rounding drift goes on the biggest line so the column adds up to exactly 100
        big = max(rows, key=lambda r: r[key])
        big[key] = round(big[key] + 100 - sum(r[key] for r in rows), 1)
    return rows


def _texts(obj, limit=400):
    """Cut every string inside a dumped model (lists and nested objects included)."""
    if isinstance(obj, str):
        return _cut(obj, limit)
    if isinstance(obj, list):
        return [_texts(v, limit) for v in obj if v not in (None, '')]
    if isinstance(obj, dict):
        return {k: _texts(v, limit) for k, v in obj.items()}
    return obj


class PlanProblem(ValueError):
    pass


def clean(raw: dict, inputs: dict) -> tuple[dict, list[str]]:
    """Validate and fix the plan from n8n. Returns the saved plan and plain notes on what was changed."""
    notes: list[str] = []
    plan = PlanV2.model_validate(raw or {})
    start, end = date.fromisoformat(inputs['start_date']), date.fromisoformat(inputs['end_date'])
    if not plan.positioning.statement and not plan.overview.summary:
        raise PlanProblem('The plan came back without an overview or a positioning statement.')
    if not plan.campaigns:
        raise PlanProblem('The plan came back without any campaign.')

    # Campaigns: unique ids, dates inside the period, budget shares that add up.
    seen, campaigns = set(), []
    for i, c in enumerate(_clip(plan.campaigns, 5), start=1):
        cid = re.sub(r'[^A-Za-z0-9_-]', '', c.id or '')[:12] or f'C{i}'
        if cid in seen:
            cid = f'C{i}'
        seen.add(cid)
        s, e = c.start_date or start, c.end_date or end
        if s > e:
            s, e = e, s
        if s < start or e > end:
            notes.append(f'Campaign "{_cut(c.name, 60)}" was moved inside the plan period.')
        s, e = max(start, min(s, end)), min(end, max(e, start))
        row = c.model_dump(mode='json')
        row.update(id=cid, start_date=s.isoformat(), end_date=e.isoformat())
        row['channels'] = [ch for ch in dict.fromkeys(row['channels']) if ch][:6]
        campaigns.append(row)
    if sum(c['budget_percent'] for c in campaigns) <= 0:
        for c in campaigns:
            c['budget_percent'] = 100 / len(campaigns)
    _rescale(campaigns, 'budget_percent')
    ids = {c['id'] for c in campaigns}

    # Calendar: inside the period, known campaign ids, then the events Radar knows about (dates from the list).
    calendar, dropped = [], 0
    for item in plan.calendar:
        if not start <= item.date <= end:
            dropped += 1
            continue
        row = item.model_dump(mode='json')
        row['kind'] = row['kind'] if row['kind'] in EVENT_KINDS else 'content'
        if row['kind'] in ('holiday', 'shopping', 'tech', 'season'):
            continue   # event dates come from the events list below, never from the model
        if row['campaign_id'] not in ids:
            row['campaign_id'] = ''
        if row.get('end_date') and row['end_date'] < row['date']:
            row['end_date'] = None
        row['confirmed'], row['source'] = True, 'plan'
        calendar.append(row)
    if dropped:
        notes.append(f'{dropped} calendar entr{"y was" if dropped == 1 else "ies were"} outside the plan period and left out.')
    for c in campaigns:
        calendar.append({'date': c['start_date'], 'end_date': c['end_date'], 'title': c['name'], 'kind': 'campaign',
                         'campaign_id': c['id'], 'channel': ', '.join(c['channels'][:3]), 'note': c['idea'],
                         'confirmed': True, 'source': 'campaign'})
    calendar += events_between(start, end)
    for typed in inputs.get('typed_events') or []:
        calendar.append(typed)
    calendar.sort(key=lambda r: (r['date'], r['kind'] != 'campaign'))

    # Money: shares only from the model; amounts from the budget the user typed.
    budget = [b.model_dump() for b in plan.budget if b.channel]
    if not budget:
        budget = [{'channel': 'Meta ads', 'percent': 60, 'purpose': ''}, {'channel': 'LinkedIn ads', 'percent': 30, 'purpose': ''},
                  {'channel': 'Contingency', 'percent': 10, 'purpose': 'Held back for what works best.'}]
        notes.append('The budget split was missing, so a standard 60/30/10 split was used.')
    elif abs(sum(b['percent'] for b in budget) - 100) > 0.5:
        notes.append('Budget shares did not add up to 100%, so they were rescaled.')
    budget = _rescale(_clip(budget, 8))
    monthly, total = inputs.get('budget'), inputs.get('budget_total')
    for b in budget:
        b['amount'] = None if total is None else round(total * b['percent'] / 100, 2)
    months = months_between(start, end)
    by_month = []
    for m in months:
        first = date.fromisoformat(m['month'] + '-01')
        last = date(first.year, first.month, monthrange(first.year, first.month)[1])
        live = [c['name'] for c in campaigns if c['start_date'] <= last.isoformat() and c['end_date'] >= first.isoformat()]
        by_month.append({**m, 'amount': None if monthly is None else round(monthly * m['days'] / 30.4, 2),
                         'campaigns': live})
    for c in campaigns:
        c['amount'] = None if total is None else round(total * c['budget_percent'] / 100, 2)

    content_plan = plan.content_plan.model_dump()
    content_plan['mix'] = _rescale([m for m in content_plan['mix'] if m['label']][:8])
    content_plan['rhythm'] = [r for r in content_plan['rhythm'] if r['platform'] in PLATFORMS][:3]
    for r in content_plan['rhythm']:
        r['per_week'] = max(0, min(14, round(r['per_week'] or 0, 1)))
        r['voice'] = (inputs.get('voices') or {}).get(r['platform'], {}).get('label', '')
        r['language'] = LANGUAGE[r['platform']]

    brief = plan.competitive_brief.model_dump()
    for p in brief['positioning_map']['points']:
        p['x'], p['y'] = max(0, min(100, p['x'])), max(0, min(100, p['y']))
    brief['rivals'] = brief['rivals'][:6]
    brief['messaging_matrix'] = brief['messaging_matrix'][:7]
    brief['content_gaps'] = brief['content_gaps'][:8]

    positioning = plan.positioning.model_dump()
    positioning['pillars'] = positioning['pillars'][:3]
    lines = {r['platform']: r['line'] for r in positioning['by_platform'] if r['platform'] in PLATFORMS}
    positioning['by_platform'] = [{'platform': p, 'line': lines.get(p, ''), 'language': LANGUAGE[p],
                                   'voice': (inputs.get('voices') or {}).get(p, {}).get('label', '')} for p in PLATFORMS]

    kpis = []
    for k in plan.kpis[:8]:
        row = k.model_dump()
        if row['campaign_id'] not in ids:
            row['campaign_id'] = ''
        kpis.append(row)

    saved = {
        'version': 2,
        'overview': plan.overview.model_dump(),
        'competitive_brief': brief,
        'positioning': positioning,
        'campaigns': campaigns,
        'calendar': calendar[:80],
        'content_plan': content_plan,
        'budget': budget,
        'by_month': by_month,
        'kpis': kpis,
        'creative_ideas': [i.model_dump() for i in plan.creative_ideas[:8]],
        'risks': [r.model_dump() for r in plan.risks[:6]],
        'next_steps': [s.model_dump() for s in plan.next_steps[:8]],
        'assumptions': plan.assumptions[:6],
        'currency': inputs.get('currency', ''),
        'budget_monthly': monthly,
        'budget_total': total,
        'executive_summary': plan.overview.summary or plan.positioning.statement,
    }
    keep = {'statement_ar', 'hook_ar', 'visual_prompt'}
    for key, value in list(saved.items()):
        if key in ('calendar', 'by_month', 'budget', 'currency'):
            continue
        saved[key] = _texts(value, 600)
    for c, raw_c in zip(saved['campaigns'], campaigns):
        for k in keep:
            if k in raw_c:
                c[k] = _cut(raw_c[k], 900)
    return saved, notes


# ---- What n8n reads: the client, the market and the brief, as prompt-ready text --------------------------

def _line(text, limit=220):
    return _cut(text, limit)


def radar_pack(db: Session, inputs: dict) -> dict:
    """Everything the strategy agents need, built from the Radar captures (no AI here)."""
    from api.routers.watch import names_of, profile_text, signals_query
    from api.watch.insight import claim_map, companies, content_gaps, effective_score, latest, week_snapshot
    from db.watch_models import WatchBrief, WatchClient, WatchOpportunity

    client = db.get(WatchClient, inputs['client_id'])
    if client is None:
        raise LookupError('The Radar client of this plan was deleted.')
    use = set(inputs.get('inputs') or RADAR_INPUTS)
    start, end = date.fromisoformat(inputs['start_date']), date.fromisoformat(inputs['end_date'])
    names = names_of(db, client.id)
    week = week_snapshot(db, client)
    data = latest(db, client.id)
    comps = companies(db, client)

    rivals = []
    for c in comps[1:]:
        snaps = data.get(c['key'], {})
        parts = [f"[{c['name']}] tier {c['tier']}"]
        home = snaps.get('page:homepage')
        if home:
            f = home['snapshot'].fields or {}
            parts.append('homepage headline: ' + _line(f.get('headline'), 200))
            if f.get('headings'):
                parts.append('headings: ' + _line('; '.join((f.get('headings') or [])[:10]), 300))
        pricing = snaps.get('page:pricing')
        if pricing and (pricing['snapshot'].fields or {}).get('prices'):
            parts.append('prices: ' + _line('; '.join(str(p.get('text') or p) for p in pricing['snapshot'].fields['prices'][:6]), 240))
        for k in ('linkedin', 'instagram', 'facebook'):
            if k in snaps:
                m = snaps[k]['snapshot'].metrics or {}
                bits = [f"{k}: {m.get('followers') or '?'} followers"]
                if m.get('engagement_rate') is not None:
                    bits.append(f"engagement {m['engagement_rate']}%")
                if m.get('posts_per_week') is not None:
                    bits.append(f"{m['posts_per_week']} posts/week")
                if m.get('bio'):
                    bits.append('bio: ' + _line(m['bio'], 160))
                parts.append(', '.join(bits))
        row = next((r for r in week['rivals'] if r['key'] == c['key']), None)
        if row and row.get('jobs'):
            parts.append(f"{row['jobs']} open jobs")
        rivals.append(' · '.join(parts))

    you = []
    for k in ('linkedin', 'instagram', 'facebook'):
        snap = (data.get('client', {}).get(k) or {}).get('snapshot')
        if snap:
            m = snap.metrics or {}
            you.append(f"{k}: {m.get('followers') or '?'} followers, engagement {m.get('engagement_rate')}%, "
                       f"{m.get('posts_per_week')} posts/week")
    standing = [f"{s['platform']}: you {s['you']}% vs rivals' average {s['rivals_avg']}% (leader {s['leader']} "
                f"{s['leader_rate']}%)" for s in week['standing']]

    moves = []
    if 'moves' in use:
        since = datetime.utcnow() - timedelta(days=45)
        rows = [(s, sc) for s, sc, _ in signals_query(db, client.id).filter_by().all()
                if s.created_at and s.created_at >= since and (effective_score(sc) or 0) >= 3]
        rows.sort(key=lambda r: (effective_score(r[1]) or 0, r[0].created_at), reverse=True)
        moves = [f"[{s.id}] score {effective_score(sc)} · {names.get(s.competitor_id, client.name) if s.competitor_id else client.name}"
                 f" · {s.type} · {_line(s.title, 160)}. Means for {client.name}: {_line(s.meaning, 220)}" for s, sc in rows[:20]]

    claims = []
    if 'claims' in use:
        claims = [f"{c['label']}: {c['status']} ({c['rival_count']} rivals), "
                  f"{client.name} {'claims it' if c['client_claims'] else 'does not claim it'}" for c in claim_map(db, client)]

    opps, focus = [], None
    if 'opportunities' in use or inputs.get('opportunity_id'):
        q = db.query(WatchOpportunity).filter(WatchOpportunity.client_id == client.id,
                                              WatchOpportunity.status.in_(('new', 'accepted', 'acted')))
        for o in q.order_by(WatchOpportunity.week_start.desc(), WatchOpportunity.rank).limit(8):
            text = (f"[opp:{o.id}] {_line(o.angle, 200)} · claim {o.claim} · audience {_line(o.audience, 120)} · "
                    f"why now: {_line(o.why_now, 200)} · rivals saying: {_line(o.competitors_saying, 160)} · "
                    f"wrong if: {_line(o.wrong_if, 160)} · confidence {o.confidence} · expires {o.expires_on}")
            if o.id == inputs.get('opportunity_id'):
                focus = text
            elif 'opportunities' in use:
                opps.append(text)

    ads = []
    if 'ads' in use:
        for c in comps[1:]:
            ad = data.get(c['key'], {}).get('ads')
            if not ad or any('page_name' not in a for a in ad['snapshot'].items or []):
                continue
            live = [a for a in ad['snapshot'].items or [] if a.get('active')]
            for a in live[:4]:
                ads.append(f"{c['name']} live ad since {a.get('start') or '?'}: {_line(a.get('headline'), 120)} — "
                           f"{_line(a.get('body'), 220)}" + (f" [CTA {a.get('cta')}]" if a.get('cta') else ''))
            if not live:
                ads.append(f'{c["name"]}: no live ads in Egypt.')

    posts = []
    if 'posts' in use:
        posts = [f"{p['company']} on {p['platform']} ({p['engagement']} interactions, {str(p.get('date') or '')[:10]}): "
                 f"{_line(p['caption'], 240)}" for p in week['posts']]

    last_brief = ''
    if 'brief' in use:
        b = (db.query(WatchBrief).filter_by(client_id=client.id, status='ready')
             .order_by(WatchBrief.week_start.desc()).first())
        if b:
            items = '; '.join(_line(i.get('title') or i.get('headline') or '', 140) for i in (b.items or [])[:6])
            last_brief = f'Week of {b.week_start}: {_line(b.headline, 200)}. ' + (items or '') + ' ' + \
                ' '.join(week['takeaways'][:4])

    gaps = [f"{g['label']}: {g['detail']}" for g in content_gaps(db, client)]

    voices = inputs.get('voices') or {}
    voice_text = '\n'.join(f"{p}: {voices.get(p, {}).get('label', '')} ({voices.get(p, {}).get('style', '')}). "
                           f"Write {p} lines in {LANGUAGE[p]}." for p in PLATFORMS)

    events = events_between(start, end)
    event_text = '\n'.join(f"{e['date']}{' to ' + e['end_date'] if e['end_date'] else ''}: {e['title']} ({e['kind']}"
                           f"{', date to confirm' if not e['confirmed'] else ''})" for e in events)
    if inputs.get('events'):
        event_text += f"\nThe client's own dates (typed by the user): {inputs['events']}"

    money = ('not given' if inputs.get('budget') is None else
             f"{inputs['budget']:,.0f} {inputs['currency']} a month, {inputs.get('budget_total') or 0:,.0f} "
             f"{inputs['currency']} for the whole plan")
    months = ', '.join(m['label'] for m in months_between(start, end))
    planning = (f"Goal: {inputs['goal']}. {inputs.get('objective') or ''}\n"
                f"Audience: {inputs.get('audience') or client.audience or 'use the client profile'}\n"
                f"Period: {inputs['start_date']} to {inputs['end_date']} ({months}). Today is {date.today().isoformat()}.\n"
                f"Budget: {money}. Paid channels allowed: {', '.join(inputs.get('paid') or []) or 'none (organic only)'}.\n"
                f"Organic platforms: LinkedIn, Instagram, Facebook.\n"
                f"Constraints: {inputs.get('constraints') or 'none'}")
    if focus:
        planning += f'\nBuild the plan around this Radar opportunity first: {focus}'

    rival_names = [c['name'] for c in comps[1:]]
    return {
        'ready': True,
        'plan_id': inputs.get('plan_id'),
        'client': client.name,
        'profile': profile_text(client),
        'planning_brief': planning,
        'rival_names': ', '.join(rival_names) or 'none confirmed yet',
        'rivals': '\n'.join(rivals) or 'No confirmed competitors yet.',
        'you': '\n'.join(you + standing) or 'No social numbers for the client yet.',
        'moves': '\n'.join(moves) or 'none',
        'claims': '\n'.join(claims) or 'none',
        'opportunities': '\n'.join(opps) or 'none',
        'ads': '\n'.join(ads) or 'none',
        'posts': '\n'.join(posts) or 'none',
        'last_brief': last_brief or 'none',
        'gaps': '\n'.join(gaps) or 'none',
        'voices': voice_text,
        'events': event_text or 'none in this period',
        'start_date': inputs['start_date'],
        'end_date': inputs['end_date'],
        'months': months,
        'counts': {'rivals': len(rival_names), 'moves': len(moves), 'claims': len(claims), 'opportunities': len(opps),
                   'ads': len(ads), 'posts': len(posts), 'events': len(events)},
    }


def defaults(db: Session, client) -> dict:
    """What the New plan page shows before anything is typed: voices with Radar's pick, what Radar can feed in,
    the events in the default 90 days and the open opportunities."""
    from api.routers.watch import signals_query
    from api.watch.insight import claim_map, effective_score, week_snapshot
    from db.watch_models import WatchBrief, WatchOpportunity

    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=89)
    week = week_snapshot(db, client)
    since = datetime.utcnow() - timedelta(days=45)
    moves = sum(1 for s, sc, _ in signals_query(db, client.id).all()
                if s.created_at and s.created_at >= since and (effective_score(sc) or 0) >= 3)
    opps = (db.query(WatchOpportunity).filter(WatchOpportunity.client_id == client.id,
                                              WatchOpportunity.status.in_(('new', 'accepted')))
            .order_by(WatchOpportunity.week_start.desc(), WatchOpportunity.rank).limit(8).all())
    brief = (db.query(WatchBrief).filter_by(client_id=client.id, status='ready')
             .order_by(WatchBrief.week_start.desc()).first())
    voices = {}
    for p in PLATFORMS:
        key, why = suggest_voice(p)
        voices[p] = {'suggested': key, 'why': why}
    return {
        'client': {'id': client.id, 'name': client.name, 'audience': client.audience},
        'goals': list(GOALS),
        'budget': 20000, 'currency': 'EGP', 'start_date': start.isoformat(), 'end_date': end.isoformat(),
        'voices': voices,
        'voice_options': [{'key': k, 'label': v[0], 'style': v[1]} for k, v in VOICES.items()],
        'languages': LANGUAGE,
        'paid': list(PAID),
        'inputs': [
            {'key': 'opportunities', 'label': 'Open opportunities', 'count': len(opps)},
            {'key': 'moves', 'label': 'Rival moves (score 3 and up, 45 days)', 'count': moves},
            {'key': 'claims', 'label': 'Claim map', 'count': len(claim_map(db, client))},
            {'key': 'ads', 'label': 'Live rival ads', 'count': week['numbers'].get('live_ads') or 0},
            {'key': 'posts', 'label': 'Best rival posts', 'count': len(week['posts'])},
            {'key': 'brief', 'label': 'Last weekly brief', 'count': 1 if brief else 0,
             'note': brief.week_start if brief else ''},
        ],
        'opportunities': [{'id': o.id, 'angle': o.angle, 'claim': o.claim, 'confidence': o.confidence,
                           'expires_on': o.expires_on} for o in opps],
        'events': events_between(start, end),
    }


# ---- Results: ad numbers typed by hand, and the rule-based performance report ----------------------------

class ResultIn(BaseModel):
    week_start: date
    platform: Literal['Meta ads', 'LinkedIn ads', 'Instagram', 'Facebook', 'LinkedIn']
    campaign_id: str = Field(default='', max_length=12)
    spend: float = Field(default=0, ge=0, le=1e10)
    impressions: int = Field(default=0, ge=0, le=10**11)
    clicks: int = Field(default=0, ge=0, le=10**10)
    leads: int = Field(default=0, ge=0, le=10**9)
    notes: str = Field(default='', max_length=400)

    @model_validator(mode='after')
    def check(self):
        if self.clicks > self.impressions and self.impressions:
            raise ValueError('Clicks cannot be more than impressions.')
        self.week_start = self.week_start - timedelta(days=self.week_start.weekday())
        return self


# Typical B2B ranges in MENA, used only to say whether a number looks healthy. They are rough guides, not targets.
BENCH = {
    'Meta ads': {'ctr': 0.9, 'cpl': 250.0},
    'LinkedIn ads': {'ctr': 0.45, 'cpl': 900.0},
    'Instagram': {'ctr': 0.6, 'cpl': 250.0},
    'Facebook': {'ctr': 0.9, 'cpl': 250.0},
    'LinkedIn': {'ctr': 0.45, 'cpl': 900.0},
}


def _rates(spend, impressions, clicks, leads):
    return {'spend': round(spend, 2), 'impressions': impressions, 'clicks': clicks, 'leads': leads,
            'ctr': round(clicks * 100 / impressions, 2) if impressions else None,
            'cpc': round(spend / clicks, 2) if clicks else None,
            'cpl': round(spend / leads, 2) if leads else None,
            'cpm': round(spend * 1000 / impressions, 2) if impressions else None}


def _sum(rows):
    return _rates(sum(r.spend for r in rows), sum(r.impressions for r in rows), sum(r.clicks for r in rows),
                  sum(r.leads for r in rows))


def _num(text):
    m = re.search(r'(\d[\d,]*(?:\.\d+)?)', str(text or ''))
    return float(m.group(1).replace(',', '')) if m else None


def _elapsed(inputs: dict, rows: list) -> float:
    """Share of the plan period run by the end of the latest week typed in (0.05 to 1)."""
    try:
        start, end = date.fromisoformat(inputs['start_date']), date.fromisoformat(inputs['end_date'])
        last = max(date.fromisoformat(r['week_start'] if isinstance(r, dict) else r.week_start) for r in rows) + timedelta(days=6)
    except (KeyError, ValueError, TypeError):
        return 1.0
    days = max((end - start).days + 1, 1)
    return min(max(((last - start).days + 1) / days, 0.05), 1.0)


def results_report(plan: dict, inputs: dict, rows: list, currency: str) -> dict:
    """Wins, misses and next moves from the typed numbers, against the plan's KPIs and the benchmarks."""
    total = _sum(rows)
    by_platform = {}
    for p in sorted({r.platform for r in rows}):
        part = [r for r in rows if r.platform == p]
        by_platform[p] = _sum(part)
    names = {c['id']: c['name'] for c in plan.get('campaigns') or []}
    by_campaign = []
    for cid in sorted({r.campaign_id for r in rows}):
        by_campaign.append({'campaign_id': cid, 'name': names.get(cid, 'Not linked to a campaign'),
                            **_sum([r for r in rows if r.campaign_id == cid])})
    weeks = []
    for w in sorted({r.week_start for r in rows}):
        weeks.append({'week_start': w, **_sum([r for r in rows if r.week_start == w])})

    wins, misses, moves = [], [], []
    for p, s in by_platform.items():
        b = BENCH.get(p, {})
        if s['ctr'] is not None and b.get('ctr'):
            if s['ctr'] >= b['ctr']:
                wins.append(f'{p} click rate is {s["ctr"]}%, at or above the usual {b["ctr"]}%.')
            else:
                misses.append(f'{p} click rate is {s["ctr"]}%, under the usual {b["ctr"]}%.')
                moves.append(f'Refresh the {p} creative: test a new hook and picture against the current one for a week.')
        if s['cpl'] is not None and b.get('cpl'):
            if s['cpl'] <= b['cpl']:
                wins.append(f'{p} cost per lead is {s["cpl"]:,.0f} {currency}, inside the usual range.')
            else:
                misses.append(f'{p} cost per lead is {s["cpl"]:,.0f} {currency}, above the usual {b["cpl"]:,.0f}.')
        if s['spend'] and not s['leads']:
            misses.append(f'{p} spent {s["spend"]:,.0f} {currency} with no leads yet.')
            moves.append(f'Check the {p} lead form or landing page works, and narrow the audience before spending more.')
    paid = {p: s for p, s in by_platform.items() if s['cpl'] is not None}
    if len(paid) >= 2:
        best = min(paid, key=lambda p: paid[p]['cpl'])
        worst = max(paid, key=lambda p: paid[p]['cpl'])
        if best != worst:
            moves.insert(0, f'Move 10 to 20% of the {worst} budget to {best}: its leads cost '
                            f'{paid[best]["cpl"]:,.0f} {currency} against {paid[worst]["cpl"]:,.0f}.')
    if len(weeks) >= 2 and weeks[-1]['ctr'] is not None and weeks[-2]['ctr'] is not None:
        if weeks[-1]['ctr'] < weeks[-2]['ctr'] * 0.8:
            misses.append(f"Click rate fell from {weeks[-2]['ctr']}% to {weeks[-1]['ctr']}% last week: ads may be tiring.")
            moves.append('Swap in the next creative from the plan; ads tire after two to four weeks.')

    kpis = []
    for k in plan.get('kpis') or []:
        target = k.get('target_value') if k.get('target_value') is not None else _num(k.get('target'))
        name = (k.get('name') or '').lower()
        actual = None
        if 'lead' in name and 'cost' not in name and 'cpl' not in name:
            actual = total['leads']
        elif 'cpl' in name or 'cost per lead' in name:
            actual = total['cpl']
        elif 'ctr' in name or 'click rate' in name or 'click-through' in name:
            actual = total['ctr']
        elif 'impression' in name or 'reach' in name:
            actual = total['impressions']
        elif 'click' in name:
            actual = total['clicks']
        lower_better = 'cost' in name or 'cpl' in name or 'cpc' in name
        rate = lower_better or 'ctr' in name or 'rate' in name
        state = None
        if not rows:
            actual = None
        if actual is not None and target:
            # Counts (leads, clicks) are judged against the share of the plan already run, not the full target.
            goal = target if rate else target * _elapsed(inputs, rows)
            ratio = (goal / actual if actual else 0) if lower_better else (actual / goal if goal else 1)
            state = 'on track' if ratio >= 0.9 else 'behind'
            (wins if state == 'on track' else misses).append(
                f"{k.get('name')}: {actual:,.2f}".rstrip('0').rstrip('.') + f" against a target of {k.get('target')}.")
        kpis.append({'name': k.get('name'), 'target': k.get('target'), 'actual': actual, 'state': state})
    if total['spend'] and inputs.get('budget_total'):
        used = total['spend'] * 100 / inputs['budget_total']
        start, end = date.fromisoformat(inputs['start_date']), date.fromisoformat(inputs['end_date'])
        gone = max(0, min(1, ((date.today() - start).days + 1) / ((end - start).days + 1))) * 100
        if used > gone + 15:
            misses.append(f'{used:.0f}% of the budget is spent but only {gone:.0f}% of the plan time has passed.')
            moves.append('Lower daily budgets or pause the weakest ad set so the money lasts to the end of the plan.')
        elif used < gone - 25:
            moves.append(f'Only {used:.0f}% of the budget is spent after {gone:.0f}% of the time: raise budgets on what works.')
    if not rows:
        moves = ['Type the first week of ad numbers to see the report.']
    return {'totals': total, 'by_platform': by_platform, 'by_campaign': by_campaign, 'weeks': weeks, 'kpis': kpis,
            'wins': wins[:6], 'misses': misses[:6], 'next_moves': list(dict.fromkeys(moves))[:5], 'currency': currency,
            'benchmarks': BENCH, 'rows': len(rows)}
