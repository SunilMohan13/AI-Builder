# AeroPulse

Air-quality intelligence for the Punjab–Haryana–Delhi NCR corridor.

The map shows pollution on a 1 km grid, with fires, wind, events, and a forecast. **Demo** is a scripted episode you can open with no backend. **Live** shows whatever this laptop’s stack has actually stored. Ask AeroPulse only explains numbers it looked up — it does not invent a reading.

| Read this | For |
| --- | --- |
| This README | Setup, how to click around |
| [docs/architecture.md](docs/architecture.md) | How data flows, what each number means |
| [docs/how-it-works.html](docs/how-it-works.html) | Click-through diagrams |
| [docs/LLD_AeroPulse_Global.md](docs/LLD_AeroPulse_Global.md) | Proposed design: any region, Google Cloud, better models, citizen-photo smoke and plume intelligence |
| [AGENTS.md](AGENTS.md) | Rules if you change the code |

---

## What you need

- Docker Desktop (or Docker Engine + Compose)
- Optional, for Demo-only UI or tests: Node 22, Python 3.12, [uv](https://docs.astral.sh/uv/)

---

## Setup — full stack (recommended)

### 1. Copy environment

From the repository root:

```bash
cp .env.example .env
```

Leave the file as-is for a first run (replay fixtures, no upstream keys).

### 2. Start everything

```bash
docker compose --env-file .env -f infrastructure/docker/compose.yaml up --build
```

Wait until the API is healthy (the first start can take several minutes while images build).

### 3. Open the product

| Open | URL |
| --- | --- |
| Operator map | http://127.0.0.1:5173 |
| API docs | http://127.0.0.1:8000/docs |

On the map, start in **Demo**. Switch to **Live** only after the stack has been up long enough for the worker to persist events (a minute or two on a warm machine).

Compose already injects a development token into the web container, so Live should be enabled in that UI. If the Live control is disabled, it will say why.

### 4. Stop

```bash
docker compose -f infrastructure/docker/compose.yaml down
```

---

## Setup — Demo UI only (no Docker)

Use this when you only want the scripted episode.

```bash
cd frontend/web
npm install
npm run dev
```

Open http://localhost:5173. Leave the mode on **Demo**. You do not need a token or an API.

---

## Optional next steps

### Live UI against a local API (without Compose web)

1. Start the stack as in step 2, or run the API another way.
2. Mint a token from the repo root:

```bash
uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('ui', [Role.VIEWER]))"
```

3. Copy `frontend/web/.env.example` to `frontend/web/.env.local` and set `VITE_API_TOKEN` to that token. Leave `VITE_API_BASE` empty so the Vite proxy talks to port 8000.
4. `cd frontend/web && npm run dev` and switch the header to **Live**.

### Live station / fire feeds

In `.env`:

1. Set `AEROPULSE_CONNECTOR_MODE=live`.
2. Add a free OpenAQ key and/or FIRMS map key if you want those sources. Open-Meteo needs no key.
3. Recreate the stack with the same `--env-file .env` command as step 2.

A source with no key reports **not configured** and sends nothing. It will not quietly replay a fixture while you think you are live.

### Copilot with Gemini

1. Put `AEROPULSE_GEMINI_API_KEY` in `.env` only (never in the browser env file).
2. Recreate the API so Compose picks it up:

```bash
docker compose --env-file .env -f infrastructure/docker/compose.yaml up -d --force-recreate --no-deps api
```

3. Ask a question in the UI. If Google is busy, the key is missing, or a number cannot be traced to a lookup, the answer falls back to stored evidence and says the language model was not used.

### Checks without the UI

```bash
uv sync
uv run pytest tests/unit tests/contract -q
```

HTTP collection: open `bruno/aeropulse`, choose **local**, paste a token. See [bruno/aeropulse/README.md](bruno/aeropulse/README.md).

---

## How to read the map

| Mode | What you are looking at |
| --- | --- |
| Demo | A fixed Punjab stubble-burning story moving into Delhi NCR. Same every time. |
| Live | Real rows from this stack. Empty cells and “—” are honest gaps, not Demo filler. |

- Air-quality **bands** follow India’s CPCB scale, not US EPA.
- Grid PM2.5 on the live path is **nearby stations, distance-weighted** — not the trained boosting model.
- Hazard / peak banners that say **degraded** are a persistence rule. `0.80` is a ranking, not “80% chance”.
- Never trust a Demo number if the header says Live. If Live fails, a banner names the call.

---

## If something does not start

- Port already in use: the stack binds API `8000`, UI `5173`, database `5433`, Redis `6380`.
- Live disabled: no token in the web container / `.env.local`.
- Copilot not using Gemini: recreate the API with `--env-file .env`; Google may also return “high demand” (503) — the app then uses retrieval on purpose.
- First Compose up is slow: images are building.

More detail: [docs/architecture.md](docs/architecture.md).
