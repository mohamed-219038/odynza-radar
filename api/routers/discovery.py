"""Company search: finds a company's official website and social pages, or its likely competitors."""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from api.gemini import GeminiError
from api.discovery import DiscoveryRequest, discover
from api.security import env_int, rate_limit

router = APIRouter()
searches = Depends(rate_limit('discover', env_int('LIMIT_SEARCHES_PER_10_MIN', 20), 600))


@router.post("", dependencies=[searches])
async def discover_companies(request: DiscoveryRequest):
    try:
        return await discover(request)
    except GeminiError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/stream", dependencies=[searches])
async def discover_companies_stream(request: DiscoveryRequest):
    """The same search, streamed as JSON lines: stage messages, verified companies so far, then the result."""
    queue = asyncio.Queue()

    async def run():
        try:
            result = await discover(request, emit=queue.put)
            await queue.put({'type': 'result', 'data': result})
        except GeminiError as exc:
            await queue.put({'type': 'error', 'detail': str(exc)})
        except Exception:
            logging.getLogger('uvicorn.error').exception('Company search failed')
            await queue.put({'type': 'error', 'detail': 'Company search failed unexpectedly. Check the server log.'})
        finally:
            await queue.put(None)

    # The search keeps running if the browser disconnects, so its result is still cached for the next request.
    worker = asyncio.create_task(run())

    async def lines():
        while (event := await queue.get()) is not None:
            yield json.dumps(jsonable_encoder(event), ensure_ascii=False) + '\n'
        await worker

    return StreamingResponse(lines(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store'})
