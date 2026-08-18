# Compressor — Telegram video bot

Send or forward a video. Get a smaller H.264 MP4 back.

Works with videos, video notes, GIFs, and video files sent as documents — including forwards. Encodes with FFmpeg, shows live progress, and deletes temp files when the job is done.

## What you get

- **Presets:** Light, Medium, Strong, Ultra, plus **8 MB** and **2 MB** target-size modes
- **Ask each time** or auto-compress with your default
- **Live progress** parsed from FFmpeg (`-progress`)
- **Queue** with a global concurrency cap and one job per user
- **Cancel** with `/cancel`
- **Stats** per user; owner sees instance totals
- **Private mode** and owner `/ban` `/unban`
- **Local Bot API** support for files up to 2 GB
- **Docker**, Railway, Render, and systemd unit included

Output is always streamable MP4 (`libx264` + AAC, `yuv420p`, `+faststart`). Resolution is never upscaled. Even dimensions are forced. Metadata is stripped down.

## Limits

| Mode | Download | Upload |
| --- | --- | --- |
| Cloud Bot API (default) | 20 MB | 50 MB |
| Local Bot API server | up to 2 GB | up to 2 GB |

The 20 MB download cap is Telegram's, not this bot's. To raise it, run the [local Bot API](https://github.com/tdlib/telegram-bot-api) overlay in `docker-compose.local-api.yml`.

## Quick start (VPS)

You need Python 3.10+, FFmpeg with `libx264` + AAC, and a token from [@BotFather](https://t.me/BotFather).

```bash
sudo apt update
sudo apt install -y ffmpeg python3-pip python3-venv

git clone https://github.com/khadiscon/telegram-video-compressor-bot.git
cd telegram-video-compressor-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — at minimum set BOT_TOKEN

python -m compressor
```

Talk to the bot in a private chat. Send `/start`, then send or forward a video.

### BotFather setup

1. `/newbot` → copy the token into `BOT_TOKEN`
2. Optional: `/setcommands`

```
start - What this bot does
help - Commands and presets
settings - Default quality
stats - Your totals
queue - Current job
cancel - Stop the encode
privacy - What is stored
```

3. Optional: turn off group privacy if you later add the bot to a group.

### Docker

```bash
cp .env.example .env
# set BOT_TOKEN
docker compose up -d --build
docker compose logs -f
```

### Local Bot API (large files)

Create `api_id` / `api_hash` at [my.telegram.org](https://my.telegram.org), then:

```bash
# in .env
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_LOCAL_API=true
TELEGRAM_API_URL=http://telegram-bot-api:8081
TELEGRAM_FILE_URL=http://telegram-bot-api:8081
DOWNLOAD_LIMIT_MB=2000
UPLOAD_LIMIT_MB=2000

docker compose -f docker-compose.yml -f docker-compose.local-api.yml up -d --build
```

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | — | Required. From BotFather |
| `OWNER_ID` | — | Your numeric user id. Unlocks `/admin` `/ban` `/unban` |
| `MAX_CONCURRENT_JOBS` | `2` | Global encode slots |
| `TEMP_DIR` | `/tmp/tg_video_compressor` | Scratch space |
| `DATA_DIR` | `./data` | `store.json` (settings + stats) |
| `PRIVATE_MODE` | `false` | If true, only `ALLOWED_USER_IDS` + owner |
| `ALLOWED_USER_IDS` | — | Comma-separated numeric ids |
| `JOB_TIMEOUT_SEC` | `900` | Kill a stuck encode |
| `DOWNLOAD_LIMIT_MB` | `20` / `2000` local | Reject larger incoming files |
| `UPLOAD_LIMIT_MB` | `50` / `2000` local | Reject larger outgoing files |
| `TELEGRAM_LOCAL_API` | `false` | Enable local Bot API mode |
| `TELEGRAM_API_URL` | — | e.g. `http://telegram-bot-api:8081` |
| `TELEGRAM_FILE_URL` | — | e.g. `http://telegram-bot-api:8081` |
| `FFMPEG_BIN` | `ffmpeg` | Binary override |
| `FFPROBE_BIN` | auto | Optional; ffmpeg `-i` is the fallback |

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

## Deploy

**Railway** — new project from this repo, set `BOT_TOKEN`, use the included `railway.toml` (Docker worker).

**Render** — `render.yaml` defines a Docker worker. Add `BOT_TOKEN` in the dashboard.

**systemd** — copy `systemd/compressor-bot.service`, adjust paths, `systemctl enable --now compressor-bot`.

A 2 vCPU / 2 GB VPS is enough for a few friends. Encoding is CPU-bound.

## Development

```bash
python -m unittest discover -s tests -v
```

Core encode logic lives in `compressor/engine.py` and has no Telegram imports. Handlers are in `compressor/handlers.py`.

## Privacy

Videos sit on disk only for the length of the job, then the folder is deleted. The JSON store keeps Telegram user id, chosen preset, and byte totals — not the video.

## License

MIT
