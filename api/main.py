"""FastAPI entrypoint with lifecycle management."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chat_routes import router as chat_router
from api.routes import router
from api.streaming_routes import router as streaming_router
from src.config.settings import get_settings
from src.database import close_db, init_db
from src.utils.cache_manager import get_cache_manager
from src.utils.logger import get_logger

settings = get_settings()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("🚀 Starting Auphere Agent", version=settings.version)

    try:
        # Initialize database
        if settings.database_url:
            logger.info("Initializing database...")
            await init_db()
            logger.info("✅ Database initialized")
        else:
            logger.warning("⚠️ DATABASE_URL not set, skipping database initialization")

        # Initialize cache
        if settings.redis_enabled:
            logger.info("Connecting to Redis cache...")
            cache = await get_cache_manager()
            logger.info("✅ Redis cache connected")
        else:
            logger.info("⚠️ Redis caching disabled")

        logger.info("✅ Auphere Agent ready!")

    except Exception as exc:
        logger.error(f"❌ Startup failed: {exc}")
        raise

    yield

    # Shutdown
    logger.info("🛑 Shutting down Auphere Agent")

    try:
        # Close database
        await close_db()
        logger.info("✅ Database connections closed")

        # Close cache
        cache = await get_cache_manager()
        await cache.disconnect()
        logger.info("✅ Redis cache disconnected")

    except Exception as exc:
        logger.error(f"❌ Shutdown error: {exc}")

    logger.info("👋 Auphere Agent stopped")


app = FastAPI(
    title="Auphere Agent API",
    description="Isolated AI Agent microservice with full persistence and caching",
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_credentials=True,
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(chat_router)
app.include_router(streaming_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "service": settings.service_name,
        "version": settings.version,
        "status": "ok",
    }

