"""Gemini REST calls shared by the company search, the competitor search and the image maker."""
import asyncio
import math
import os
import re
from pathlib import Path

import httpx
from dotenv import dotenv_values

API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'
DEFAULT_MODEL = 'gemini-3.5-flash-lite'
# Google answers 500/502/503/504 when a model is briefly overloaded; these usually pass within seconds.
BUSY_STATUSES = {500, 502, 503, 504}
RETRY_WAITS = (3, 8, 20)
MAX_RATE_WAIT = 65


def gemini_key():
    # A locally entered key takes precedence over an inherited/stale shell key.
    local = dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('GEMINI_API_KEY')
    return (local or os.getenv('GEMINI_API_KEY', '')).strip()


class GeminiError(ValueError):
    pass


def gemini_error(status):
    hints = {
        400: 'check model support, request settings and Gemini key validity',
        401: 'check GEMINI_API_KEY and restart the API',
        403: 'check Google project permissions, key restrictions and API availability',
        404: 'model unavailable; run check_gemini.py to verify access',
        413: 'reduce GEMINI_MAX_INPUT_TOKENS or RESEARCH_MAX_INPUT_CHARS',
        429: 'quota/rate limit reached; check Google AI Studio limits before retrying',
    }
    return f'Gemini returned HTTP {status}; ' + hints.get(status, 'check Gemini service status and retry later')


def response_error(response):
    try:
        error = response.json().get('error', {})
        reasons = {item.get('reason') for item in error.get('details', []) if isinstance(item, dict)}
        if 'API_KEY_INVALID' in reasons or 'api key not valid' in str(error.get('message', '')).lower():
            return 'Gemini rejected the API key; replace GEMINI_API_KEY with a valid Google AI Studio key'
        if response.status_code == 429:
            # Only expose quota identifiers, model IDs and numbers. Provider messages
            # can echo credentials or research inputs, so never display their raw text.
            hints = []
            details = error.get('details', [])
            for detail in details[:20] if isinstance(details, list) else []:
                if not isinstance(detail, dict):
                    continue
                violations = detail.get('violations', [])
                for violation in violations[:3] if isinstance(violations, list) else []:
                    if not isinstance(violation, dict):
                        continue
                    limit = str(violation.get('quotaId', ''))
                    model = (violation.get('quotaDimensions') or {}).get('model', '')
                    value = str(violation.get('quotaValue', ''))
                    parts = []
                    if re.fullmatch(r'Generate[A-Za-z0-9_-]{1,150}', limit):
                        parts.append('limit '+limit)
                    if isinstance(model, str) and re.fullmatch(r'gemini-[A-Za-z0-9._-]{1,80}', model):
                        parts.append('model '+model)
                    if re.fullmatch(r'\d{1,13}', value):
                        parts.append('quota '+value)
                    if parts:
                        hints.append(', '.join(parts))
                    if value == '0':
                        hints.append('This limit has no quota allocated; check model access in the Google project linked to your key')
                delay = detail.get('retryDelay', '')
                if isinstance(delay, str) and re.fullmatch(r'\d{1,5}(?:\.\d{1,9})?s', delay):
                    hints.append(f'Google suggests retrying after {math.ceil(float(delay[:-1]))} seconds')
            if not any('retrying after' in h for h in hints):
                delay = response.headers.get('Retry-After', '')
                if re.fullmatch(r'\d{1,5}', delay):
                    hints.append(f'Google suggests retrying after {delay} seconds')
            message = gemini_error(429)
            if hints:
                message += '; ' + '; '.join(dict.fromkeys(hints))
            key = gemini_key()
            if key:
                message = message.replace(key, '[redacted]')
            return re.sub(r'AIza[\w-]+', '[redacted]', message)[:1000]
        if response.status_code == 400:
            message = str(error.get('message', 'Invalid request'))
            key = gemini_key()
            if key:
                message = message.replace(key, '[redacted]')
            message = re.sub(r'AIza[\w-]+', '[redacted]', message)
            return 'Gemini rejected the request: ' + message[:500]
    except (ValueError, TypeError, AttributeError):
        pass
    return gemini_error(response.status_code)


