# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 aeropulse
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps ./apps
COPY connectors ./connectors
COPY fixtures ./fixtures
COPY config ./config
COPY infrastructure/db ./infrastructure/db

# `models/` is gitignored (pickle artifacts). Create an empty registry root so
# the image builds without a local train run; GET /api/v1/models then lists
# deterministic baselines until AEROPULSE_MODEL_DIR is populated.
RUN mkdir -p models \
    && uv sync --frozen --no-dev --no-install-project \
    && uv sync --frozen --no-dev \
    && chown -R aeropulse:aeropulse /app

ENV UV_FROZEN=1 UV_NO_SYNC=1

USER aeropulse
EXPOSE 8000
