"""
Table creation script for Lily's NeonDB schema.

Run once to create all tables:
    conda run -n lily python -m src.db.init_db

Safe to run on an existing DB (uses CREATE TABLE IF NOT EXISTS via SQLAlchemy).
"""

from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger(__name__)


async def create_tables() -> None:
    # Import all models so SQLAlchemy registers them on Base.metadata
    import src.db.models.patient      # noqa: F401
    import src.db.models.encounters   # noqa: F401
    import src.db.models.vitals       # noqa: F401

    from src.db.session import Base, async_engine

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info("db_tables_created", tables=list(Base.metadata.tables.keys()))
    print("Tables created:", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    asyncio.run(create_tables())
