# AeroPulse Deployment Guide

Deploy the **UI on Netlify** (free) and optionally connect it to the **FastAPI backend on Render** (free tier). This guide is written for hackathon submission item **#5 — Deployed link**.

---

## Architecture

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  Netlify (static hosting)   │         │  Render (web service)       │
│  https://aeropulse.netlify  │  HTTPS  │  https://aeropulse-api    │
│  .app                       │ ──────► │  .onrender.com              │
│                             │  + JWT  │                             │
│  React + Vite + mock/API    │         │  FastAPI (aeropulse-api)    │
└─────────────────────────────┘         └──────────────┬──────────────┘
                                                       │
                                            (optional) Neon Postgres
```

| Phase | What you get | Effort |
|-------|----------------|--------|
| **1** | Live UI with **mock data** (good for judges) | ~15 min |
| **2** | Live API (`/health`, `/api/v1/*`) on Render | ~30 min |
| **3** | UI calls real API instead of mocks | ~2–4 hrs dev work |

**Recommendation:** Ship **Phase 1** before the deadline. Add Phase 2–3 if you have time.

---

## Prerequisites

- GitHub repo pushed (branch `feature/ui-integration` or `main`)
- [Netlify](https://www.netlify.com) account (free)
- [Render](https://render.com) account (free) — only for Phase 2+
- Node **22** locally to verify builds

Repo already includes:

- `netlify.toml` — Netlify build settings (monorepo → `frontend/web`)
- `frontend/web/public/_redirects` — SPA routing (`/forecast`, `/map`, etc.)

---

## Phase 1 — Deploy UI on Netlify (do this first)

### Step 1 — Push code to GitHub

```bash
cd /path/to/GoogleHack
git checkout feature/ui-integration   # or main after merge
git push -u origin feature/ui-integration
```

Commit deployment config if not already committed:

```bash
git add netlify.toml frontend/web/public/_redirects
git commit -m "Add Netlify deployment config"
git push
```

### Step 2 — Create Netlify site

1. Go to [app.netlify.com](https://app.netlify.com) → **Add new site** → **Import an existing project**
2. Choose **GitHub** and authorize Netlify
3. Select repo: `SunilMohan13/AeroPulse` (or your fork)

### Step 3 — Build settings

Netlify should read **`netlify.toml`** at the repo root automatically:

| Setting | Value |
|---------|--------|
| Base directory | *(leave empty — `netlify.toml` sets `base = "frontend/web"`)* |
| Build command | `npm ci && npm run build` |
| Publish directory | `dist` |
| Branch to deploy | `feature/ui-integration` or `main` |

If you configure manually in the UI instead:

| Setting | Value |
|---------|--------|
| Base directory | `frontend/web` |
| Build command | `npm ci && npm run build` |
| Publish directory | `frontend/web/dist` |

### Step 4 — Environment variables (Phase 1)

For **mock-only** demo, you do **not** need any env vars. The UI uses in-browser mock services.

Optional (prepare for Phase 3):

| Key | Value | Notes |
|-----|--------|--------|
| `VITE_API_BASE` | `https://aeropulse-api.onrender.com` | Only used after Phase 3 code is merged |
| `VITE_USE_MOCKS` | `true` | Keep mocks until API wiring is done |

### Step 5 — Deploy

Click **Deploy site**. First build takes ~2–3 minutes.

### Step 6 — Custom subdomain (optional)

**Site settings → Domain management → Options → Edit site name**

Example: `aeropulse-india.netlify.app`

### Step 7 — Verify

Open the URL and check:

- [ ] Overview loads with KPIs and map
- [ ] **Live Map** (`/map`) — basemap + pollution layers
- [ ] **Forecast** (`/forecast`) — chart animates
- [ ] **Demo Mode** (top bar) runs the scripted incident
- [ ] Direct URL `/events/EVT-1024` works (SPA redirect)

### Step 8 — Local build test (before pushing)

```bash
cd frontend/web
npm ci
npm run build
npm run preview   # http://localhost:4173
```

---

## Phase 2 — Deploy API + web on Render

`render.yaml` at the repo root is the Blueprint. It creates two services:

| Service | How it runs | What you get |
|---------|-------------|--------------|
| `aeropulse-api` | Existing Docker image (`infrastructure/docker/Dockerfile`) | `/health` and `/api/v1/*` from the in-memory Punjab replay. No database is attached, which is the same rehearsal Live mode already describes. |
| `aeropulse-web` | Vite production build, static hosting | The UI. Demo works with no token. The build receives the API URL as `VITE_API_BASE`. |

Render cannot run the rest of `infrastructure/docker/compose.yaml`. TimescaleDB, Redpanda, Redis, MinIO, the worker, the connector, and the drift monitor are not web services, and Render does not offer Kafka or Timescale. Those stay on local Compose.

### Apply the Blueprint

1. Sign in at [dashboard.render.com](https://dashboard.render.com) with the account that should own the services.
2. Push this branch, including `render.yaml`, to GitHub. Render deploys from Git, not from your laptop.
3. **New → Blueprint** → select `SunilMohan13/AeroPulse` (or your fork) and the branch you pushed.
4. Render reads `render.yaml`. It generates `AEROPULSE_JWT_SECRET` and does not show it again. Copy it from the API service’s Environment tab if you need to mint a Live-mode token.
5. First Docker build is slow (it runs `uv sync`). The free API instance sleeps after about 15 minutes; the first request after that can take 30–60 seconds.

### Verify

```bash
curl https://<aeropulse-api-host>/health
```

Open the static site URL. Overview should load in Demo. Direct routes such as `/map` work because the Blueprint rewrites them to `index.html`.

### Live mode

`/api/v1/*` requires a Bearer JWT signed with the Render `AEROPULSE_JWT_SECRET`. Mint a VIEWER token locally against that secret and set `VITE_API_TOKEN` on `aeropulse-web`, then redeploy the static site. Vite bakes `VITE_*` at build time, so changing the variable without a rebuild does nothing. Do not commit the token.

`*.onrender.com` and `*.netlify.app` are allowed by CORS. A custom domain goes in `AEROPULSE_CORS_ORIGINS` on the API.

---

## Phase 3 — Wire UI to live API (development plan)

Today, all frontend services under `frontend/web/src/services/` call **mock data** directly. Connecting to Render requires **UI changes** plus a **small backend CORS update** (not UI-only).

### 3.1 Backend prerequisite (one-time, backend team)

CORS in `apps/api/aeropulse_api/app.py` currently allows only localhost:

```text
allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
```

Add your Netlify URL:

```text
allow_origins=[
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "https://aeropulse-india.netlify.app",  # your Netlify URL
],
```

Or read from env: `AEROPULSE_CORS_ORIGINS=https://....netlify.app`

### 3.2 Authentication

All `/api/v1/*` routes require a **Bearer JWT**.

Mint a dev token locally:

```bash
uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('demo', [Role.VIEWER]))"
```

Store in Netlify (Phase 3):

| Key | Value |
|-----|--------|
| `VITE_API_TOKEN` | `eyJ...` *(viewer JWT)* |

> **Security:** For a public hackathon demo, use a **read-only VIEWER** token. Never commit tokens to git. Rotate `AEROPULSE_JWT_SECRET` on Render if exposed.

### 3.3 Frontend env helper (to implement)

Create `frontend/web/src/config/api.ts`:

```typescript
export const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, '') ?? ''

export const USE_MOCKS =
  import.meta.env.VITE_USE_MOCKS === 'true' || !API_BASE

export const API_TOKEN = import.meta.env.VITE_API_TOKEN ?? ''
```

### 3.4 Shared fetch wrapper (to implement)

Create `frontend/web/src/services/apiClient.ts`:

```typescript
import { API_BASE, API_TOKEN, USE_MOCKS } from '../config/api'

export async function apiGet<T>(path: string): Promise<T> {
  if (USE_MOCKS) throw new Error('mock mode')
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      Accept: 'application/json',
    },
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}
```

### 3.5 Endpoint mapping (mock → API)

| UI service | Mock today | Live API endpoint | Status |
|------------|------------|-------------------|--------|
| `mapService.fetchAirQuality` | `mockGrid` | `GET /api/v1/map/air-quality?bbox=` | API returns **GeoJSON points**, not grid polygons — needs adapter |
| `mapService.fetchFires` | `mockFires` | `GET /api/v1/map/fire?bbox=` | GeoJSON → map layer adapter |
| `mapService.fetchWeather` | `mockWind` | `GET /api/v1/map/weather?bbox=` | GeoJSON → wind adapter |
| `eventService.fetchEvents` | `mockEvents` | `GET /api/v1/events` | Shape differs — map `event.v1` → `PollutionEvent` |
| `eventService.fetchEvent` | `mockEvents` | `GET /api/v1/events/{id}` | Ready with adapter |
| `sourceService.fetchSources` | `mockSources` | `GET /api/v1/sources` | Ready with adapter |
| `forecastService.*` | mocks | `GET /api/v1/events/{id}/forecast` | **501** on API today — keep mocks |
| `evidenceService.*` | mocks | `GET /api/v1/events/{id}/evidence` | Partial — adapt response |
| `copilotService.*` | mocks | Not implemented | Keep mocks |
| `riskService.*` | mocks | Not implemented | Keep mocks |
| `citizenService.*` | mocks | Not implemented | Keep mocks |

**Pragmatic Phase 3 scope:** Wire **events + sources + health** first; keep map/forecast/copilot on mocks until API returns grid/forecast data.

### 3.6 Example: hybrid `eventService.ts`

```typescript
import { USE_MOCKS } from '../config/api'
import { apiGet } from './apiClient'
import { mockEvents, HERO_EVENT_ID } from '../data/mockEvents'

export async function fetchEvents() {
  if (USE_MOCKS) {
    return mockEvents.map(/* existing transform */)
  }
  const data = await apiGet<{ items: unknown[] }>('/api/v1/events')
  return data.items.map(adaptEvent) // implement adaptEvent()
}
```

### 3.7 Netlify env for live API

**Site settings → Environment variables → Production:**

| Variable | Value |
|----------|--------|
| `VITE_API_BASE` | `https://aeropulse-api.onrender.com` |
| `VITE_USE_MOCKS` | `false` |
| `VITE_API_TOKEN` | *(viewer JWT from step 3.2)* |

