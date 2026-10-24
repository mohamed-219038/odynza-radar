"""Turns a finished HTML page (the weekly brief) into a PDF with the local Chromium from Playwright."""
import os


def render_pdf(html: str) -> bytes:
    """Blocking; call through asyncio.to_thread. A thread gets its own event loop, which also works on Windows."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # PDF_BROWSER_PATH (optional) points at an existing Chrome/Chromium instead of Playwright's own download.
        browser = p.chromium.launch(headless=True, executable_path=os.getenv('PDF_BROWSER_PATH', '').strip() or None)
        try:
            page = browser.new_page()
            # No network: the page is fully inline, so nothing is fetched while rendering.
            page.route('**/*', lambda route: route.abort())
            page.set_content(html, wait_until='load')
            return page.pdf(format='A4', print_background=True, prefer_css_page_size=True,
                            display_header_footer=True, header_template='<span></span>',
                            footer_template='<div style="font:8px Arial;color:#9aa398;width:100%;text-align:center">'
                                            '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        finally:
            browser.close()
