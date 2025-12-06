#!/usr/bin/env python3
"""
Database initialization script.
Creates all tables and optionally seeds with test data.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set minimal environment variables if not present
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://localhost:5432/auphere-agent"

from src.database import close_db, get_engine, init_db
from src.utils.logger import get_logger

logger = get_logger("init_db")


async def main():
    """Initialize database."""
    try:
        logger.info("=== Auphere Agent - Database Initialization ===")

        # Initialize tables
        logger.info("Creating tables...")
        await init_db()
        logger.info("✅ Tables created successfully")

        # Verify tables exist
        engine = get_engine()
        async with engine.begin() as conn:
            from sqlalchemy import text

            result = await conn.execute(
                text(
                    """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """
                )
            )
            tables = [row[0] for row in result.fetchall()]

            logger.info(f"✅ Tables in database: {', '.join(tables)}")

            # Show table counts
            for table in tables:
                count_result = await conn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                )
                count = count_result.scalar()
                logger.info(f"   - {table}: {count} rows")

        # Close connection
        await close_db()

        logger.info("=== Database initialization complete! ===")

    except Exception as exc:
        logger.error(f"❌ Database initialization failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

