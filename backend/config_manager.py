"""
config_manager.py

Read and write unshackle.yaml. Provides structured access to all
config sections so the webui can offer per-section editors.

Always writes to both /config/unshackle.yaml (the volume mount)
and /root/.config/unshackle/unshackle.yaml (the XDG location unshackle reads).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

MAPPED_CFG = Path(os.environ.get("CONFIG_PATH", "/config/unshackle.yaml"))
XDG_CFG = Path("/root/.config/unshackle/unshackle.yaml")
WVD_DIR = Path("/config/WVDs")
COOKIES_DIR = Path("/config/Cookies")


def _load() -> dict:
    if MAPPED_CFG.exists():
        return yaml.safe_load(MAPPED_CFG.read_text()) or {}
    return {}


def _save(cfg: dict):
    MAPPED_CFG.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
    MAPPED_CFG.write_text(text)
    XDG_CFG.parent.mkdir(parents=True, exist_ok=True)
    XDG_CFG.write_text(text)


def get_raw() -> str:
    return MAPPED_CFG.read_text() if MAPPED_CFG.exists() else ""


def save_raw(content: str):
    MAPPED_CFG.parent.mkdir(parents=True, exist_ok=True)
    MAPPED_CFG.write_text(content)
    XDG_CFG.parent.mkdir(parents=True, exist_ok=True)
    XDG_CFG.write_text(content)


# ── Credentials ───────────────────────────────────────────────────────────────

def get_credentials() -> dict:
    return _load().get("credentials", {})


def set_credential(service: str, profile: Optional[str], username: str, password: str):
    """Add or update a credential. profile=None means direct (no profile)."""
    cfg = _load()
    creds = cfg.setdefault("credentials", {})
    if profile:
        if service not in creds or not isinstance(creds[service], dict):
            creds[service] = {}
        creds[service][profile] = f"{username}:{password}"
    else:
        creds[service] = f"{username}:{password}"
    _save(cfg)


def delete_credential(service: str, profile: Optional[str] = None):
    cfg = _load()
    creds = cfg.get("credentials", {})
    if profile and isinstance(creds.get(service), dict):
        creds[service].pop(profile, None)
        if not creds[service]:
            del creds[service]
    else:
        creds.pop(service, None)
    _save(cfg)


# ── CDM ───────────────────────────────────────────────────────────────────────

def get_cdm() -> dict:
    return _load().get("cdm", {})


def set_default_cdm(device_name: str):
    cfg = _load()
    cfg.setdefault("cdm", {})["default"] = device_name
    _save(cfg)


# ── WVDs ──────────────────────────────────────────────────────────────────────

def list_wvds() -> list[dict]:
    WVD_DIR.mkdir(parents=True, exist_ok=True)
    return [
        {"name": f.name, "stem": f.stem, "size": f.stat().st_size}
        for f in sorted(WVD_DIR.glob("*.wvd"))
    ]


def save_wvd(filename: str, data: bytes):
    WVD_DIR.mkdir(parents=True, exist_ok=True)
    (WVD_DIR / filename).write_bytes(data)


def delete_wvd(filename: str):
    p = WVD_DIR / filename
    if p.exists():
        p.unlink()


# ── Cookies ───────────────────────────────────────────────────────────────────

def list_cookies() -> list[dict]:
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    return [
        {"name": f.name, "service": f.stem, "size": f.stat().st_size}
        for f in sorted(COOKIES_DIR.iterdir()) if f.is_file()
    ]


def save_cookie(service: str, data: bytes, ext: str = "txt"):
    """Save cookie file named after the service (e.g. STV.txt)."""
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    (COOKIES_DIR / f"{service}.{ext}").write_bytes(data)


def delete_cookie(filename: str):
    p = COOKIES_DIR / filename
    if p.exists():
        p.unlink()


# ── Full config sections ──────────────────────────────────────────────────────

def get_section(key: str) -> Any:
    return _load().get(key)


def set_section(key: str, value: Any):
    cfg = _load()
    cfg[key] = value
    _save(cfg)


def update_sections(updates: dict):
    """Merge multiple top-level keys at once."""
    cfg = _load()
    cfg.update(updates)
    _save(cfg)


from typing import Optional
