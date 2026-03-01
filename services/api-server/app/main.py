"""API server entrypoint."""

import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.admin_docs import router as admin_docs_router
from app.api.admin_eval import router as admin_eval_router
from app.api.admin_jobs import router as admin_jobs_router
from app.api.admin_connectivity import router as admin_connectivity_router
from app.api.chat import router as chat_router
from app.api.search import router as search_router
from app.api.upload import router as upload_router
from app.services.secrets_guard import validate_runtime_secrets

try:
    from shared.logging_config import configure_logging, get_logger
    configure_logging()
    _log = get_logger("api-server")
except ImportError:
    import logging
    _log = logging.getLogger("api-server")  # type: ignore[assignment]

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="ExpertDatebase API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

validate_runtime_secrets()

cors_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
cors_origins = [item.strip() for item in cors_origins_raw.split(",") if item.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(upload_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(admin_eval_router)
app.include_router(admin_jobs_router)
app.include_router(admin_docs_router)
app.include_router(admin_connectivity_router)


async def _check_postgres() -> tuple[bool, str]:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        return False, "DATABASE_URL not set"
    try:
        import asyncpg  # type: ignore[import]
        conn = await asyncio.wait_for(asyncpg.connect(database_url), timeout=3.0)
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True, "ok"
    except ImportError:
        # Fallback: psycopg2 synchronous probe
        try:
            import psycopg2  # type: ignore[import]
            conn = psycopg2.connect(database_url, connect_timeout=3)
            conn.close()
            return True, "ok"
        except Exception as exc:
            return False, str(exc)
    except Exception as exc:
        return False, str(exc)


async def _check_redis() -> tuple[bool, str]:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        r = aioredis.from_url(redis_url, socket_connect_timeout=3)
        await asyncio.wait_for(r.ping(), timeout=3.0)
        await r.aclose()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


async def _check_qdrant() -> tuple[bool, str]:
    endpoint = os.getenv("VECTORDB_ENDPOINT", "")
    if not endpoint:
        return False, "VECTORDB_ENDPOINT not set"
    try:
        import http.client
        import urllib.parse
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6333
        loop = asyncio.get_event_loop()

        def _probe() -> None:
            conn = http.client.HTTPConnection(host, port, timeout=3)
            conn.request("GET", "/readyz")
            resp = conn.getresponse()
            conn.close()
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}")

        await asyncio.wait_for(loop.run_in_executor(None, _probe), timeout=4.0)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


@app.get("/health")
async def health() -> JSONResponse:
    pg_ok, pg_msg = await _check_postgres()
    redis_ok, redis_msg = await _check_redis()
    qdrant_ok, qdrant_msg = await _check_qdrant()

    deps = {
        "postgres": {"ok": pg_ok, "detail": pg_msg},
        "redis": {"ok": redis_ok, "detail": redis_msg},
        "qdrant": {"ok": qdrant_ok, "detail": qdrant_msg},
    }
    all_ok = pg_ok and redis_ok and qdrant_ok
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "deps": deps},
        status_code=status_code,
    )
