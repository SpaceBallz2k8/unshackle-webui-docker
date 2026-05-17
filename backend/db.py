"""
db.py - WebUI SQLite database.
Only stores webui-specific data (tool versions, settings).
Download jobs are stored in unshackle's own job manager via the REST API.
"""
import os
import aiosqlite

DB_PATH = os.environ.get("DATABASE_URL", "/data/unshackle.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_versions (
                tool        TEXT PRIMARY KEY,
                version     TEXT,
                checked_at  TEXT DEFAULT (datetime('now'))
            );

            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('setup_complete', 'false'),
                ('theme', 'dark');
        """)
        await db.commit()
    from backend.services_manager import ensure_repos_table
    await ensure_repos_table()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row["value"] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT key, value FROM settings") as cur:
            return {r["key"]: r["value"] for r in await cur.fetchall()}
