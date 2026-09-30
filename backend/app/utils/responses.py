"""Standard JSON error responses for domain errors."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.errors import AppError


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )
