# AeroPulse — contributor standards

For people changing the code. Operators: start at [README.md](README.md).  
How the product works: [docs/architecture.md](docs/architecture.md) · [docs/how-it-works.html](docs/how-it-works.html).

## Commands

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest tests/unit tests/contract -q
docker compose --env-file .env -f infrastructure/docker/compose.yaml up --build
```

Mint a local token:

```bash
uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('dev', [Role.ADMIN]))"
```

After renaming ML features, run `uv run aeropulse-ml parity`.

## Product

- Shared contracts only after normalize. No vendor JSON past that line.
- Every served prediction states its version and whether it is degraded. Hazard also states whether it is calibrated. Never show a bare number.
- Missing live keys → not configured, zero records. Never a silent fixture under a live banner.
- IMD stays off: Open-Meteo already covers the same weather sites.
- This build uses HS256 JWT. OIDC is later.
- 1 km cells (H3 resolution 8).
- No language model on detection, anomaly, likelihood, or forecast. Ask AeroPulse is the only LLM surface.
- Copilot figures come only from tools and must pass grounding.
- Air-quality labels are CPCB (India), never US EPA.
- Ground stations outrank CAMS-derived values for the same cell-hour.
- List APIs use `limit` / `offset` and return `items`, `total`, `limit`, `offset`.

## ML

- Feature names live in one place. Training and serving both import them.
- A feature derived from the target is a leak.
- Changing a feature set bumps the version so old files cannot silently serve.
- No random splits — time, space, or season only.
- Fit on training rows, then apply to held-out rows.
- Beat an honest baseline or stay unpromoted. Do not lower a gate to pass.
- Shadow scoring runs after the operator answer already exists.
- Open-Meteo air quality is CAMS output, not station truth.

## Frontend

- Demo is a product. It must work with no API.
- Live never paints Demo data.
- Missing API fields show as “—” with a reason.
- `0.80` hazard is a rank until marked calibrated.
- One HTTP client. One Demo/Live branch.

## Later (not hidden bugs)

Quantile forecasts, hazard calibration, serving a promoted champion for hazard/peak, licensed population data, OIDC, live Sentinel/MODIS/CAMS, exporting traces, load tests.
