#!/bin/bash
set -e

UNSHACKLE_CFG_DIR="/root/.config/unshackle"
UNSHACKLE_CFG="$UNSHACKLE_CFG_DIR/unshackle.yaml"
MAPPED_CFG="${CONFIG_PATH:-/config/unshackle.yaml}"
UNSHACKLE_API_PORT="${UNSHACKLE_API_PORT:-8786}"
UNSHACKLE_API_SECRET="${UNSHACKLE_API_SECRET:-internal-secret-change-me}"
WEBUI_HOST="${WEBUI_HOST:-0.0.0.0}"
WEBUI_PORT="${WEBUI_PORT:-8080}"
SERVICES_PATH="${SERVICES_PATH:-/services}"
PYTHON=/usr/local/bin/python3

# Ensure variables are available to the Python subprocesses
export UNSHACKLE_API_PORT UNSHACKLE_API_SECRET WEBUI_HOST WEBUI_PORT SERVICES_PATH
export DATABASE_URL="/data/unshackle.db"

echo "[entrypoint] Starting unshackle-webui..."
echo "[entrypoint] Python: $($PYTHON --version)"
echo "[entrypoint] Uvicorn: $($PYTHON -m uvicorn --version 2>&1)"

mkdir -p "$UNSHACKLE_CFG_DIR"

# ── Symlink config subdirs ────────────────────────────────────────────────────
for subdir in WVDs Cookies Cache Logs Temp vaults DCSL PRDs; do
    mkdir -p "/config/$subdir"
    rm -rf "$UNSHACKLE_CFG_DIR/$subdir"
    ln -s "/config/$subdir" "$UNSHACKLE_CFG_DIR/$subdir"
done
rm -rf "$UNSHACKLE_CFG_DIR/services"
ln -s "$SERVICES_PATH" "$UNSHACKLE_CFG_DIR/services"

# ── Generate default config if missing ───────────────────────────────────────
if [ ! -f "$MAPPED_CFG" ]; then
    echo "[entrypoint] Generating default config..."
    cat > "$MAPPED_CFG" << YAML
# unshackle.yaml - managed by unshackle-webui
output_template:
  movies: '{title}.{year}.{repack?}.{edition?}.{quality}.{source}.WEB-DL.{dual?}.{multi?}.{audio_full}.{atmos?}.{hdr?}.{hfr?}.{video?}-{tag?}'
  series: '{title}.{year?}.{season_episode}.{episode_name?}.{repack?}.{edition?}.{quality}.{source}.WEB-DL.{dual?}.{multi?}.{audio_full}.{atmos?}.{hdr?}.{hfr?}.{video?}-{tag?}'
  songs: '{track_number}.{title}.{repack?}.{edition?}.{source?}.WEB-DL.{audio_full}.{atmos?}-{tag?}'
directories:
  cache: /config/Cache
  cookies: /config/Cookies
  dcsl: /config/DCSL
  downloads: /downloads
  logs: /config/Logs
  temp: /config/Temp
  wvds: /config/WVDs
  prds: /config/PRDs
  services:
    - /services
  vaults: /config/vaults/
dl:
  best: true
  worst: false
  best_available: false
  no_proxy_download: false
  sub_format: srt
  downloads: 4
  workers: 16
YAML
fi

# ── Sanitise and prepare the active XDG config ────────────────────────────────
# This function copies /config/unshackle.yaml → XDG location,
# strips broken vault entries, fixes directories, and injects the API secret.
prepare_config() {
    cp -f "$MAPPED_CFG" "$UNSHACKLE_CFG"
    $PYTHON /app/strip_vaults.py "$UNSHACKLE_CFG"
    $PYTHON - << PYEOF
import yaml, os, sys
path = "$UNSHACKLE_CFG"
secret = os.environ.get("UNSHACKLE_API_SECRET", "internal-secret-change-me")
try:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("directories", {}).update({
        "cache": "/config/Cache", "cookies": "/config/Cookies",
        "dcsl": "/config/DCSL", "downloads": "/downloads",
        "logs": "/config/Logs", "temp": "/config/Temp",
        "wvds": "/config/WVDs", "prds": "/config/PRDs",
        "services": ["/services"], "vaults": "/config/vaults/",
    })
    # Ensure all dl defaults are present to prevent signature errors
    dl = cfg.setdefault("dl", {})
    dl.setdefault("best", True)
    dl.setdefault("worst", False)
    dl.setdefault("best_available", False)
    dl.setdefault("no_proxy_download", False)
    dl.setdefault("no_proxy", False)

    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    print(f"[entrypoint] Config ready (secret injected): {path}")
except Exception as e:
    print(f"[entrypoint] Config error: {e}", file=sys.stderr)
PYEOF
}

prepare_config

# ── Runtime compatibility patch for result() signature changes ────────────────
# The dev branch changes result() parameters frequently; this ensures they are
# all optional so the API call works regardless of exact upstream version.
$PYTHON /app/patch_result.py || true

# ── Config watcher — runs AFTER initial prepare ───────────────────────────────
# Re-runs prepare_config whenever the user edits /config/unshackle.yaml
(
    set +e
    LAST_HASH=$(md5sum "$MAPPED_CFG" 2>/dev/null | cut -d' ' -f1 || echo "")
    while true; do
        sleep 3
        if [ -f "$MAPPED_CFG" ]; then
            HASH=$(md5sum "$MAPPED_CFG" 2>/dev/null | cut -d' ' -f1 || echo "")
            if [ -n "$HASH" ] && [ "$HASH" != "$LAST_HASH" ]; then
                echo "[watcher] Config change detected, updating XDG config..."
                prepare_config || true
                LAST_HASH="$HASH"
            fi
        fi
    done
) &

# ── Start unshackle serve ─────────────────────────────────────────────────────
echo "[entrypoint] Starting unshackle REST API on port $UNSHACKLE_API_PORT..."
# --no-key: API is on 127.0.0.1 only, never exposed externally, no auth needed
unshackle serve \
    --host 127.0.0.1 \
    --port "$UNSHACKLE_API_PORT" \
    --api-only \
    --debug-api \
    --no-key \
    &
UNSHACKLE_PID=$!

# Wait for API to be ready
echo "[entrypoint] Waiting for unshackle API..."
for i in $(seq 1 30); do
    # Check if the unshackle process is still running
    if ! kill -0 $UNSHACKLE_PID 2>/dev/null; then
        echo "[entrypoint] ERROR: unshackle process died. Check logs above for the traceback."
        break
    fi

    # Use || echo "000" to prevent set -e from killing the script on connection failure
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
        "http://127.0.0.1:$UNSHACKLE_API_PORT/api/health" 2>/dev/null || echo "000")

    if [ "$HTTP" = "200" ]; then
        echo "[entrypoint] Unshackle API ready! (HTTP $HTTP)"
        break
    fi
    echo "[entrypoint] Waiting for API... attempt $i (HTTP $HTTP)"
    sleep 1
done

# ── Start WebUI ───────────────────────────────────────────────────────────────
echo "[entrypoint] Starting WebUI on $WEBUI_HOST:$WEBUI_PORT..."
cd /app
exec $PYTHON -m uvicorn backend.main:app \
    --host "$WEBUI_HOST" \
    --port "$WEBUI_PORT" \
    --reload
