"""
main.py - Unshackle WebUI FastAPI application.

Architecture:
  - This webui is completely separate from unshackle
  - All download/search/jobs go through the unshackle REST API (port 8786)
  - This server handles: UI, auth, config management, service files, WVDs, cookies
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Optional

import os
import aiosqlite

DB_PATH = os.environ.get("DATABASE_URL", "/data/unshackle.db")
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from pydantic import BaseModel

from backend import config_manager as cfg_mgr
from backend import services_manager as svc_mgr
from backend import unshackle_api as api
from backend.auth import login, logout, require_auth
from backend.db import get_all_settings, get_setting, init_db, set_setting

app = FastAPI(title="Unshackle WebUI", version="2.0.0")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
async def startup():
    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS hidden_jobs (job_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS job_labels (
                job_id     TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                service    TEXT,
                episode_id TEXT
            );
        """)
        await db.commit()


# ── SPA ───────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(session: Optional[str] = Cookie(None)):
    return (FRONTEND_DIR / "index.html").read_text()


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def do_login(req: LoginRequest):
    token = login(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    resp = JSONResponse({"ok": True})
    resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.post("/api/auth/logout")
async def do_logout(session: Optional[str] = Cookie(None)):
    if session:
        logout(session)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


@app.get("/api/auth/me")
async def me(session: Optional[str] = Cookie(None)):
    try:
        require_auth(session)
        return {"authenticated": True, "username": os.environ.get("WEBUI_USERNAME", "admin")}
    except HTTPException:
        return {"authenticated": False}


# ── Unshackle API proxy ────────────────────────────────────────────────────────
# These endpoints proxy to the unshackle REST API so the frontend only
# talks to one server.

@app.get("/api/unshackle/health", dependencies=[Depends(require_auth)])
async def unshackle_health():
    try:
        return await api.health()
    except Exception as e:
        raise HTTPException(503, f"Unshackle API unavailable: {e}")


@app.get("/api/unshackle/services", dependencies=[Depends(require_auth)])
async def unshackle_services():
    try:
        services = await api.list_services()
        return {"services": services}
    except Exception as e:
        raise HTTPException(503, str(e))


class SearchRequest(BaseModel):
    service: str
    query: str
    profile: Optional[str] = None
    proxy: Optional[str] = None


@app.post("/api/unshackle/search", dependencies=[Depends(require_auth)])
async def unshackle_search(req: SearchRequest):
    try:
        return await api.search(req.service, req.query, req.profile, req.proxy)
    except Exception as e:
        raise HTTPException(500, str(e))


class ListTitlesRequest(BaseModel):
    service: str
    title_id: str
    profile: Optional[str] = None


@app.post("/api/unshackle/list-titles", dependencies=[Depends(require_auth)])
async def unshackle_list_titles(req: ListTitlesRequest):
    try:
        return await api.list_titles(req.service, req.title_id, req.profile)
    except Exception as e:
        raise HTTPException(500, str(e))


class DownloadRequest(BaseModel):
    service: str
    title_id: str
    title_label: Optional[str] = None
    episode_id: Optional[str] = None
    # Episode selection
    wanted: Optional[list[str]] = None
    latest_episode: bool = False
    # Quality / codec
    quality: Optional[list[int]] = None
    worst: bool = False
    best_available: bool = False
    vcodec: Optional[list[str]] = None
    acodec: Optional[list[str]] = None
    vbitrate: Optional[int] = None
    abitrate: Optional[int] = None
    channels: Optional[float] = None
    no_atmos: bool = False
    range: Optional[list[str]] = None
    # Language
    lang: Optional[list[str]] = None
    v_lang: Optional[list[str]] = None
    a_lang: Optional[list[str]] = None
    s_lang: Optional[list[str]] = None
    require_subs: Optional[list[str]] = None
    forced_subs: bool = False
    exact_lang: bool = False
    # Track selection flags
    video_only: bool = False
    audio_only: bool = False
    subs_only: bool = False
    chapters_only: bool = False
    no_subs: bool = False
    no_audio: bool = False
    no_video: bool = False
    no_chapters: bool = False
    audio_description: bool = False
    split_audio: bool = False
    # Muxing / output
    no_mux: bool = False
    sub_format: Optional[str] = None
    no_folder: bool = False
    no_source: bool = False
    repack: bool = False
    tag: Optional[str] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    animeapi_id: Optional[str] = None
    enrich: bool = False
    output_dir: Optional[str] = None
    # Proxy / network
    profile: Optional[str] = None
    proxy: Optional[str] = None
    no_proxy: bool = False
    no_proxy_download: bool = False
    slow: Optional[Any] = None
    # CDM / vault
    cdm_only: Optional[bool] = None
    skip_dl: bool = False
    export: bool = False
    no_cache: bool = False
    reset_cache: bool = False
    # Concurrency
    downloads: int = 4
    workers: int = 16


@app.post("/api/unshackle/download", dependencies=[Depends(require_auth)])
async def unshackle_download(req: DownloadRequest):
    # Build payload: exclude UI-only meta fields, skip None values,
    # skip False booleans (API defaults handle them server-side)
    exclude_keys = {"title_label", "episode_id"}
    payload = {}
    for k, v in req.dict().items():
        if k in exclude_keys:
            continue
        if v is None:
            continue
        if isinstance(v, bool) and not v:
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        payload[k] = v
    try:
        result = await api.start_download(payload)
        if req.title_label and result.get("job_id"):
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO job_labels (job_id, title, service, episode_id) VALUES (?,?,?,?)",
                    (result["job_id"], req.title_label, req.service, req.episode_id),
                )
                await db.commit()
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/unshackle/jobs", dependencies=[Depends(require_auth)])
async def unshackle_jobs(
    status: Optional[str] = None,
    service: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
):
    try:
        jobs = await api.list_jobs(status, service, sort_by, sort_order)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT job_id FROM hidden_jobs") as cur:
                hidden = {str(r[0]) for r in await cur.fetchall()}
            async with db.execute("SELECT job_id, title, episode_id FROM job_labels") as cur:
                labels = {str(r["job_id"]): {"title": r["title"], "episode_id": r["episode_id"]}
                          for r in await cur.fetchall()}
        visible = [j for j in jobs if str(j.get("job_id")) not in hidden]
        for j in visible:
            lbl = labels.get(str(j.get("job_id")))
            if lbl:
                j["title_label"] = lbl["title"]
                j["episode_id"] = lbl["episode_id"]
        return {"jobs": visible}
    except Exception as e:
        raise HTTPException(503, str(e))


