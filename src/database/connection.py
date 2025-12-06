"""Database connection management."""

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("database")

# Global engine instance
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[sessionmaker] = None


def get_engine(settings: Optional[Settings] = None) -> AsyncEngine:
    """
    Get or create database engine.

    Args:
        settings: Optional settings instance

    Returns:
        AsyncEngine instance
    """
    global _engine
    if _engine is None:
        settings = settings or get_settings()

        if not settings.database_url:
            raise ValueError("DATABASE_URL not configured")

        # Convert postgresql:// to postgresql+asyncpg://
        database_url = settings.database_url
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )

        _engine = create_async_engine(
            database_url,
            echo=settings.environment == "development",
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

        logger.info("database_engine_created", url=database_url.split("@")[-1])

    return _engine


def get_session_factory() -> sessionmaker:
    """
    Get or create session factory.

    Returns:
        Session factory
    """
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("session_factory_created")

    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI to get database session.

    Yields:
        AsyncSession instance

    Example:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database (create tables).
    Should be called on application startup.
    """
    from src.database.models import Base

    engine = get_engine()

    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

    logger.info("database_initialized")


async def close_db() -> None:
    """
    Close database connections.
    Should be called on application shutdown.
    """
    global _engine, _session_factory

    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("database_closed")

