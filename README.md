# unshackle-webui

A fully dockerised web interface for [unshackle](https://github.com/unshackle-dl/unshackle).

## What's included

The container installs everything needed automatically:

| Tool | Purpose |
|------|---------|
| unshackle | Core download engine (from 'dev' upstream GitHub) |
| ffmpeg | Stream remuxing |
| mkvtoolnix | MKV muxing |
| aria2c | Download accelerator |
| CCExtractor | Closed caption extraction |
| shaka-packager | CENC-CTR/CBCS decryption |
| N_m3u8DL-RE | HLS/DASH downloading |

## Quick Start

```bash
# 1. Clone this repo
git clone https://github.com/yourusername/unshackle-webui.git
cd unshackle-webui

# 2. Edit .env (set your username/password and port)
nano .env

# 3. Build and start
docker compose up -d --build

# 4. Open the web UI
open http://localhost:8080
```

## First-time setup

On first login:
1. Go to **WVDs** and upload your `.wvd` Widevine device file, then click **Set Active**
2. Go to **Credentials** and add your service login details
3. Go to **Services** and upload your service modules (zip or git repo)
4. Go to **Settings** to configure output templates, CDM, and download options
5. Start downloading from the **Download** tab

## Directory structure

```
unshackle-webui/
├── .env                  ← Your settings (port, login)
├── docker-compose.yml
├── Dockerfile
├── config/
│   ├── unshackle.yaml    ← Main config (auto-generated on first run)
│   ├── WVDs/             ← Drop .wvd files here
│   ├── Cookies/          ← Cookie files (SERVICE.txt)
│   ├── Cache/
│   ├── Logs/
│   └── vaults/
├── services/             ← Service .py modules
└── downloads/            ← Completed downloads
```

## Configuration

All configuration is done through the web UI:

- **WVDs** — Upload Widevine device files, set active device
- **Credentials** — Per-service username/password, with profile support
- **Cookies** — Cookie files for services that use browser auth
- **Services** — Upload zip or clone git repos containing service modules
- **Settings** — Output templates, download options, muxing, subtitles, headers, CDM
- **Config File** — Raw YAML editor for advanced configuration

## .env options

```env
WEBUI_HOST=0.0.0.0       # Bind address
WEBUI_PORT=8080           # Web UI port
WEBUI_USERNAME=admin      # Login username
WEBUI_PASSWORD=changeme   # Login password (change this!)
TZ=Europe/London          # Timezone
```

## Updating unshackle

Since unshackle is cloned from upstream during the Docker build, updating is just:

```bash
docker compose up -d --build
```

This pulls the latest unshackle from GitHub and rebuilds. Your config, services, WVDs and downloads are all in mounted volumes and are untouched.

## Architecture

```
┌─────────────────────────────────────┐
│           Docker Container           │
│                                      │
│  ┌──────────────┐  ┌──────────────┐ │
│  │  unshackle   │  │  FastAPI     │ │
│  │  serve       │  │  WebUI       │ │
│  │  :8786       │◄─│  :8080       │ │
│  │  (internal)  │  │  (external)  │ │
│  └──────────────┘  └──────────────┘ │
│                                      │
│  /config  /services  /downloads      │
└─────────────────────────────────────┘
```

The WebUI talks exclusively to `unshackle serve`'s REST API — no subprocess hacking, no output parsing. Clean separation means unshackle can be updated from upstream at any time without touching the WebUI code.
