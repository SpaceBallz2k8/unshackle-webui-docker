"""
services_manager.py — zip upload and git repo management for services.
Services live flat in /services/<service_name>/
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import aiosqlite

SERVICES_PATH = os.environ.get("SERVICES_PATH", "/services")
DB_PATH = os.environ.get("DATABASE_URL", "/data/unshackle.db")
REPOS_META_PATH = "/data/repos"


async def ensure_repos_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS service_repos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_name    TEXT NOT NULL UNIQUE,
                url          TEXT NOT NULL,
                branch       TEXT NOT NULL DEFAULT 'main',
                services     TEXT NOT NULL DEFAULT '[]',
                last_pulled  TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


def scan_services() -> list[dict]:
    base = Path(SERVICES_PATH)
    base.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in sorted(base.iterdir()):
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.is_dir() and list(entry.glob("*.py")):
            results.append({"name": entry.name, "type": "folder",
                             "files": [f.name for f in sorted(entry.glob("*.py"))]})
        elif entry.is_file() and entry.suffix == ".py":
            results.append({"name": entry.stem, "type": "file", "files": [entry.name]})
    return results


def install_from_zip(zip_bytes: bytes) -> list[str]:
    base = Path(SERVICES_PATH)
    installed = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "upload.zip"
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path) as zf:
            safe = [m for m in zf.infolist()
                    if not m.filename.startswith("/") and ".." not in m.filename]
            zf.extractall(tmp_path / "extracted", members=safe)
        extracted = tmp_path / "extracted"
        top = [p for p in extracted.iterdir() if not p.name.startswith("__")]
        if not top:
            raise ValueError("Zip is empty or has no valid entries")
        for entry in top:
            if entry.is_dir():
                dest = base / entry.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(entry, dest)
                installed.append(entry.name)
            elif entry.is_file() and entry.suffix == ".py":
                shutil.copy2(entry, base / entry.name)
                installed.append(entry.stem)
    return installed


async def _run_git(args: list, cwd: Optional[str] = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=cwd,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode().strip(), err.decode().strip()


def _repo_git_dir(repo_name: str) -> Path:
    return Path(REPOS_META_PATH) / repo_name


def _find_service_entries(path: Path) -> list[Path]:
    found = []
    for e in sorted(path.iterdir()):
        if e.name.startswith(".") or e.name.startswith("_"):
            continue
        if e.is_dir() and any(e.glob("*.py")):
            found.append(e)
        elif e.is_file() and e.suffix == ".py":
            found.append(e)
    return found


async def clone_repo(url: str, branch: str = "main") -> dict:
    base = Path(SERVICES_PATH)
    repo_name = url.rstrip("/").split("/")[-1].removesuffix(".git")

    existing = await _get_repo(repo_name)
    if existing:
        raise ValueError(f"Repo '{repo_name}' already installed. Use Pull to update.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / repo_name
        rc, _, err = await _run_git(["clone", "--depth", "1", "--branch", branch, url, str(tmp_path)])
        if rc != 0:
            rc, _, err = await _run_git(["clone", "--depth", "1", url, str(tmp_path)])
        if rc != 0:
            raise RuntimeError(f"git clone failed: {err}")

        service_dirs = _find_service_entries(tmp_path)
        if not service_dirs:
            raise ValueError("No service folders found in repo.")

        installed = []
        for entry in service_dirs:
            dest = base / entry.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(entry), str(dest))
            installed.append(entry.name)

        git_store = _repo_git_dir(repo_name)
        git_store.parent.mkdir(parents=True, exist_ok=True)
        if git_store.exists():
            shutil.rmtree(git_store)
        shutil.move(str(tmp_path / ".git"), str(git_store))

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO service_repos (repo_name, url, branch, services, last_pulled) "
            "VALUES (?, ?, ?, ?, datetime('now')) ON CONFLICT(repo_name) DO UPDATE SET "
            "url=excluded.url, branch=excluded.branch, services=excluded.services, last_pulled=datetime('now')",
            (repo_name, url, branch, json.dumps(installed)),
        )
        await db.commit()

    return {"repo_name": repo_name, "url": url, "branch": branch, "services": installed,
            "message": f"Installed {len(installed)} service(s): {', '.join(installed)}"}


async def pull_repo(repo_name: str) -> dict:
    repo = await _get_repo(repo_name)
    if not repo:
        raise ValueError(f"Repo '{repo_name}' not found")

    git_dir = _repo_git_dir(repo_name)
    services = json.loads(repo["services"])
    base = Path(SERVICES_PATH)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / repo_name
        rc, _, err = await _run_git(["clone", str(git_dir), str(tmp_path)])
        if rc != 0:
            raise RuntimeError(f"git clone failed: {err}")

        await _run_git(["--git-dir", str(git_dir), "fetch", "--depth", "1", "origin"])

        updated = []
        for svc_name in services:
            src = tmp_path / svc_name
            dest = base / svc_name
            if src.exists():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                updated.append(svc_name)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE service_repos SET last_pulled=datetime('now') WHERE repo_name=?",
            (repo_name,),
        )
        await db.commit()

    return {"repo_name": repo_name, "services": services,
            "output": f"Updated: {', '.join(updated)}" if updated else "Already up to date"}


async def delete_service_entry(name: str):
    base = Path(SERVICES_PATH)
    folder = base / name
    single = base / f"{name}.py"
    repo = await _get_repo_by_service(name)

    if folder.exists():
        shutil.rmtree(folder)
    elif single.exists():
        single.unlink()
    else:
        raise FileNotFoundError(f"Service '{name}' not found")

    if repo:
        repo_name = repo["repo_name"]
        for svc in json.loads(repo["services"]):
            p = base / svc
            if p.exists():
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        git_dir = _repo_git_dir(repo_name)
        if git_dir.exists():
            shutil.rmtree(git_dir)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM service_repos WHERE repo_name=?", (repo_name,))
            await db.commit()


async def list_repos() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM service_repos ORDER BY repo_name") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def _get_repo(repo_name: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM service_repos WHERE repo_name=?", (repo_name,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _get_repo_by_service(service_name: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM service_repos") as cur:
            for row in await cur.fetchall():
                if service_name in json.loads(row["services"]):
                    return dict(row)
    return None
