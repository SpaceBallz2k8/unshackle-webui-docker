"""
auth.py - Simple session-based authentication for the WebUI.
Credentials come from .env (WEBUI_USERNAME / WEBUI_PASSWORD).
Password is bcrypt-hashed on first comparison.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Cookie, HTTPException, status
from fastapi.responses import JSONResponse

WEBUI_USERNAME = os.environ.get("WEBUI_USERNAME", "admin")
WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD", "changeme")

# In-memory session store: {token: expiry}
_sessions: dict[str, datetime] = {}
SESSION_TTL_HOURS = 24


def _hash_password(plain: str) -> bytes:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt())


def _check_password(plain: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed)


# Hash the env password once on import
_hashed_pw = _hash_password(WEBUI_PASSWORD)


def login(username: str, password: str) -> Optional[str]:
    """Return a session token if credentials are valid, else None."""
    if username != WEBUI_USERNAME:
        return None
    if not _check_password(password, _hashed_pw):
        return None
    token = secrets.token_urlsafe(32)
    _sessions[token] = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)
    return token


def logout(token: str):
    _sessions.pop(token, None)


def _purge_expired():
    now = datetime.utcnow()
    expired = [t for t, exp in _sessions.items() if exp < now]
    for t in expired:
        del _sessions[t]


def require_auth(session: Optional[str] = Cookie(None)):
    """FastAPI dependency — raises 401 if not logged in."""
    _purge_expired()
    if not session or session not in _sessions:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    # Refresh TTL on activity
    _sessions[session] = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)
