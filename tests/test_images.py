"""Post images for M2 drafts: the Gemini and FLUX (Cloudflare Workers AI) image makers. No real model calls."""
import io
import os
import unittest
from unittest.mock import patch

import httpx

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 200


class ImageMakerTests(unittest.TestCase):
    def test_nano_banana_request_and_image_parsing(self):
        import asyncio
        import base64
        import json
        import os
        from api.content_media import ImageMaker, image_prompt
        seen = []

        def respond(request):
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={'candidates': [{'content': {'parts': [
                {'text': 'Here it is'}, {'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}}]}}]})
        real = httpx.AsyncClient
        prompt = image_prompt({'image_prompt': 'Team at work', 'on_image_text': 'موافقة في دقيقة'}, 'Blue and white', '4:5')
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'k', 'GEMINI_IMAGE_MODEL': ''}), \
                patch('api.content_media.gemini_key', return_value='k'), \
                patch('api.content_media.httpx.AsyncClient', side_effect=lambda **kw: real(**kw, transport=httpx.MockTransport(respond))):
            data, mime = asyncio.run(ImageMaker().make(prompt, '4:5', [(PNG, 'image/png'), (b'<svg/>', 'image/svg+xml')]))
        self.assertEqual((data, mime), (PNG, 'image/png'))
        path, body = seen[0]
        self.assertTrue(path.endswith('/gemini-2.5-flash-image:generateContent'))
        self.assertEqual(body['generationConfig'], {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': '4:5'}})
        parts = body['contents'][0]['parts']
        self.assertEqual(len(parts), 2)  # the SVG logo is not a supported reference type
        self.assertIn('"موافقة في دقيقة"', parts[0]['text'])
        self.assertIn('Blue and white', parts[0]['text'])
        self.assertEqual(len(seen), 1)


class FluxMakerTests(unittest.TestCase):
    def test_flux_request_is_multipart_with_small_references(self):
        import asyncio
        import base64
        from PIL import Image
        from api.content_media import FluxMaker, image_maker
        big = io.BytesIO()
        Image.new('RGB', (1080, 1350), 'blue').save(big, 'JPEG')
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={'success': True, 'result': {'image': base64.b64encode(PNG).decode()}})
        real = httpx.AsyncClient
        env = {'CLOUDFLARE_ACCOUNT_ID': 'a' * 32, 'CLOUDFLARE_API_TOKEN': 'tok', 'CLOUDFLARE_IMAGE_MODEL': '', 'IMAGE_PROVIDER': ''}
        with patch.dict(os.environ, env), \
                patch('api.content_media.httpx.AsyncClient', side_effect=lambda **kw: real(**kw, transport=httpx.MockTransport(respond))):
            maker = image_maker()
            self.assertIsInstance(maker, FluxMaker)
            data, mime = asyncio.run(maker.make('A team at work', '4:5', [(big.getvalue(), 'image/jpeg'), (b'<svg/>', 'image/svg+xml')]))
        self.assertEqual((data, mime), (PNG, 'image/png'))
        request = seen[0]
        self.assertEqual(request.url.path, f"/client/v4/accounts/{'a' * 32}/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
        self.assertEqual(request.headers['authorization'], 'Bearer tok')
        self.assertTrue(request.headers['content-type'].startswith('multipart/form-data'))
        body = request.read()
        self.assertIn(b'name="width"\r\n\r\n1024', body)
        self.assertIn(b'name="height"\r\n\r\n1280', body)
        self.assertIn(b'name="input_image_0"', body)
        self.assertNotIn(b'name="input_image_1"', body)  # the SVG is skipped
        start = body.index(b'\x89PNG')
        with Image.open(io.BytesIO(body[start:])) as ref:
            self.assertLessEqual(max(ref.size), 511)

    def test_gemini_is_used_without_cloudflare(self):
        from api.content_media import ImageMaker, image_maker
        with patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID': '', 'CLOUDFLARE_API_TOKEN': '', 'IMAGE_PROVIDER': ''}):
            self.assertIsInstance(image_maker(), ImageMaker)


if __name__ == '__main__':
    unittest.main()
