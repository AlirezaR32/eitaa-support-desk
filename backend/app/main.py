"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import RateLimitMiddleware
from app.db.session import dispose_engine, get_engine
from app.services.errors import AppError

logger = get_logger("app.main")

DESCRIPTION = """
Eitaa Support Desk — multi-agent helpdesk on top of Eitaa messenger.

* REST API under `/api/v1` (this document)
* WebSocket realtime: `/api/v1/ws?token=<access-token>`
* Health: `/health` (liveness) and `/ready` (readiness incl. DB check)

All Eitaa access flows through a single adapter layer built on the
[`eitaa-cli`](https://github.com/EhsanAhmadzadeh/eitaa-cli) library. Because
that client has **no server-push stream**, message sync is polling-based
(`EITAA_SYNC_INTERVAL`, default 15s) while panel updates are pushed to
browsers over WebSocket the moment the backend persists a change.
"""


def create_app() -> FastAPI:
    configure_logging()
    Path(settings.uploads_path).mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ---------------- security headers ----------------
    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "microphone=(self), camera=(), geolocation=()"
        )
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        # hide server tech details
        if "server" in response.headers:
            del response.headers["server"]
        return response

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    # ---------------- domain errors -> JSON ----------------
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    # ---------------- routes ----------------
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    async def health() -> dict:
        return {"status": "ok", "env": settings.app_env}

    @app.get("/ready", tags=["meta"], summary="Readiness probe (DB + workers)")
    async def ready() -> JSONResponse:
        checks: dict[str, bool | str] = {}
        db_ok = False
        last_error = ""
        for attempt in range(3):  # first pool connect can occasionally be slow
            try:
                async with get_engine().connect() as conn:
                    await conn.execute(text("SELECT 1"))
                db_ok = True
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)[:120]
                await asyncio.sleep(0.3)
        checks["database"] = True if db_ok else f"fail: {last_error}"
        from app.workers.sync_worker import sync_worker

        checks["sync_worker_configured"] = settings.run_sync_worker
        checks["accounts_syncing_now"] = len(sync_worker.in_progress)
        healthy = checks["database"] is True
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ready" if healthy else "degraded", "checks": checks},
        )

    # ---------------- lifecycle ----------------
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        problems = settings.validate_production_secrets()
        for problem in problems:
            logger.error("CONFIG: %s", problem)
        if settings.is_production and problems:
            raise RuntimeError("Refusing to start: production secrets missing/weak")
        if settings.eitaa_sync_enabled and settings.run_sync_worker:
            from app.workers.sync_worker import sync_worker

            await sync_worker.start()
            logger.info("sync worker: enabled")
        scheduler = None
        try:
            from app.workers.scheduler import build_scheduler

            scheduler = build_scheduler()
            scheduler.start()
        except Exception:  # noqa: BLE001 — scheduler is best-effort at boot
            logger.exception("scheduler failed to start")
        from app.core.security import session_vault

        if session_vault.using_derived_key:
            logger.warning(
                "EITAA_SESSION_ENCRYPTION_KEY not set — using a key derived from "
                "SECRET_KEY. This is fine for development; set a dedicated Fernet "
                "key in production."
            )
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        from app.workers.sync_worker import sync_worker

        await sync_worker.stop()
        await dispose_engine()

    app.router.lifespan_context = lifespan
    return app


app = create_app()
