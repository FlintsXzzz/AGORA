"""
app/database.py
---------------
Async SQLAlchemy engine and session factory backed by Supabase PostgreSQL.
Uses the asyncpg driver for non-blocking database access.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.settings import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# echo=False in production; set DATABASE_ECHO=true in .env for debugging.
_engine_kwargs: dict[str, object] = {
    "echo": False,
    "pool_pre_ping": True,  # discard stale connections
}
if not settings.DATABASE_URL.startswith("sqlite+aiosqlite://"):
    _engine_kwargs.update(
        {
            "pool_size": 10,
            "max_overflow": 20,
        }
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Declarative base (shared across all models)
# ---------------------------------------------------------------------------
Base = declarative_base()


# ---------------------------------------------------------------------------
# Dependency – FastAPI DI
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session; automatically closed after request."""
    async with async_session() as session:
        yield session
