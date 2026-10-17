"""backend/db.py and settings: connecting, schema, clear failures, .env handling."""

import asyncio

import asyncpg
import pytest

from backend.config import Settings, read_env_file
from backend.db import DatabaseUnavailable, _redact, apply_schema, connect

pytestmark = pytest.mark.db


async def tables(url: str) -> set[str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}
    finally:
        await conn.close()


async def test_schema_applies_and_is_idempotent(pg_url):
    pool = await connect(pg_url, timeout=5)
    try:
        await apply_schema(pool)
        await apply_schema(pool)  # second start: no errors, no duplicates
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM schema_version") == 1
            await conn.execute(
                "INSERT INTO events VALUES (1, 'p', 'stage_done', $1, now())", {"stage": "intake", "summary": ""}
            )
            payload = await conn.fetchval("SELECT payload FROM events WHERE id = 1")
            assert payload == {"stage": "intake", "summary": ""}  # jsonb round-trips as a dict
    finally:
        await pool.close()
    assert {"events", "projects", "llm_calls", "schema_version"} <= await tables(pg_url)


async def test_connect_without_url_explains_what_to_do():
    with pytest.raises(DatabaseUnavailable, match="docker compose up -d db"):
        await connect(None)


async def test_connect_gives_up_with_a_clear_error_after_the_timeout():
    start = asyncio.get_running_loop().time()
    with pytest.raises(DatabaseUnavailable, match=r"Could not connect to Postgres at postgresql://u:\*\*\*@127.0.0.1:1/x"):
        await connect("postgresql://u:secret@127.0.0.1:1/x", timeout=0.6, retry_every=0.2)
    assert asyncio.get_running_loop().time() - start >= 0.5


@pytest.mark.parametrize(
    ("url", "redacted"),
    [("postgresql://u:pw@h:5432/db", "postgresql://u:***@h:5432/db"), ("postgresql://h/db", "postgresql://h/db")],
)
def test_redact(url, redacted):
    assert _redact(url) == redacted


def test_env_file_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\n\nDATABASE_URL="postgresql://a:b@h/d"\nSCRAP_STORE=memory\nnot a pair\n')
    assert read_env_file(env) == {"DATABASE_URL": "postgresql://a:b@h/d", "SCRAP_STORE": "memory"}
    assert read_env_file(tmp_path / "missing") == {}


def test_settings_read_env_file_and_environment_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://file/db\nSCRAP_STORE=memory\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SCRAP_STORE", raising=False)
    s = Settings.from_env(env)
    assert (s.database_url, s.store) == ("postgresql://file/db", "memory")
    monkeypatch.setenv("SCRAP_STORE", "postgres")
    assert Settings.from_env(env).store == "postgres"


def test_store_defaults(monkeypatch, tmp_path):
    for var in ("SCRAP_STORE", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert Settings.from_env(tmp_path / "none").store == "postgres"  # on the box: persistence by default
    assert Settings().store == "memory"  # constructed directly (tests)
