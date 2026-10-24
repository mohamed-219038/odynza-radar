"""Is a social profile really this company's? Checks the handle and what the profile says about itself.

A shared name is not enough: "Odynza Egypt" on Facebook turned out to be a Hurghada tour operator, not the
AI company. A profile is kept when the company's own website links to it, or when its search snippet mentions
the company's website or talks about the same business. A profile whose snippet is clearly about something
else is removed and reported.
"""
import re
from urllib.parse import parse_qs, urlsplit

from api.competitors import host

STOP = set('''about after again also because been before being below between both company could does doing down during each
from further have having here into just more most other over same should some such than that their them then there these
they this those through under until very were what when where which while will with would your yours ours page official
pages likes like talking followers following posts post photos videos home contact info information welcome best
facebook instagram linkedin people view profile company's limited group inc llc ltd egypt cairo world online'''.split())


def compact(value):
    return re.sub(r'\W', '', str(value or '')).casefold()


def topic_words(*texts):
    words = set()
    for text in texts:
        for word in re.findall(r'\w+', str(text or '').casefold()):
            if len(word) >= 4 and not word.isdigit() and word not in STOP:
                words.add(word)
    return words


def handle(channel, link):
    """The account part of a profile link: 'odynza' for instagram.com/odynza, the page name for facebook.com/p/Name-123."""
    parsed = urlsplit(link or '')
    parts = [p for p in parsed.path.split('/') if p]
    if channel == 'facebook':
        if parts[:1] == ['profile.php']:
            return (parse_qs(parsed.query).get('id') or [''])[0]
        if parts[:1] in (['p'], ['pages']) and len(parts) >= 2:
            return parts[1]
    if channel == 'linkedin':
        return parts[1] if len(parts) >= 2 else ''
    return parts[0] if parts else ''


def handle_matches(channel, link, name, website):
    """The handle starts with the company name or domain name (or spells its initials); numeric IDs cannot be checked."""
    raw = handle(channel, link)
    value = compact(raw)
    if not value or value.isdigit():
        return False
    label = compact(host(website).split('.')[0]) if website else ''
    key = compact(name)
    first = compact((re.findall(r'\w+', str(name or '')) or [''])[0])
    initials = ''.join(w[0] for w in re.split(r'[-._\s]+', raw.casefold()) if w and not w.isdigit())
    for k in (key, label, first if len(first) >= 4 else ''):
        if len(k) >= 3 and (value.startswith(k) or k.startswith(value) and len(value) >= 4):
            return True
    return len(initials) >= 3 and initials in (key, label)


def profile_key(url):
    parsed = urlsplit(url or '')
    network = '.'.join(host(url).split('.')[-2:])  # eg.linkedin.com, web.facebook.com -> the network itself
    return network, parsed.path.rstrip('/').casefold(), (parse_qs(parsed.query).get('id') or [''])[0]


def same_profile(a, b):
    return bool(a and b) and profile_key(a) == profile_key(b)


def verdict(link, rows, website, topics, name=''):
    """'matched' (snippet names the website or the same business), 'different' (clearly another business) or 'unknown'."""
    texts = [f"{hit['title']} {hit['description']}" for _, _, hit in rows if same_profile(hit['url'], link)]
    if not texts:
        return 'unknown', ''
    text = ' '.join(texts)
    domain = host(website)
    if domain and domain in text.casefold():
        return 'matched', text
    own = topic_words(name, host(website).split('.')[0] if website else '')
    topics, seen = topics - own, topic_words(text) - own
    overlap = topics & seen
    if len(overlap) >= (2 if len(topics) >= 8 else 1):
        return 'matched', text
    if len(seen) >= 5 and not overlap:
        return 'different', text
    return 'unknown', text


def describe(text, words=14):
    tokens = ' '.join(str(text or '').split()).split()
    return ' '.join(tokens[:words]) + ('…' if len(tokens) > words else '')
