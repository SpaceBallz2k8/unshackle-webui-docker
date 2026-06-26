FROM python:3.12-slim

# ── System tools ──────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    git curl ffmpeg mkvtoolnix aria2 wget ca-certificates \
    tar xz-utils jq procps \
    && rm -rf /var/lib/apt/lists/*

# ── CCExtractor ───────────────────────────────────────────────────────────────
RUN wget -q -O /tmp/ccextractor.deb \
    https://github.com/CCExtractor/ccextractor/releases/download/v0.96.6/ccextractor_0.96.6_debian13_amd64.deb \
    && apt-get update && apt-get install -y /tmp/ccextractor.deb \
    && rm /tmp/ccextractor.deb && rm -rf /var/lib/apt/lists/*

# ── Shaka Packager ────────────────────────────────────────────────────────────
RUN wget -q -O /usr/local/bin/packager \
    https://github.com/shaka-project/shaka-packager/releases/download/v3.7.2/packager-linux-x64 \
    && chmod +x /usr/local/bin/packager

# ── N_m3u8DL-RE ──────────────────────────────────────────────────────────────
RUN wget -q -O /tmp/n_m3u8dl.tar.gz \
    https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.5.1-beta/N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz \
    && mkdir -p /tmp/n_m3u8dl \
    && tar -xzf /tmp/n_m3u8dl.tar.gz -C /tmp/n_m3u8dl \
    && mv /tmp/n_m3u8dl/N_m3u8DL-RE /usr/local/bin/N_m3u8DL-RE \
    && chmod +x /usr/local/bin/N_m3u8DL-RE \
    && rm -rf /tmp/n_m3u8dl /tmp/n_m3u8dl.tar.gz

# ── WebUI deps into system Python FIRST (before unshackle venv exists) ────────
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# ── uv ────────────────────────────────────────────────────────────────────────
RUN curl -Ls https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# ── Unshackle (from upstream) ─────────────────────────────────────────────────
WORKDIR /unshackle
RUN git clone --branch dev https://github.com/unshackle-dl/unshackle.git . \
    && uv sync

# System python (/usr/local/bin/python3) must stay first so uvicorn works.
# Unshackle venv is appended so `unshackle` binary is available but its
# python doesn't override the system python.
ENV PATH="/usr/local/bin:/root/.local/bin:/unshackle/.venv/bin:$PATH"

# ── Copy WebUI ────────────────────────────────────────────────────────────────
WORKDIR /app
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# ── Volume mount points ───────────────────────────────────────────────────────
RUN mkdir -p /config/WVDs /config/Cookies /config/Cache /config/Logs \
             /config/Temp /config/vaults /config/DCSL /config/PRDs \
             /services /downloads /data

COPY entrypoint.sh /app/entrypoint.sh
COPY strip_vaults.py /app/strip_vaults.py
RUN chmod +x /app/entrypoint.sh

EXPOSE ${WEBUI_PORT:-8080}

CMD ["/app/entrypoint.sh"]
