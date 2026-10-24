"""Company logos: the sharpest icon a site offers wins, tiny icons only when nothing better exists. Network mocked."""
import asyncio
import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from api import logos


def png(side):
    out = io.BytesIO()
    Image.new('RGB', (side, side), (200, 30, 30)).save(out, 'PNG')
    data = out.getvalue()
    return data + b'\0' * max(0, 500 - len(data))   # past the 400-byte "globe" filter


PAGE = b'''<html><head><link rel="icon" href="/favicon-16.png" sizes="16x16">
<link rel="manifest" href="/site.webmanifest"></head><body></body></html>'''


def fake_site(files):
    async def fetch(url, accept='image/*', limit=None, total=35):
        path = '/' + url.split('/', 3)[3] if url.count('/') >= 3 else '/'
        if path in files:
            return files[path], url
        raise HTTPException(404, 'missing')
    return fetch


class Logos(unittest.TestCase):
    def setUp(self):
        logos._cache.clear()

    def find(self, files):
        with patch('api.logos.fetch_public', fake_site(files)):
            return asyncio.run(logos.company_logo('https://example.com/about'))

    def test_the_manifest_icon_beats_the_tab_icon(self):
        manifest = json.dumps({'icons': [{'src': '/icon-512.png', 'sizes': '512x512'}]}).encode()
        data, mime = self.find({'/': PAGE, '/favicon-16.png': png(16), '/site.webmanifest': manifest, '/icon-512.png': png(512)})
        self.assertEqual(mime, 'image/png')
        self.assertEqual(Image.open(io.BytesIO(data)).size, (512, 512))

    def test_a_tiny_icon_is_kept_only_when_nothing_bigger_exists(self):
        data, _ = self.find({'/': PAGE, '/favicon-16.png': png(16)})
        self.assertEqual(Image.open(io.BytesIO(data)).size, (16, 16))

    def test_the_logo_marked_in_the_page_is_used(self):
        page = b'<html><body><img itemprop="logo" src="/brand.png"></body></html>'
        data, _ = self.find({'/': page, '/brand.png': png(200)})
        self.assertEqual(Image.open(io.BytesIO(data)).size, (200, 200))
