"""Opening a web page in Playwright's Chromium for the website collector."""
from __future__ import annotations

import os

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeout

TIMEOUT = int(os.getenv("PLAYWRIGHT_TIMEOUT", "30000"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
)


async def load_page(page, url: str, settle: int) -> str:
    """Slow sites often time out while still loading scripts or images after their text has arrived.
    Keep that text; with no text yet, try once more with twice the time."""
    try:
        await page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        html = await page.content()
        if len(BeautifulSoup(html, "lxml").get_text(" ", strip=True)) >= 200:
            return html
        await page.goto(url, timeout=TIMEOUT * 2, wait_until="commit")
        await page.wait_for_timeout(settle + 5000)
        return await page.content()
    await page.wait_for_timeout(settle)  # let JS settle
    return await page.content()
