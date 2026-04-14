"""
asyncpg connection pool singleton.

Used for:
    ai_users            — user auth (signup / login)
    ai_feedback         — employer score corrections
    ai_job_calibration  — per-JD aggregated calibration state

Run schema.sql against your PostgreSQL instance before starting the server.
"""
import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


async def init_postgres(dsn: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)


async def close_postgres() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError(
            "PostgreSQL pool not initialised. "
            "Set POSTGRES_DSN in your environment and restart the server."
        )
    return _pool
