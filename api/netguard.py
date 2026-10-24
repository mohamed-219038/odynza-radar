"""Keep the browser scraper on the public internet: no localhost, LAN, cloud metadata or other private addresses.

Users type the websites Radar opens, so on a shared server this stops anyone using the scraper
to read pages on the server itself or on the office network (server-side request forgery).
"""
import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit

_cache: dict[str, bool] = {}


def allow_private() -> bool:
    return os.getenv("SCRAPE_ALLOW_PRIVATE_NETWORK", "").strip().lower() in {"1", "true", "yes"}


async def host_is_public(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    if host in _cache:
        return _cache[host]
    try:
        ascii_host = host.encode("idna").decode("ascii")
        infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(ascii_host, None, type=socket.SOCK_STREAM), 8)
        ips = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
        ok = bool(ips) and all(ip.is_global and not ip.is_multicast and not ip.is_reserved for ip in ips)
    except (OSError, UnicodeError, ValueError, asyncio.TimeoutError):
        ok = False
    if len(_cache) > 5000:
        _cache.clear()
    _cache[host] = ok
    return ok


async def url_is_public(url: str) -> bool:
    if allow_private():
        return True
    parts = urlsplit(url)
    if parts.scheme in ("data", "blob", "about"):
        return True
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return False
    return await host_is_public(parts.hostname or "")


async def guard_context(context):
    """Abort every browser request (page, redirect, script, image, fetch) whose host is not public."""
    if allow_private():
        return

    async def check(route):
        if await url_is_public(route.request.url):
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    await context.route("**/*", check)
