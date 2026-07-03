# immich-revive

A lightweight background daemon that monitors [Immich](https://immich.app/) job queues and **automatically retries failed machine-learning tasks**.

## Problem

If you offload ML processing (face detection, smart search, etc.) to a remote machine using Immich's [Remote Machine Learning](https://immich.app/docs/features/ml-hardware-acceleration) feature, jobs will fail whenever that machine goes offline. Immich does **not** automatically retry these failed jobs — you have to manually restart them via the Admin UI or CLI every single time.

## Solution

This daemon runs on your Immich server and:

1. **Polls** the Immich API every N seconds (default: 120s)
2. **Detects** failed jobs in the queues you care about
3. **Clears** the failed entries so Immich treats those assets as "unprocessed" again
4. **Triggers** re-processing so they get queued for your ML server

The moment your laptop comes back online, Immich seamlessly picks up where it left off — **zero manual intervention**.

## Compatibility

- Supports **Immich < v2.4.0** (legacy `/api/jobs` endpoint)
- Supports **Immich >= v2.4.0** (new `/api/queues` endpoint)
- Auto-detects which API version your server uses

## Prerequisites

- Python 3.8+ (bare-metal) **or** Docker & Docker Compose
- An Immich **Administrator API Key** (create one in Account Settings → API Keys)

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
git clone https://github.com/wpaalperen/immich-revive
cd immich-revive

cp .env.example .env
nano .env   # set IMMICH_URL and IMMICH_API_KEY

docker compose up -d
docker logs -f immich-revive
```

> **Note:** The included `docker-compose.yml` uses `network_mode: host`, which means the container shares your server's network. This ensures `http://localhost:2283` correctly reaches your Immich instance even though Immich itself runs in a separate Docker container.
>
> If you prefer **not** to use host networking, you can remove the `network_mode: host` line and instead connect this container to Immich's Docker network:
>
> ```yaml
> services:
>   immich-revive:
>     build: .
>     container_name: immich-revive
>     restart: unless-stopped
>     env_file:
>       - .env
>     networks:
>       - immich_default  # Must match Immich's network name
>
> networks:
>   immich_default:
>     external: true
> ```
>
> When using this approach, set `IMMICH_URL=http://immich_server:2283` in your `.env` (replace `immich_server` with the Immich server container name shown by `docker ps`).

### Option 2: Systemd Service (Bare-metal)

If you run this tool directly on the host (not in Docker), `localhost:2283` will work out of the box since Immich publishes its port to the host.

```bash
git clone https://github.com/wpaalperen/immich-revive /opt/immich-revive
cd /opt/immich-revive

pip3 install -r requirements.txt

cp .env.example .env
nano .env   # set IMMICH_URL and IMMICH_API_KEY

sudo cp systemd/immich-revive.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now immich-revive.service

journalctl -u immich-revive.service -f
```

## Configuration

All settings live in the `.env` file:

| Variable | Default | Description |
|---|---|---|
| `IMMICH_URL` | `http://localhost:2283` | Full URL to your Immich instance |
| `IMMICH_API_KEY` | *(required)* | Administrator API key |
| `CHECK_INTERVAL` | `120` | Seconds between each check (minimum 10) |
| `MONITORED_JOBS` | `faceDetection,smartSearch,metadataExtraction` | Comma-separated list of queues to watch |

### Available Queue Names

| Queue Name | Description |
|---|---|
| `faceDetection` | Detect faces in photos |
| `facialRecognition` | Match detected faces to people |
| `smartSearch` | Generate CLIP embeddings for smart search |
| `metadataExtraction` | Extract EXIF/metadata from assets |
| `thumbnailGeneration` | Generate preview thumbnails |
| `videoConversion` | Transcode video files |
| `duplicateDetection` | Find duplicate assets |
| `sidecar` | Process sidecar (XMP) files |

## How It Works

```
┌─────────────────────────────────────┐
│  Immich Server                      │
│                                     │
│  ┌───────────┐   ┌───────────────┐  │
│  │ Immich    │   │ Auto-Resume   │  │
│  │ Server    │◄──│ Daemon        │  │
│  │           │   │               │  │
│  └─────┬─────┘   └───────────────┘  │
│        │  ML requests               │
└────────┼────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│  ML Server          │ ← may go offline
│  immich-machine-    │
│  learning container │
└─────────────────────┘
```

1. Laptop goes offline → ML jobs fail
2. Daemon detects failed jobs via Immich API
3. Daemon clears the failures and re-queues assets
4. Laptop comes back → jobs process successfully

## License

MIT
