FROM aiogram/telegram-bot-api:latest

USER root

RUN apk add --no-cache python3 py3-pip ffmpeg \
    && ln -sf python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY compressor ./compressor
COPY bot.py .
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/data /tmp/tg_video_compressor /var/lib/telegram-bot-api /tmp/telegram-bot-api

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    TEMP_DIR=/tmp/tg_video_compressor \
    TELEGRAM_WORK_DIR=/var/lib/telegram-bot-api \
    TELEGRAM_TEMP_DIR=/tmp/telegram-bot-api \
    TELEGRAM_LOCAL=1 \
    TELEGRAM_HTTP_PORT=8081 \
    DOWNLOAD_LIMIT_MB=500 \
    UPLOAD_LIMIT_MB=500 \
    MAX_CONCURRENT_JOBS=1 \
    JOB_TIMEOUT_SEC=3600

VOLUME ["/app/data", "/var/lib/telegram-bot-api"]

EXPOSE 8081

ENTRYPOINT ["/app/entrypoint.sh"]
