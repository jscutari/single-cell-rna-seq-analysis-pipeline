"""Postgres connection and schema (asyncpg).

The database runs in Docker on the Brev box (docker-compose.yml). Startup waits
for it while the container boots, then fails with a clear message instead of
running without persistence.
"""

import asyncio
import json
import logging
import time
from pathlib import Path

import asyncpg

log = logging.getLogger("scrap.backend.db")

SCHEMA = Path(__file__).with_name("schema.sql")


class DatabaseUnavailable(RuntimeError):
    """The database could not be reached at startup."""


async def _init_connection(conn: asyncpg.Connection) -> None:
    # jsonb columns in and out as Python objects.
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect(url: str | None, timeout: float = 30.0, retry_every: float = 0.5) -> asyncpg.Pool:
    """A connection pool, retrying until `timeout` (e.g. while the container starts)."""
    if not url:
        raise DatabaseUnavailable(
            "DATABASE_URL is not set. Copy .env.example to .env and start Postgres with "
            "`docker compose up -d db`, or set SCRAP_STORE=memory to run without persistence."
        )
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            return await asyncpg.create_pool(url, min_size=1, max_size=5, init=_init_connection)
        except (OSError, asyncpg.PostgresError, asyncio.TimeoutError) as error:
            last_error = error
        if time.monotonic() >= deadline:
            raise DatabaseUnavailable(
                f"Could not connect to Postgres at {_redact(url)} within {timeout:.0f}s ({last_error}). "
                "Is it running? `docker compose up -d db`"
            ) from last_error
        await asyncio.sleep(retry_every)


async def apply_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA.read_text())


def _redact(url: str) -> str:
    """The URL without its password, for error messages."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