@app.get("/api/unshackle/jobs/{job_id}", dependencies=[Depends(require_auth)])
async def unshackle_job(job_id: str):
    try:
        return await api.get_job(job_id)
    except Exception as e:
        raise HTTPException(404, str(e))


@app.delete("/api/unshackle/jobs/{job_id}", dependencies=[Depends(require_auth)])
async def unshackle_cancel_job(job_id: str):
    try:
        # Mark as hidden locally so it disappears from the UI immediately
        async with aiosqlite.connect(os.environ.get("DATABASE_URL", "/data/unshackle.db")) as db:
            await db.execute("INSERT OR IGNORE INTO hidden_jobs (job_id) VALUES (?)", (job_id,))
            await db.commit()
        
        # Attempt to cancel in the engine (it might fail if already finished, so we catch)
        try:
            await api.cancel_job(job_id)
        except Exception:
            pass
            
        return {"ok": True, "job_id": job_id}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Job polling SSE stream ────────────────────────────────────────────────────
# Since unshackle's API uses polling (not SSE), we wrap it here

import asyncio
from fastapi.responses import StreamingResponse


@app.get("/api/jobs/{job_id}/stream", dependencies=[Depends(require_auth)])
async def stream_job(job_id: str):
    """SSE endpoint that polls unshackle API and streams status updates."""

    async def generate():
        last_status = None
        last_progress = -1
        while True:
            try:
                job = await api.get_job(job_id)
                status = job.get("status", "unknown")
                progress = job.get("progress", 0)

                if status != last_status or progress != last_progress:
                    yield f"data: {json.dumps(job)}\n\n"
                    last_status = status
                    last_progress = progress

                if status in ("completed", "failed", "cancelled"):
                    break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config/raw", dependencies=[Depends(require_auth)])
