"""Post images and reel key frames, and the files they are saved to.

Three image makers:
- OpenRouter image models (paid, a few cents an image), used when OPENROUTER_API_KEY is set in .env.
  Model: OPENROUTER_IMAGE_MODEL (default google/gemini-3.1-flash-image). When Cloudflare is also set up it is the
  fallback if an OpenRouter image fails (no credit, busy, refused).
- FLUX.2 [klein] on Cloudflare Workers AI (free daily allowance), used when CLOUDFLARE_ACCOUNT_ID and
  CLOUDFLARE_API_TOKEN are set in .env. Model: CLOUDFLARE_IMAGE_MODEL (default @cf/black-forest-labs/flux-2-klein-4b).
- Nano Banana (Gemini image models, GEMINI_IMAGE_MODEL), which needs a Gemini key with paid image quota.
IMAGE_PROVIDER=openrouter|cloudflare|gemini forces one; by default OpenRouter, then Cloudflare, then Gemini.
The company logo and up to two of its own post images go along as style references, so the brand look comes from
the company's existing content. If no image can be made, the draft keeps its prompt so the image can be made in
the Gemini app and uploaded.
"""
import base64
import io
import logging
import os
import re
from pathlib import Path

import httpx

from api.gemini import GeminiClient, GeminiError, gemini_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE_MODEL = 'gemini-2.5-flash-image'
DEFAULT_FLUX_MODEL = '@cf/black-forest-labs/flux-2-klein-4b'
# FLUX sizes (multiples of 16): about 1 to 1.3 megapixels keeps each image cheap in the free allowance.
FLUX_SIZE = {'1:1': (1024, 1024), '4:5': (1024, 1280), '9:16': (864, 1536)}
DEFAULT_OPENROUTER_MODEL = 'google/gemini-3.1-flash-image'
OPENROUTER_IMAGES_URL = 'https://openrouter.ai/api/v1/images'
OPENROUTER_MAX_REFERENCE = 1024
FLUX_MAX_REFERENCE = 511   # Workers AI wants reference images smaller than 512x512
REFERENCE_TYPES = {'image/png', 'image/jpeg', 'image/webp'}
UPLOAD_TYPES = {'image': {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'},
                'video': {'video/mp4': 'mp4', 'video/quicktime': 'mov', 'video/webm': 'webm'}}
MAX_UPLOAD = {'image': 15 * 1024 * 1024, 'video': 120 * 1024 * 1024}


def media_dir(run_id):
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', run_id):
        raise ValueError('bad run id')
    folder = ROOT / 'data' / 'content' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def media_file(run_id, item_id, kind):
    """The saved image or video of an item, or None."""
    folder = ROOT / 'data' / 'content' / run_id
    for ext in UPLOAD_TYPES[kind].values():
        path = folder / f'{item_id}-{kind}.{ext}'
        if path.exists():
            return path
    return None


def save_media(run_id, item_id, kind, data, ext):
    folder = media_dir(run_id)
    for old in UPLOAD_TYPES[kind].values():
        (folder / f'{item_id}-{kind}.{old}').unlink(missing_ok=True)
    path = folder / f'{item_id}-{kind}.{ext}'
    path.write_bytes(data)
    return path


def slide_file(run_id, item_id, number):
    """The saved picture of carousel slide number (2 and up; slide 1 is the draft's own image), or None."""
    folder = ROOT / 'data' / 'content' / run_id
    for ext in UPLOAD_TYPES['image'].values():
        path = folder / f'{item_id}-slide{number}.{ext}'
        if path.exists():
            return path
    return None


def save_slide(run_id, item_id, number, data, ext):
    folder = media_dir(run_id)
    for old in UPLOAD_TYPES['image'].values():
        (folder / f'{item_id}-slide{number}.{old}').unlink(missing_ok=True)
    path = folder / f'{item_id}-slide{number}.{ext}'
    path.write_bytes(data)
    return path


def sniff(data, kind):
    """The real file type from its first bytes; the browser's Content-Type is not trusted."""
    if kind == 'image':
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'image/png'
        if data.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg'
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'
    else:
        if data[4:8] == b'ftyp':
            return 'video/quicktime' if data[8:10] == b'qt' else 'video/mp4'
        if data.startswith(b'\x1a\x45\xdf\xa3'):
            return 'video/webm'
    return None


def image_prompt(content, brand_look, aspect):
    headline = content.get('on_image_text', '').strip()
    parts = [content.get('image_prompt', '').strip(),
             f'Brand look: {brand_look}' if brand_look else '',
             'Reference image 0 (the first one) is the company logo: place it small and unchanged in a corner. '
             'Any other reference images are the company\'s own past posts: match their colours, type and mood, '
             'but make a new design.',
             f'Render this headline exactly, spelled correctly, large and readable: "{headline}"' if headline else
             'No text on the image except the logo.',
             f'Aspect ratio {aspect}. Social media post quality, clean composition, no watermark, no fake UI text.']
    return '\n'.join(p for p in parts if p)


def slide_prompt(content, brand_look, aspect, number):
    """Slide number of a carousel; reference image 0 is slide 1 (the cover), so every slide shares its design."""
    slides = content.get('slides') or []
    slide = slides[number - 1] if 0 < number <= len(slides) else {}
    headline, body = (slide.get('headline') or '').strip(), (slide.get('body') or '').strip()
    last = number == len(slides)
    parts = [f'Slide {number} of {len(slides)} of the same social media carousel.',
             'Reference image 0 is slide 1, the cover. Keep exactly its background, colours, fonts, text sizes, margins, '
             'logo and its position, so the slides look like one set. Do not copy its headline.',
             f'Topic of the carousel: {content.get("image_prompt", "").strip()}' if content.get('image_prompt') else '',
             f'Brand look: {brand_look}' if brand_look else '',
             f'Render this headline exactly, spelled correctly, large and readable: "{headline}"' if headline else '',
             f'Under it, smaller and readable, render exactly: "{body}"' if body else '',
             'One simple supporting icon or illustration in the same style. '
             + ('This is the last slide: make the call to action stand out. ' if last else '')
             + f'Small page number "{number}/{len(slides)}" in a corner.',
             f'Aspect ratio {aspect}. No watermark, no other text, no fake UI text.']
    return '\n'.join(p for p in parts if p)


class ImageMaker(GeminiClient):
    allow_fallback = False   # a text model cannot stand in for an image model

    def __init__(self):
        super().__init__()
        self.model = os.getenv('GEMINI_IMAGE_MODEL', '').strip() or DEFAULT_IMAGE_MODEL
        if not re.fullmatch(r'gemini-[a-zA-Z0-9._-]+', self.model):
            raise GeminiError('GEMINI_IMAGE_MODEL must be a Gemini model name such as gemini-2.5-flash-image')

    async def make(self, prompt, aspect, references=()):
        key = gemini_key()
        if not key or key == 'your_gemini_api_key':
            raise GeminiError('Set GEMINI_API_KEY in .env to make images')
        parts = [{'text': prompt}] + [{'inline_data': {'mime_type': mime, 'data': base64.b64encode(data).decode()}}
                                      for data, mime in references if mime in REFERENCE_TYPES]
        payload = {'contents': [{'role': 'user', 'parts': parts}],
                   'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': aspect}}}
        self.usage = {}
        try:
            async with httpx.AsyncClient(timeout=180, headers={'x-goog-api-key': key}) as client:
                body = await self._post(client, 'generateContent', payload)
        except httpx.TimeoutException:
            raise GeminiError('The image model timed out') from None
        except httpx.RequestError:
            raise GeminiError('Unable to connect to Gemini to make the image') from None
        for candidate in body.get('candidates') or []:
            for part in (candidate.get('content') or {}).get('parts') or []:
                inline = part.get('inlineData') or part.get('inline_data') or {}
                if inline.get('data'):
                    data = base64.b64decode(inline['data'])
                    mime = sniff(data, 'image')
                    if mime:
                        return data, mime
        raise GeminiError('The image model returned no image (it may have refused the prompt); edit the prompt and try again')


