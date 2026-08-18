# Compressor — Telegram video bot

Send or forward a video. Get a smaller H.264 MP4 back.

Personal-use default: **500 MB in / 500 MB out**. That needs Telegram’s **local Bot API** (the cloud API stops at 20 MB). The Docker image runs both the local API and the bot in one container.

Works with videos, video notes, GIFs, and video files sent as documents — including forwards.

## Railway (what you asked for)

1. Open [my.telegram.org](https://my.telegram.org) → API development tools → create an app. Copy **api_id** and **api_hash**.
2. New Railway project from [this repo](https://github.com/khadiscon/telegram-video-compressor-bot).
3. Set these variables:

| Variable | Where |
| --- | --- |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_API_ID` | my.telegram.org |
| `TELEGRAM_API_HASH` | my.telegram.org |
| `OWNER_ID` | your numeric Telegram user id (optional, unlocks `/admin`) |

4. Give the service **at least 2 GB RAM** and ~5 GB disk. A 500 MB encode is CPU-heavy; hobby/512 MB will die.
5. Deploy. Message the bot. Send a video under 500 MB.

The public Railway URL only answers `ok` so the platform health check passes. The bot talks to Telegram over long-polling — you never open that URL to use it.

Without `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` the container **refuses to start**. That is intentional. Cloud Telegram cannot fetch a 500 MB file.

## Local / VPS

```bash
cp .env.example .env
# set BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH

docker compose up -d --build
docker compose logs -f
```

Python-only (cloud API, **20 MB cap** — not what you want for 500 MB):

```bash
sudo apt install -y ffmpeg python3-venv
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m compressor
```

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | — | Required |
| `TELEGRAM_API_ID` | — | Required in Docker / Railway |
| `TELEGRAM_API_HASH` | — | Required in Docker / Railway |
| `OWNER_ID` | — | Your numeric user id |
| `DOWNLOAD_LIMIT_MB` | `500` local / `20` cloud | Reject larger incoming files |
| `UPLOAD_LIMIT_MB` | `500` local / `50` cloud | Reject larger outgoing files |
| `MAX_CONCURRENT_JOBS` | `1` | Encode slots. Keep at 1 on Railway |
| `JOB_TIMEOUT_SEC` | `3600` | Kill a stuck encode |
| `PRIVATE_MODE` | `false` | If true, only `ALLOWED_USER_IDS` + owner |
| `ALLOWED_USER_IDS` | — | Comma-separated numeric ids |
| `TEMP_DIR` | `/tmp/tg_video_compressor` | Scratch space |
| `DATA_DIR` | `/app/data` | `store.json` |

## Commands

| Command | Who | What |
| --- | --- | --- |
| `/start` `/help` `/privacy` | anyone | Intro, docs, data policy |
| `/settings` | anyone | Default preset + ask-each-time |
| `/stats` | anyone | Personal totals (owner also sees instance totals) |
| `/queue` | anyone | Job state and position |
| `/cancel` | anyone | Kill your running encode |
| `/admin` | owner | Instance totals + active jobs |
| `/ban` `/unban` `<id>` | owner | Block or restore a user |

## Presets

| Preset | How it encodes |
| --- | --- |
| Light | CRF 20, up to 1080p, 128k AAC |
| Medium | CRF 23, up to 1080p, 96k AAC |
| Strong | CRF 28, 720p, 30 fps, 80k AAC |
| Ultra | CRF 32, 720p, 24 fps, 64k AAC |
| 8 MB | Constrained bitrate aimed at 8 MB |
| 2 MB | Constrained bitrate aimed at 2 MB |

If the encode is not smaller than the original, the bot says so and does not send a worse file.

## BotFather

1. `/newbot` → `BOT_TOKEN`
2. Optional `/setcommands`:

```
start - What this bot does
help - Commands and presets
settings - Default quality
stats - Your totals
queue - Current job
cancel - Stop the encode
privacy - What is stored
```

## Development

```bash
python -m unittest discover -s tests -v
```

Encode logic is in `compressor/engine.py` (no Telegram imports). Handlers are in `compressor/handlers.py`.

## Privacy

Videos sit on disk only for the length of the job, then the folder is deleted. The JSON store keeps Telegram user id, chosen preset, and byte totals — not the video.

## License

MIT