async def get_config_raw():
    return {"content": cfg_mgr.get_raw()}


@app.post("/api/config/raw", dependencies=[Depends(require_auth)])
async def save_config_raw(payload: dict):
    cfg_mgr.save_raw(payload.get("content", ""))
    return {"saved": True}


@app.get("/api/config/section/{key}", dependencies=[Depends(require_auth)])
async def get_section(key: str):
    return {"key": key, "value": cfg_mgr.get_section(key)}


@app.post("/api/config/section/{key}", dependencies=[Depends(require_auth)])
async def set_section(key: str, payload: dict):
    cfg_mgr.set_section(key, payload.get("value"))
    return {"saved": True}


# ── Credentials ───────────────────────────────────────────────────────────────

@app.get("/api/credentials", dependencies=[Depends(require_auth)])
async def list_credentials():
    raw = cfg_mgr.get_credentials()
    result = []
    for service, val in raw.items():
        if isinstance(val, str):
            result.append({"service": service, "profile": None, "value": val})
        elif isinstance(val, dict):
            for profile, pval in val.items():
                result.append({"service": service, "profile": profile, "value": pval})
    return {"credentials": result}


class CredentialRequest(BaseModel):
    service: str
    username: str
    password: str
    profile: Optional[str] = None


@app.post("/api/credentials", dependencies=[Depends(require_auth)])
async def add_credential(req: CredentialRequest):
    cfg_mgr.set_credential(req.service, req.profile, req.username, req.password)
    return {"saved": True}


class DeleteCredentialRequest(BaseModel):
    service: str
    profile: Optional[str] = None


@app.delete("/api/credentials", dependencies=[Depends(require_auth)])
async def delete_credential(req: DeleteCredentialRequest):
    cfg_mgr.delete_credential(req.service, req.profile)
    return {"deleted": True}


# ── Cookies ───────────────────────────────────────────────────────────────────

@app.get("/api/cookies", dependencies=[Depends(require_auth)])
async def list_cookies():
    return {"cookies": cfg_mgr.list_cookies()}


@app.post("/api/cookies/upload", dependencies=[Depends(require_auth)])
async def upload_cookie(service: str, file: UploadFile = File(...)):
    data = await file.read()
    ext = Path(file.filename).suffix.lstrip(".") or "txt"
    cfg_mgr.save_cookie(service.upper(), data, ext)
    return {"saved": f"{service.upper()}.{ext}"}


@app.delete("/api/cookies/{filename}", dependencies=[Depends(require_auth)])
async def delete_cookie(filename: str):
    cfg_mgr.delete_cookie(filename)
    return {"deleted": filename}


# ── WVDs ──────────────────────────────────────────────────────────────────────

@app.get("/api/wvds", dependencies=[Depends(require_auth)])
async def list_wvds():
    wvds = cfg_mgr.list_wvds()
    current = cfg_mgr.get_cdm().get("default", "")
    for w in wvds:
        w["active"] = w["stem"] == current
    return {"wvds": wvds}


@app.post("/api/wvds/upload", dependencies=[Depends(require_auth)])
async def upload_wvd(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".wvd"):
        raise HTTPException(400, "Only .wvd files accepted")
    cfg_mgr.save_wvd(file.filename, await file.read())
    return {"filename": file.filename}


@app.post("/api/wvds/{stem}/activate", dependencies=[Depends(require_auth)])
async def activate_wvd(stem: str):
    cfg_mgr.set_default_cdm(stem)
    return {"default": stem}


@app.delete("/api/wvds/{filename}", dependencies=[Depends(require_auth)])
async def delete_wvd(filename: str):
    cfg_mgr.delete_wvd(filename)
    return {"deleted": filename}


# ── Services ──────────────────────────────────────────────────────────────────