def shrink(data, limit=FLUX_MAX_REFERENCE):
    """A PNG copy that fits in limit x limit, or None when it cannot be read (Pillow missing or a bad image)."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert('RGBA')
            img.thumbnail((limit, limit))
            out = io.BytesIO()
            img.save(out, 'PNG')
            return out.getvalue()
    except Exception:
        return None


class FluxMaker:
    """FLUX.2 on Cloudflare Workers AI: multipart form in, base64 image out."""
    name = 'cloudflare'

    def __init__(self):
        self.account = os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip()
        self.token = os.getenv('CLOUDFLARE_API_TOKEN', '').strip()
        self.model = os.getenv('CLOUDFLARE_IMAGE_MODEL', '').strip() or DEFAULT_FLUX_MODEL
        if not (self.account and self.token):
            raise GeminiError('Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env to make images with FLUX.2')
        if not re.fullmatch(r'[0-9a-fA-F]{32}', self.account):
            raise GeminiError('CLOUDFLARE_ACCOUNT_ID should be the 32-character account id from the Cloudflare dashboard')
        if not re.fullmatch(r'@cf/[a-z0-9._/-]+', self.model):
            raise GeminiError('CLOUDFLARE_IMAGE_MODEL must be a Workers AI model such as @cf/black-forest-labs/flux-2-klein-4b')

    async def make(self, prompt, aspect, references=()):
        width, height = FLUX_SIZE.get(aspect, FLUX_SIZE['1:1'])
        # Workers AI only accepts multipart; (None, value) sends a plain field inside the multipart body.
        form = {'prompt': (None, prompt[:2000]), 'width': (None, str(width)), 'height': (None, str(height))}
        count = 0
        for data, mime in references:
            small = shrink(data) if mime in REFERENCE_TYPES else None
            if small and count < 4:
                form[f'input_image_{count}'] = (f'reference-{count}.png', small, 'image/png')
                count += 1
        url = f'https://api.cloudflare.com/client/v4/accounts/{self.account}/ai/run/{self.model}'
        try:
            async with httpx.AsyncClient(timeout=180, headers={'Authorization': f'Bearer {self.token}'}) as client:
                response = await client.post(url, files=form)
        except httpx.TimeoutException:
            raise GeminiError('The image model timed out') from None
        except httpx.RequestError:
            raise GeminiError('Unable to connect to Cloudflare to make the image') from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not body.get('success', response.status_code < 400):
            detail = '; '.join(str(e.get('message', '')) for e in body.get('errors') or [] if isinstance(e, dict))
            raise GeminiError(f'Cloudflare returned HTTP {response.status_code}: {detail[:300]}')
        encoded = (body.get('result') or {}).get('image') or ''
        try:
            data = base64.b64decode(encoded)
        except ValueError:
            data = b''
        mime = sniff(data, 'image') if data else None
        if not mime:
            raise GeminiError('The image model returned no image (it may have refused the prompt); edit the prompt and try again')
        return data, mime


class OpenRouterMaker:
    """OpenRouter's image API: JSON in (prompt, aspect ratio, reference images as data URLs), base64 image out."""
    name = 'openrouter'

    def __init__(self):
        self.key = os.getenv('OPENROUTER_API_KEY', '').strip()
        self.model = os.getenv('OPENROUTER_IMAGE_MODEL', '').strip() or DEFAULT_OPENROUTER_MODEL
        if not self.key:
            raise GeminiError('Set OPENROUTER_API_KEY in .env to make images with OpenRouter')
        if not re.fullmatch(r'[a-z0-9._-]+/[a-zA-Z0-9._:-]+', self.model):
            raise GeminiError('OPENROUTER_IMAGE_MODEL must be an OpenRouter model id such as google/gemini-3.1-flash-image')

    async def make(self, prompt, aspect, references=()):
        refs = []
        for data, mime in references:
            if mime not in REFERENCE_TYPES or len(refs) >= 4:
                continue
            small = shrink(data, OPENROUTER_MAX_REFERENCE)
            data, mime = (small, 'image/png') if small else (data, mime)
            refs.append({'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{base64.b64encode(data).decode()}'}})
        payload = {'model': self.model, 'prompt': prompt[:4000], 'aspect_ratio': aspect, 'n': 1}
        if refs:
            payload['input_references'] = refs
        headers = {'Authorization': f'Bearer {self.key}', 'X-Title': 'Odynza Radar'}
        try:
            async with httpx.AsyncClient(timeout=240, headers=headers) as client:
                response = await client.post(OPENROUTER_IMAGES_URL, json=payload)
                body = response.json() if response.content else {}
                if response.status_code >= 400:
                    error = body.get('error') if isinstance(body, dict) else None
                    detail = error.get('message', '') if isinstance(error, dict) else str(error or '')
                    raise GeminiError(f'OpenRouter returned HTTP {response.status_code}: {detail[:300]}')
                for item in body.get('data') or []:
                    data = b''
                    if item.get('b64_json'):
                        data = base64.b64decode(item['b64_json'])
                    elif str(item.get('url', '')).startswith('https://'):
                        async with httpx.AsyncClient(timeout=60) as plain:   # no key on the picture link
                            got = await plain.get(item['url'])
                        data = got.content if got.status_code < 400 else b''
                    mime = sniff(data, 'image') if data else None
                    if mime:
                        return data, mime
        except httpx.TimeoutException:
            raise GeminiError('The image model timed out') from None
        except httpx.RequestError:
            raise GeminiError('Unable to connect to OpenRouter to make the image') from None
        except GeminiError:
            raise
        except ValueError:   # a broken JSON or base64 answer
            raise GeminiError('OpenRouter sent an answer that could not be read') from None
        raise GeminiError('The image model returned no image (it may have refused the prompt); edit the prompt and try again')


