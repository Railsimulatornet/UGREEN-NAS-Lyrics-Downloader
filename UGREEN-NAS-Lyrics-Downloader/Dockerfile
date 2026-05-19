FROM python:3.12-slim

LABEL org.opencontainers.image.title="UGREEN NAS Lyrics Downloader" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.authors="Roman Glos" \
      org.opencontainers.image.description="Downloads synchronized LRC lyrics for music libraries on UGREEN NAS" \
      org.opencontainers.image.licenses="All rights reserved"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/lyrics_downloader.py /app/lyrics_downloader.py
RUN chmod 0755 /app && chmod 0644 /app/lyrics_downloader.py

ENTRYPOINT ["python", "/app/lyrics_downloader.py"]
