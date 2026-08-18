# Sophisticated Telegram Video Compressor Bot

A production-ready Telegram bot that automatically compresses videos sent or forwarded to it.  
Built with **python-telegram-bot** (v22) and **FFmpeg**.

## Features

- **Automatic processing** of any video or video document received in private chat (including forwarded messages).
- **Configurable quality presets**:
  - Light – higher quality, moderate reduction
  - Medium – balanced (default)
  - Strong – aggressive size reduction
  - Ultra – maximum compression (H.265 + resolution limit)
- **Smart encoding**:
  - H.264 (AVC) or H.265 (HEVC)
  - CRF-based quality control
  - Progressive download optimization (`+faststart`)
  - AAC audio (or stream copy)
  - Optional height capping while preserving aspect ratio
- **Concurrency control** – limited simultaneous jobs to protect server resources.
- **Clear status feedback** – download → analyze → compress → upload progress messages.
- **Size & time reporting** – before/after comparison and processing duration.
- **Automatic temporary file cleanup**.
- **Strict adherence to Telegram Bot API limits**:
  - Download: ≤ 20 MB
  - Upload: ≤ 50 MB

## Requirements

- Python 3.10+
- FFmpeg compiled with `libx264` and `libx265` (most modern packages include both)
- A Telegram Bot token from [@BotFather](https://t.me/BotFather)

### System packages (Ubuntu/Debian example)

```bash
sudo apt update
sudo apt install -y ffmpeg python3-pip python3-venv
```

## Installation

```bash
git clone https://github.com/khadiscon/telegram-video-compressor-bot.git
cd telegram-video-compressor-bot

python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Configuration

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` and set your bot token:

```
BOT_TOKEN=123456:ABC-DEF...
```

Optional variables:

| Variable              | Default | Description                          |
|-----------------------|---------|--------------------------------------|
| `MAX_CONCURRENT_JOBS` | 2       | Maximum simultaneous compressions    |
| `TEMP_DIR`            | system temp | Base directory for temporary files |

## Running the Bot

```bash
python bot.py
```

For production, run under a process manager (systemd, supervisord, or Docker) and consider a reverse proxy or health checks.

## Usage

1. Start a private chat with the bot.
2. Send `/start` or `/help`.
3. Optionally open `/settings` and choose a preset.
4. Send or forward any video (or video file as document).
5. The bot replies with the compressed version and a summary.

## Important Limitations

- **20 MB download limit** is imposed by the official Telegram Bot API cloud endpoint. Videos larger than this cannot be retrieved with `getFile`.
- For files up to 2 GB you must run a **local Bot API server** and point the bot library to it.
- Compression is CPU-intensive. A modest VPS (2–4 vCPU) is recommended for concurrent use.
- Very short or already highly compressed videos may show limited further reduction.

## Extending the Bot

Possible enhancements:

- Queue with priority / estimated wait time
- Custom CRF / resolution via conversation
- Progress percentage by parsing FFmpeg `-progress`
- Thumbnail generation
- Admin-only usage or whitelist
- Logging to a channel
- Docker image with multi-stage build

## License

MIT License – feel free to adapt for personal or commercial use.
