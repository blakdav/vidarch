FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask==3.0.3 gunicorn==22.0.0 yt-dlp

WORKDIR /app
COPY app.py .
COPY templates/ templates/

ENV OUTPUT_DIR=/downloads \
    WORKERS=3 \
    PYTHONUNBUFFERED=1

RUN useradd -u 1000 -m app && mkdir -p /downloads && chown app:app /downloads
USER app

EXPOSE 8080

# Single worker process: the download queue lives in memory.
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "8", \
     "-b", "0.0.0.0:8080", "--timeout", "120", "app:app"]