class FallbackMaker:
    """Tries the first maker, and the free Cloudflare one when that fails."""
    def __init__(self, first, backup):
        self.first, self.backup = first, backup
        self.name = first.name

    async def make(self, prompt, aspect, references=()):
        try:
            return await self.first.make(prompt, aspect, references)
        except GeminiError as error:
            try:
                return await self.backup.make(prompt, aspect, references)
            except GeminiError:
                raise error from None


def image_maker():
    """OpenRouter when its key is set (Cloudflare as its fallback), else FLUX.2 on Cloudflare, else Nano Banana.
    IMAGE_PROVIDER=openrouter|cloudflare|gemini forces one."""
    choice = os.getenv('IMAGE_PROVIDER', '').strip().lower()
    cloudflare = bool(os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip() and os.getenv('CLOUDFLARE_API_TOKEN', '').strip())
    openrouter = bool(os.getenv('OPENROUTER_API_KEY', '').strip())
    if choice == 'openrouter' or (choice not in ('cloudflare', 'gemini') and openrouter):
        maker = OpenRouterMaker()
        return FallbackMaker(maker, FluxMaker()) if cloudflare else maker
    if choice == 'cloudflare' or (choice != 'gemini' and cloudflare):
        return FluxMaker()
    return ImageMaker()


