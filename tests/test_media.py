import asyncio
import socket
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from api.media import fetch_image, public_target

PNG = b'\x89PNG\r\n\x1a\n' + b'fixture'


class ImageNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_private_dns_and_credentials(self):
        loop=asyncio.get_running_loop()
        for address in ['127.0.0.1','169.254.169.254','10.0.0.1','::1']:
            with patch.object(loop,'getaddrinfo',new=AsyncMock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))])):
                with self.assertRaises(HTTPException):await public_target('https://cdn.example.com/image.png')
        for url in ['file:///etc/passwd','https://user:key@example.com/a','https://example.com:8000/a']:
            with self.assertRaises(HTTPException):await public_target(url)

    async def test_dns_is_pinned_for_connection(self):
        with patch.object(asyncio.get_running_loop(),'getaddrinfo',new=AsyncMock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))])):
            target,host=await public_target('https://cdn.example.com/image.png?signature=fixture')
            self.assertEqual(target.host,'8.8.8.8')
            self.assertEqual(host,'cdn.example.com')
            self.assertEqual(target.query,b'signature=fixture')

    async def run_fetch(self,handler,limit=None):
        real_client=httpx.AsyncClient
        def client(**kwargs):return real_client(transport=httpx.MockTransport(handler),**kwargs)
        async def target(url):return httpx.URL(url).copy_with(host='8.8.8.8'),'cdn.example.com'
        with patch('api.media.httpx.AsyncClient',side_effect=client),patch('api.media.public_target',side_effect=target),patch('api.media.MAX_IMAGE_BYTES',limit or 12000000):
            return await fetch_image('https://cdn.example.com/a')

    async def test_valid_image_uses_host_and_tls_name(self):
        def handler(request):
            self.assertEqual(request.url.host,'8.8.8.8')
            self.assertEqual(request.headers['host'],'cdn.example.com')
            self.assertEqual(request.extensions['sni_hostname'],'cdn.example.com')
            self.assertNotIn('authorization',request.headers)
            return httpx.Response(200,content=PNG)
        self.assertEqual(await self.run_fetch(handler),(PNG,'image/png','png'))

    async def test_html_expired_oversize_and_redirect_loop_fail(self):
        cases=[(lambda r:httpx.Response(200,content=b'<html>not an image</html>'),None,415),
               (lambda r:httpx.Response(403),None,502),
               (lambda r:httpx.Response(200,content=PNG*10),20,413),
               (lambda r:httpx.Response(302,headers={'location':'/next'}),None,502)]
        for handler,limit,status in cases:
            with self.assertRaises(HTTPException) as caught:await self.run_fetch(handler,limit)
            self.assertEqual(caught.exception.status_code,status)


if __name__=='__main__':unittest.main()
