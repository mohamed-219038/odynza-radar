"""How much a competitor change matters to the client, as a senior marketer would rank it.

The scale below is sent to the n8n impact agent with every batch; `adjust` then holds each AI score inside a band
for its kind of change and rival tier, so the weekly brief ranks the same way every week. Paid ads rank high on
purpose: a rival paying to reach the client's buyers is the clearest sign of where it is pushing right now.
"""
from __future__ import annotations

SCALE = (
    '5 = act this week: a direct rival moves on the client\'s buyers with money or price (a new or bigger ad campaign, '
    'a price cut or discount on a plan the client competes with, a launch that copies the client\'s main offer). '
    '4 = plan a response this month: any rival ad running or stopping, a direct rival\'s new offer, price change, '
    'positioning or headline change, a big-name customer win, or a rival claim that contradicts the client. '
    '3 = worth knowing, include in the brief: adjacent rivals\' offer or positioning changes, notable press or roundup '
    'mentions, hiring that shows a new direction, a post that did unusually well. '
    '2 = note it, no action: routine posts, follower changes, small copy edits with no new promise, the client\'s own '
    'changes. 1 = archive: noise, cosmetic or date-only changes. '
    'Paid ads always count: spending money shows intent, so treat every rival ad as at least a 4 for direct and '
    'adjacent rivals and at least a 3 for the rest; raise to 5 when it targets the client\'s audience or offer.'
)

# (lowest, highest) score per change type for each rival tier; the client's own changes stay low.
BANDS: dict[str, dict[str, tuple[int, int]]] = {
    'ad':          {'direct': (4, 5), 'adjacent': (4, 5), 'aspirational': (3, 5), 'emerging': (3, 5)},
    'pricing':     {'direct': (4, 5), 'adjacent': (3, 5), 'aspirational': (2, 4), 'emerging': (2, 4)},
    'offer':       {'direct': (3, 5), 'adjacent': (3, 5), 'aspirational': (2, 4), 'emerging': (2, 4)},
    'positioning': {'direct': (3, 5), 'adjacent': (2, 4), 'aspirational': (2, 4), 'emerging': (2, 4)},
    'client':      {'direct': (3, 5), 'adjacent': (2, 4), 'aspirational': (2, 4), 'emerging': (2, 4)},
    'claim':       {'direct': (2, 4), 'adjacent': (2, 4), 'aspirational': (1, 3), 'emerging': (1, 3)},
    'partnership': {'direct': (2, 4), 'adjacent': (2, 4), 'aspirational': (1, 3), 'emerging': (1, 3)},
    'mention':     {'direct': (2, 3), 'adjacent': (2, 3), 'aspirational': (1, 3), 'emerging': (1, 3)},
    'hiring':      {'direct': (2, 3), 'adjacent': (1, 3), 'aspirational': (1, 3), 'emerging': (1, 3)},
    'social':      {'direct': (2, 3), 'adjacent': (1, 3), 'aspirational': (1, 3), 'emerging': (1, 3)},
    'content':     {'direct': (2, 3), 'adjacent': (1, 3), 'aspirational': (1, 3), 'emerging': (1, 3)},
}
CLIENT_BAND = (1, 2)   # the client's own changes, unless the client corrects them


def adjust(kind: str, tier: str, score: int, from_ads_source: bool = False) -> tuple[int, str]:
    """The AI score held inside its band, and a short note when it was moved (empty when it was not)."""
    kind = 'ad' if from_ads_source else (kind or '').lower()
    if tier == 'client':
        low, high = CLIENT_BAND
    else:
        low, high = BANDS.get(kind, {}).get(tier, (1, 5))
    fixed = min(max(int(score), low), high)
    if fixed == score:
        return fixed, ''
    label = 'rival ads' if kind == 'ad' else f'{kind or "this"} changes'
    who = 'your own changes' if tier == 'client' else f'{label} from a {tier} rival'
    return fixed, f'Scored {score} by the AI, set to {fixed}: {who} rank {low} to {high}.'