def is_quota_error(error):
    text = str(error).casefold()
    return '429' in text or 'http 402' in text or 'quota' in text or 'neuron' in text or 'daily free allocation' in text


def plain_image_error(error):
    logging.getLogger('radar.images').warning('Image not made: %s', error)
    text = str(error).casefold()
    if 'openrouter' in text:
        if 'http 402' in text or 'credit' in text:
            return ('Your OpenRouter account has no credit left for images. Add credit at openrouter.ai/settings/credits, '
                    'or remove OPENROUTER_API_KEY from .env to go back to the free Cloudflare images.')
        if 'http 401' in text or 'http 403' in text:
            return 'OpenRouter did not accept the key. Check OPENROUTER_API_KEY in .env (it starts with sk-or-).'
        if 'http 404' in text or 'http 400' in text and 'model' in text:
            return 'OpenRouter does not have this image model. Check OPENROUTER_IMAGE_MODEL in .env, or leave it empty.'
        if is_quota_error(error):
            return 'OpenRouter is limiting requests right now. Press Make image again in a minute.'
        if 'openrouter_api_key' in text or 'openrouter_image_model' in text:
            return str(error)
    if 'cloudflare' in text:
        if is_quota_error(error):
            return ("Today's free Cloudflare image allowance is used up. It renews at midnight UTC (2 or 3 am Cairo); "
                    'press Make image then, or make the image in the Gemini app and upload it.')
        if 'http 401' in text or 'http 403' in text or 'authentication' in text:
            return ('Cloudflare did not accept the token. Check CLOUDFLARE_API_TOKEN (it needs Workers AI permission) '
                    'and CLOUDFLARE_ACCOUNT_ID in .env.')
        if 'cloudflare_account_id' in text or 'cloudflare_api_token' in text or 'cloudflare_image_model' in text:
            return str(error)
    if is_quota_error(error):
        return ('Your Gemini key has no image quota (the Gemini API has no free image tier). Set up the free Cloudflare '
                'images (README, Cloudflare images), or copy the prompt into the Gemini app, make the image there and upload it here.')
    if '404' in text or 'model' in text and 'unavailable' in text:
        return 'This image model is not available for your key. Set GEMINI_IMAGE_MODEL in .env, or make the image in the Gemini app and upload it.'
    if 'gemini_api_key' in text or 'api key' in text:
        return 'The Gemini key is missing or not valid. Check GEMINI_API_KEY in .env.'
    if 'refused' in text or 'no image' in text:
        return 'The image model did not return an image. Edit the image prompt and try again.'
    detail = re.sub(r'\s+', ' ', str(error)).strip()[:240]
    return f'The image could not be made ({detail}). Press Make image again in a few minutes.'
