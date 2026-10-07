# syntax=docker/dockerfile:1
# Training image (LLD APAC 7): one family per run, gate report beside the
# artifact. A run never promotes; promotion is a reviewed edit to
# config/model_serving.yaml.
#
#   docker build -f infrastructure/docker/Dockerfile.ml -t aeropulse-ml .
#   docker run --rm -v "$PWD/models:/app/models" aeropulse-ml \
#     --family pm25_forecast --dataset fixture --regions in-north
#
# Cloud Run Jobs: build with --build-arg UV_EXTRAS="--extra gcp" and pass
# --dataset bq://<project>/<dataset>; credentials come from the job's
# service account, never from the image.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 aeropulse
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

ARG UV_EXTRAS=""

COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps ./apps
COPY connectors ./connectors
COPY fixtures ./fixtures
COPY config ./config

RUN mkdir -p models var/aeropulse \
    && uv sync --frozen --no-dev --no-install-project ${UV_EXTRAS} \
    && uv sync --frozen --no-dev ${UV_EXTRAS} \
    && chown -R aeropulse:aeropulse /app

ENV UV_FROZEN=1 UV_NO_SYNC=1 AEROPULSE_MODEL_DIR=/app/models

USER aeropulse
ENTRYPOINT ["aeropulse-ml", "train"]
CMD ["--family", "all", "--dataset", "fixture", "--regions", "in-north"]
