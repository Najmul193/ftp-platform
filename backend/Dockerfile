# syntax=docker/dockerfile:1
#
# Multi-stage so the runtime image carries no build toolchain.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq only: the client library, not the build headers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Never run as root -- an upload parser is the one place untrusted bytes are
# handled, so it gets the least privilege available.
RUN useradd --create-home --uid 10001 ftp

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=ftp:ftp alembic.ini ./
COPY --chown=ftp:ftp alembic ./alembic
COPY --chown=ftp:ftp app ./app
COPY --chown=ftp:ftp data ./data

USER ftp
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
