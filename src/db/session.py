"""
Async SQLAlchemy session for NeonDB (PostgreSQL via asyncpg).

Uses a single shared async engine. All Layer 2 DB operations go through
async_session_factory. Sync get_db() is kept for FastAPI routes that
have not yet been ported to async.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.config import settings


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Async engine (Layer 2 + new async routes)
# ---------------------------------------------------------------------------

_async_connect_args: dict = {}
if "neon.tech" in settings.database_url or "postgresql+asyncpg" in settings.database_url:
    _async_connect_args = {
        "ssl": "require",
        "server_settings": {"channel_binding": "prefer"},
    }

async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=_async_connect_args,
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Sync engine (FastAPI dependency injection for existing sync routes)
# Strips asyncpg scheme back to psycopg2-compatible for sync use.
# ---------------------------------------------------------------------------

_sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
_sync_url = _sync_url.replace("sqlite+aiosqlite://", "sqlite://", 1)

sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def get_db():
    """FastAPI sync dependency — yields a DB session, used by existing routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
