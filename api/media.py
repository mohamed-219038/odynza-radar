"""Retrieve stored image URLs only; pin public DNS addresses and limit response size."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urljoin

import httpx
from fastapi import HTTPException

MAX_IMAGE_BYTES = 12 * 1024 * 1024


async def public_target(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port != (443 if parsed.scheme == "https" else 80):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii")
        addresses = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), 8)
        ips = [ipaddress.ip_address(a[4][0]) for a in addresses]
        if not ips or any(not ip.is_global or ip.is_multicast or ip.is_reserved for ip in ips):
            raise ValueError()
        address = next((str(ip) for ip in ips if ip.version == 4), str(ips[0]))
        # Connect to the validated IP, while keeping TLS verification on the original name.
        return httpx.URL(url).copy_with(host=address), host
    except (ValueError, UnicodeError, socket.gaierror, asyncio.TimeoutError):
        raise HTTPException(400, "This image address cannot be accessed safely.") from None


def image_type(data, icons=False):
    if icons and data[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon", "ico"
    if icons and b"<svg" in data[:2048].lower():
        return "image/svg+xml", "svg"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif", "avif"
    raise HTTPException(415, "The source did not return a supported image.")


async def fetch_image(url):
    """The saved copy of a scraped picture, or the picture downloaded now and saved for next time."""
    from api.watch import pictures
    content = pictures.saved(url)
    if content is None:
        content, _ = await fetch_public(url)
        image_type(content)   # refuse anything that is not a picture before keeping it
        pictures.keep(url, content)
    mime, extension = image_type(content)
    return content, mime, extension


async def fetch_public(url, accept="image/*", limit=None, total=35):
    """GET a public URL (no private addresses, no credentials); returns (bytes, final URL)."""
    limit = limit or MAX_IMAGE_BYTES
    try:
        # No API credentials, cookies, proxy environment, or caller headers are forwarded.
        async with asyncio.timeout(total), httpx.AsyncClient(timeout=12, trust_env=False) as client:
            for _ in range(4):
                target, host = await public_target(url)
                async with client.stream("GET", target, headers={"Host": host, "Accept": accept, "User-Agent": "Mozilla/5.0 (compatible; OdynzaRadar-Image-Viewer/1.0)"}, extensions={"sni_hostname": host}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            break
                        url = urljoin(url, location)
                        continue
                    if response.status_code != 200:
                        raise HTTPException(502, "Image unavailable. Its source link may have expired; open the original post or scrape again.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > limit:
                            raise HTTPException(413, "Image is larger than the 12 MB download limit.")
                    return bytes(data), url
    except (httpx.HTTPError, asyncio.TimeoutError):
        raise HTTPException(502, "Image could not be loaded. The source may be unavailable or the image link expired.") from None
    raise HTTPException(502, "Image source redirected too many times.")