@app.get("/api/services", dependencies=[Depends(require_auth)])
async def list_services():
    services = svc_mgr.scan_services()
    repos = await svc_mgr.list_repos()
    repo_map = {}
    for r in repos:
        for svc in json.loads(r.get("services", "[]")):
            repo_map[svc] = r
    for s in services:
        if s["name"] in repo_map:
            s["repo"] = repo_map[s["name"]]
    return {"services": services}


@app.post("/api/services/upload-zip", dependencies=[Depends(require_auth)])
async def upload_service_zip(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Only .zip files accepted")
    try:
        installed = svc_mgr.install_from_zip(await file.read())
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    return {"installed": installed, "count": len(installed)}


class GitCloneRequest(BaseModel):
    url: str
    branch: str = "main"


@app.post("/api/services/clone", dependencies=[Depends(require_auth)])
async def clone_service(req: GitCloneRequest):
    try:
        return await svc_mgr.clone_repo(req.url, req.branch)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/services/{name}/pull", dependencies=[Depends(require_auth)])
async def pull_service(name: str):
    try:
        return await svc_mgr.pull_repo(name)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/services/{name}", dependencies=[Depends(require_auth)])
async def delete_service(name: str):
    try:
        await svc_mgr.delete_service_entry(name)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"deleted": name}


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings", dependencies=[Depends(require_auth)])
async def get_settings():
    return await get_all_settings()


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


@app.post("/api/settings", dependencies=[Depends(require_auth)])
async def update_settings(payload: SettingsUpdate):
    for k, v in payload.settings.items():
        await set_setting(k, v)
    return {"saved": True}


# ── Downloads browser ─────────────────────────────────────────────────────────

@app.get("/api/downloads", dependencies=[Depends(require_auth)])
async def list_downloads():
    base = Path(os.environ.get("DOWNLOADS_PATH", "/downloads"))
    items = []
    if base.exists():
        for f in sorted(base.rglob("*")):
            rel_path = str(f.relative_to(base))
            is_dir = f.is_dir()
            items.append({
                "name": f.name,
                "path": rel_path,
                "is_dir": is_dir,
                "size": f.stat().st_size if not is_dir else 0,
                "modified": f.stat().st_mtime,
            })
    return {"files": items}


@app.get("/api/downloads/get/{path:path}", dependencies=[Depends(require_auth)])
async def download_file_content(path: str):
    base = Path(os.environ.get("DOWNLOADS_PATH", "/downloads"))
    target = (base / path).resolve()
    
    # Security: Ensure the path is inside the downloads directory
    if not str(target).startswith(str(base.resolve())):
        raise HTTPException(403, "Access denied")
        
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "File not found")
        
    return FileResponse(target, filename=target.name)


@app.delete("/api/downloads/{path:path}", dependencies=[Depends(require_auth)])
async def delete_download_item(path: str):
    base = Path(os.environ.get("DOWNLOADS_PATH", "/downloads"))
    target = (base / path).resolve()

    if not str(target).startswith(str(base.resolve())):
        raise HTTPException(403, "Access denied")

    if not target.exists():
        raise HTTPException(404, "Not found")

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"deleted": path}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Tool versions ─────────────────────────────────────────────────────────────

@app.get("/api/tools", dependencies=[Depends(require_auth)])
async def tool_versions():
    import shutil, subprocess
    tools = {}
    checks = {
        "ffmpeg": ["ffmpeg", "-version"],
        "mkvmerge": ["mkvmerge", "--version"],
        "aria2c": ["aria2c", "--version"],
        "ccextractor": ["ccextractor", "--version"],
        "packager": ["packager", "--version"],
        "N_m3u8DL-RE": ["N_m3u8DL-RE", "--version"],
        "unshackle": ["unshackle", "--version"],
    }
    for name, cmd in checks.items():
        if shutil.which(cmd[0]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                first_line = (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else "installed"
                tools[name] = {"installed": True, "version": first_line}
            except Exception:
                tools[name] = {"installed": True, "version": "installed"}
        else:
            tools[name] = {"installed": False, "version": None}
    return {"tools": tools}
