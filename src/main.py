"""FastAPI application entrypoint.

The lifespan context manager handles startup and shutdown of the connection
pool. Routers are mounted per-resource, with consistent error shapes and
no-cache headers on authenticated endpoints.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api import audit, brokers, errors, fetch, meta
from src.core.config import get_settings
from src.core.logging import configure_logging
from src.db.pool import close_pool, open_pool
from src.services.browser import shutdown_browser


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    logger = logging.getLogger(__name__)

    logger.info(
        "Starting pii-scanner env=%s host=%s port=%s",
        settings.env,
        settings.api_host,
        settings.api_port,
    )

    # Bridge Pydantic .env loading with the OpenAI SDK's direct os.environ lookup.
    # Done once at startup so it's not buried in business logic.
    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key.get_secret_value())

    await open_pool(settings)
    try:
        yield
    finally:
        logger.info("Shutting down")
        await close_pool()
        await shutdown_browser()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="pii-scanner",
        version="0.1.0",
        description="Open-source data broker auditor",
        lifespan=lifespan,
        # Disable docs in production; OpenAPI schema can leak endpoint detail
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # CORS for the React dev server (separate port). In production the
    # frontend is served from the same origin so CORS is not needed.
    if not settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    errors.register_exception_handlers(app)

    app.include_router(meta.router)
    app.include_router(brokers.router)
    app.include_router(audit.router)
    app.include_router(fetch.router)

    # Serve the built React frontend in production. The Dockerfile copies
    # the Vite build output to /app/static. In dev, Vite serves on :5173.
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
