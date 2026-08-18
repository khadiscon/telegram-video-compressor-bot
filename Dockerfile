FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY compressor ./compressor
COPY bot.py .

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    TEMP_DIR=/tmp/tg_video_compressor

VOLUME ["/app/data"]

CMD ["python", "-m", "compressor"]