def rate_wait(response):
    """Seconds Google asks us to wait after a per-minute limit, or None when waiting will not help (daily or zero quota)."""
    try:
        details = response.json().get('error', {}).get('details', [])
    except (ValueError, AttributeError):
        return None
    wait, per_minute = None, False
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        for violation in detail.get('violations', []) or []:
            if not isinstance(violation, dict):
                continue
            limit = str(violation.get('quotaId', ''))
            if str(violation.get('quotaValue', '')) == '0' or 'PerDay' in limit:
                return None
            per_minute = per_minute or 'PerMinute' in limit
        delay = detail.get('retryDelay', '')
        if isinstance(delay, str) and re.fullmatch(r'\d{1,5}(?:\.\d{1,9})?s', delay):
            wait = math.ceil(float(delay[:-1]))
    header = response.headers.get('Retry-After', '')
    if wait is None and re.fullmatch(r'\d{1,5}', header):
        wait = int(header)
    return wait if per_minute and wait is not None and wait <= MAX_RATE_WAIT else None


def fallback_model(model):
    """A second model to try when the chosen one stays overloaded; GEMINI_FALLBACK_MODEL=off disables it."""
    value = os.getenv('GEMINI_FALLBACK_MODEL', '').strip() or DEFAULT_MODEL
    if value.lower() == 'off' or value == model or not re.fullmatch(r'gemini-[a-zA-Z0-9._-]+', value):
        return None
    return value


def clean_json_output(content):
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        text = "\n".join(lines).strip()
    return text


def extract_json(content):
    """Strip code fences and any preamble/trailing text around the JSON object."""
    text = clean_json_output(content)
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


class GeminiClient:
    def __init__(self):
        self.model = os.getenv('GEMINI_MODEL', '').strip() or DEFAULT_MODEL
        if not re.fullmatch(r'gemini-[a-zA-Z0-9._-]+', self.model):
            raise GeminiError('GEMINI_MODEL must be a Gemini model ID')
        self.usage = {}

    async def _post(self, client, action, payload):
        """One Gemini call. Busy servers are retried with growing waits, then the fallback model is tried;
        a per-minute rate limit is waited out once. Other errors fail at once, since retrying cannot fix them."""
        models = [self.model] + ([m] if action == 'generateContent' and getattr(self, 'allow_fallback', True)
                                  and (m := fallback_model(self.model)) else [])
        for model in models:
            rate_waited = False
            for attempt in range(len(RETRY_WAITS) + 1):
                try:
                    response = await client.post(f'{API_BASE}/{model}:{action}', json=payload)
                except httpx.TimeoutException:
                    if attempt == len(RETRY_WAITS):
                        raise
                    await asyncio.sleep(RETRY_WAITS[attempt])
                    continue
                if response.status_code in BUSY_STATUSES and attempt < len(RETRY_WAITS):
                    await asyncio.sleep(RETRY_WAITS[attempt])
                    continue
                if response.status_code == 429 and not rate_waited and (wait := rate_wait(response)) is not None:
                    rate_waited = True
                    await asyncio.sleep(wait + 1)
                    continue
                break
            if response.status_code in BUSY_STATUSES and model != models[-1]:
                continue
            if model != self.model and isinstance(getattr(self, 'usage', None), dict):
                self.usage['fallback_model'] = model
            break
        if response.status_code >= 400:
            # Do not store raw provider bodies, which can echo inputs/credentials.
            message = response_error(response)
            if response.status_code in BUSY_STATUSES:
                message = f'Gemini was busy (HTTP {response.status_code}) after {len(RETRY_WAITS) + 1} tries' + \
                          (f' and on {models[-1]} too' if len(models) > 1 else '') + '; try again in a few minutes'
            raise GeminiError(f'{action}: {message}')
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError
            return body
        except ValueError:
            raise GeminiError('Gemini returned an invalid response') from None