Trigger **Clear cache and deploy site** after changing env vars (Vite bakes `VITE_*` at build time).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Netlify build fails on `tsc` | Run `npm run build` locally; fix TypeScript errors |
| `/forecast` 404 on refresh | Ensure `_redirects` or `netlify.toml` `[[redirects]]` is committed |
| Map blank (no basemap) | CARTO tiles need internet; check browser console; offline fallback should still show geography |
| API CORS error in browser | Add Netlify URL to API `allow_origins` |
| API 401 | Set `VITE_API_TOKEN` and redeploy Netlify |
| Render slow first load | Free tier cold start — wait or ping `/health` before demo |
| `git push` rejected | Push branch `feature/ui-integration`; open PR to merge |

---

## Hackathon submission checklist

| # | Item | Where |
|---|------|--------|
| 1 | Source code | GitHub: `SunilMohan13/AeroPulse` |
| 2 | Demo video (3–5 min) | Record: Overview → Demo Mode → Live Map → Copilot |
| 3 | Pitch deck | 10–12 slides |
| 4 | Brief description | See below |
| 5 | **Deployed link** | **Netlify URL from Phase 1** |

**Brief description (2–3 lines):**

> AeroPulse is an environmental intelligence platform for India's air-quality crisis. It fuses satellite fire detections, ground sensors, wind, and population data into a live map with AI-powered event detection, source attribution, and forecast plumes across the Punjab–Haryana–Delhi corridor. Built for pollution boards and disaster response — designed to scale nationally via modular connectors and a 1 km evidence grid.

---

## Quick reference commands

```bash
# Local UI
cd frontend/web && npm run dev

# Local API
uv run aeropulse-api

# Full stack (Docker)
docker compose -f infrastructure/docker/compose.yaml up --build

# Production UI build
cd frontend/web && npm ci && npm run build
```

---

## Related files

| File | Purpose |
|------|---------|
| `netlify.toml` | Netlify monorepo build config |
| `frontend/web/public/_redirects` | SPA fallback for client-side routes |
| `frontend/web/vite.config.ts` | Vite + MapLibre worker fix |
| `infrastructure/docker/Dockerfile` | API container for Render |
| `infrastructure/docker/compose.yaml` | Full local stack |
| `render.yaml` | Render Blueprint: API Docker service + static web |

---

*Last updated: September 2026 — AeroPulse hackathon deployment*
