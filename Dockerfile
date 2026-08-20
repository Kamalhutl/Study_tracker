# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps (build time only : sqlite for psycopg compiles here).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/prod.txt /app/requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt

# ---- dev image --------------------------------------------------------------
FROM base AS dev
COPY requirements/dev.txt /app/requirements/
RUN pip install --no-cache-dir -r requirements/dev.txt

COPY . /app

# ---- prod image -------------------------------------------------------------
FROM base AS prod
COPY . /app

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]