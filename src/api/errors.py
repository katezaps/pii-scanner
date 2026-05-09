"""Centralized exception handlers for consistent error response shape.

Error responses follow the agreed shape:
    { "error": "<code>", "message": "<human-readable>" }

We never echo request body content into error messages — that's how PII leaks
back to the user via 400 responses.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _error_payload(code: str, message: str) -> dict[str, str]:
    return {"error": code, "message": message}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Pydantic validation errors include the original input in `exc.errors()`.
        # We must NOT echo raw input back — only field paths and error types.
        sanitized = [
            {
                "loc": [str(p) for p in err.get("loc", [])],
                "type": err.get("type", "value_error"),
                "msg": err.get("msg", "invalid"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                **_error_payload("validation_error", "Request validation failed"),
                "details": sanitized,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            429: "rate_limited",
            503: "service_unavailable",
        }.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Error"
        headers = exc.headers if exc.headers else None
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, message),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload("internal_error", "An unexpected error occurred"),
        )
