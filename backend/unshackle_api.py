"""
unshackle_api.py

Async HTTP client for the unshackle REST API (unshackle serve --api-only).
All communication goes through this module — the webui never touches
unshackle internals directly.
"""
from __future__ import annotations

import os
import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("unshackle_api")

UNSHACKLE_API_URL = f"http://127.0.0.1:{os.environ.get('UNSHACKLE_API_PORT', '8786')}"
UNSHACKLE_API_SECRET = os.environ.get("UNSHACKLE_API_SECRET", "internal-secret-change-me")

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=UNSHACKLE_API_URL,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0, read=300.0),
        )
    return _client


async def health() -> dict:
    try:
        r = await get_client().get("/api/health")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"Health check failed: {e}")
        return {"status": "unreachable", "error": str(e)}


async def list_services() -> list[dict]:
    try:
        r = await get_client().get("/api/services")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            services = data.get("services", [])
        else:
            services = data

        normalized = []
        for s in services:
            if isinstance(s, str):
                normalized.append({"name": s})
            else:
                normalized.append(s)
        return normalized
    except Exception as e:
        log.error(f"Failed to list services from engine: {e}")
        return []


async def search(service: str, query: str, profile: Optional[str] = None, proxy: Optional[str] = None) -> dict:
    payload: dict[str, Any] = {"service": service, "query": query}
    if profile:
        payload["profile"] = profile
    if proxy:
        payload["proxy"] = proxy
    r = await get_client().post("/api/search", json=payload)
    r.raise_for_status()
    return r.json()


async def list_titles(service: str, title_id: str, profile: Optional[str] = None) -> dict:
    payload: dict[str, Any] = {"service": service, "title_id": title_id}
    if profile:
        payload["profile"] = profile
    r = await get_client().post("/api/list-titles", json=payload)
    r.raise_for_status()
    return r.json()


async def list_tracks(service: str, title_id: str, wanted: Optional[list] = None) -> dict:
    payload: dict[str, Any] = {"service": service, "title_id": title_id}
    if wanted:
        payload["wanted"] = wanted
    r = await get_client().post("/api/list-tracks", json=payload)
    r.raise_for_status()
    return r.json()


async def start_download(payload: dict) -> dict:
    """
    payload must include: service, title_id
    Optional: wanted, quality, vcodec, acodec, lang, range, latest_episode,
              split_audio, repack, imdb_id, tmdb_id, no_folder, workers, downloads,
              best_available, worst, slow, export, skip_dl, no_proxy_download, etc.
    Returns: {job_id, status, created_time}
    """
    r = await get_client().post("/api/download", json=payload)
    r.raise_for_status()
    return r.json()


async def list_jobs(
    status: Optional[str] = None,
    service: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> list[dict]:
    params: dict[str, str] = {}
    if status:
        params["status"] = status
    if service:
        params["service"] = service
    if sort_by:
        params["sort_by"] = sort_by
    if sort_order:
        params["sort_order"] = sort_order
    r = await get_client().get("/api/download/jobs", params=params)
    r.raise_for_status()
    return r.json().get("jobs", [])


async def get_job(job_id: str) -> dict:
    r = await get_client().get(f"/api/download/jobs/{job_id}")
    r.raise_for_status()
    return r.json()


async def cancel_job(job_id: str) -> dict:
    r = await get_client().delete(f"/api/download/jobs/{job_id}")
    r.raise_for_status()
    return r.json()


async def wait_for_api(max_attempts: int = 30) -> bool:
    """Poll until the unshackle API is ready."""
    for i in range(max_attempts):
        try:
            await health()
            return True
        except Exception:
            await asyncio.sleep(1)
    return False
