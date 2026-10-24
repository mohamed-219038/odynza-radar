"""Post images and reel key frames, and the files they are saved to.

Two image makers:
- FLUX.2 [klein] on Cloudflare Workers AI (free daily allowance), used when CLOUDFLARE_ACCOUNT_ID and
  CLOUDFLARE_API_TOKEN are set in .env. Model: CLOUDFLARE_IMAGE_MODEL (default @cf/black-forest-labs/flux-2-klein-4b).
- Nano Banana (Gemini image models, GEMINI_IMAGE_MODEL), which needs a Gemini key with paid image quota.
IMAGE_PROVIDER=cloudflare|gemini forces one; by default Cloudflare is used when it is set up.
The company logo and up to two of its own post images go along as style references, so the brand look comes from
the company's existing content. If no image can be made, the draft keeps its prompt so the image can be made in
the Gemini app and uploaded.
"""
import base64
import io
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


def image_maker():
    """FLUX.2 on Cloudflare when it is set up (or IMAGE_PROVIDER=cloudflare), otherwise Nano Banana."""
    choice = os.getenv('IMAGE_PROVIDER', '').strip().lower()
    cloudflare = bool(os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip() and os.getenv('CLOUDFLARE_API_TOKEN', '').strip())
    if choice == 'cloudflare' or (choice != 'gemini' and cloudflare):
        return FluxMaker()
    return ImageMaker()


def is_quota_error(error):
    text = str(error).casefold()
    return '429' in text or 'quota' in text or 'neuron' in text or 'daily free allocation' in text


def plain_image_error(error):
    text = str(error).casefold()
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
    return 'The image service was busy. Press Make image again in a few minutes.'
