FROM python:3.12-slim

ARG VERSION=1.0.1

LABEL org.opencontainers.image.title="UGREEN NAS Lyrics Downloader" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.authors="Roman Glos" \
      org.opencontainers.image.description="Downloads synchronized LRC lyrics for music libraries on UGREEN NAS" \
      org.opencontainers.image.source="https://github.com/Railsimulatornet/UGREEN-NAS-Lyrics-Downloader" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN set -eux; \
    apt-get update; \
    apt-get -y upgrade; \
    apt-get install -y --no-install-recommends ca-certificates; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN set -eux; \
    python -m pip install --no-cache-dir --upgrade pip setuptools wheel; \
    python -m pip install --no-cache-dir --upgrade -r /app/requirements.txt; \
    python -m pip check; \
    python -m pip uninstall -y setuptools wheel; \
    python -m pip uninstall -y pip; \
    rm -rf /root/.cache /tmp/* /var/tmp/*

COPY app/lyrics_downloader.py /app/lyrics_downloader.py
RUN chmod 0755 /app && chmod 0644 /app/lyrics_downloader.py

ENTRYPOINT ["python", "/app/lyrics_downloader.py"]
