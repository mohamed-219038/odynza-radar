"""Odynza Radar: competitor intelligence (M0), strategy (M1) and social content (M2) in one web app.

    .venv\\Scripts\\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000

The collection scheduler runs inside this server, and the n8n workflows post their results back to it.
"""
import os
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.watch import pictures
from fastapi import Depends

from api.routers import auth, content, discovery, radar_plans, strategy, watch
from api.watch import scheduler
from api.security import SecurityMiddleware, allowed_hosts, require_user
from db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    logger.info("Odynza Radar ready.")
    # Pictures collected before they were saved locally: keep them now, before their platform links expire.
    saving = asyncio.create_task(pictures.backfill()) if os.getenv("WATCH_SAVE_PICTURES", "1") != "0" else None
    yield
    if saving is not None and not saving.done():
        saving.cancel()
    await scheduler.stop()


app = FastAPI(title="Odynza Radar", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "frontend" / "dist"      # React build output (cd frontend, npm run build)
SITE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=SITE_DIR), name="static")

app.include_router(auth.router, prefix="/auth", tags=["Accounts"])
app.include_router(watch.n8n, prefix="/watch/n8n", tags=["Watch · n8n"])
app.include_router(watch.router, prefix="/watch", tags=["Watch"])
# M1 Strategy and M2 Social content. Each endpoint checks sign-in itself: n8n posts results
# back to the address the plan or batch was started from, without a browser session.
app.include_router(radar_plans.router, prefix="/strategy", tags=["M1 Strategy"])
app.include_router(strategy.router, prefix="/strategy", tags=["M1 Strategy"])
app.include_router(content.router, prefix="/content", tags=["M2 Social content"])
# Company search ("Search by name" on Profile, "Find competitors").
app.include_router(discovery.router, prefix="/discover", tags=["Company search"], dependencies=[Depends(require_user)])


@app.exception_handler(StarletteHTTPException)
async def http_errors(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401 and request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/?next=" + quote(request.url.path, safe="/"), status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def unexpected_errors(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse({"detail": "Something went wrong on the server. Try again; details are in the server log."},
                        status_code=500)


def site_page():
    index = SITE_DIR / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "The site is not built yet: run npm install and npm run build in frontend/."}, 503)
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "site": "odynza-radar"}


@app.get("/", include_in_schema=False)
async def root():
    return site_page()


@app.get("/{section}", include_in_schema=False)
async def section(section: str):
    """Deep links like /brief or /ads open the same page on that section."""
    if section in {"overview", "competitors", "collect", "ads", "compare", "brief", "opportunities", "data", "profile",
                   "strategy", "content", "team", "reset"}:
        return site_page()
    raise StarletteHTTPException(404, "Not found")

