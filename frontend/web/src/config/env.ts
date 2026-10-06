/**
 * Runtime configuration for the live backend.
 *
 * Vite inlines `import.meta.env.VITE_*` at build time, so these are read once
 * rather than plumbed through React state. Compose already sets
 * `VITE_API_BASE`; `VITE_API_URL` is accepted as an alias because the
 * integration plan names it that way, and disagreeing with either would make
 * live mode silently point at nothing.
 */

const raw = import.meta.env as Record<string, string | undefined>

/**
 * Base URL of the AeroPulse API, without a trailing slash.
 *
 * Empty means same-origin. Local `npm run dev` then uses the Vite proxy
 * (`/api`, `/health` → `:8000`) so the browser never cross-origin fetches
 * `localhost:5173` → `127.0.0.1:8000`. Compose and Netlify set this to the
 * public API host.
 */
export const API_BASE = (raw.VITE_API_BASE ?? raw.VITE_API_URL ?? '').replace(/\/+$/, '')

/**
 * Bearer token for the API. Every `/api/v1` route requires one.
 *
 * Development only: mint with
 *   `uv run python -c "from aeropulse_auth import encode_token, Role; \
 *    print(encode_token('ui', [Role.VIEWER]))"`
 * and put it in `frontend/web/.env.local` as `VITE_API_TOKEN=...`.
 *
 * This is a development HS256 token. It is not a
 * production auth story and must not become one — a token compiled into a
 * browser bundle is readable by anyone who loads the page.
 */
export const API_TOKEN = raw.VITE_API_TOKEN ?? ''

/** Whether live mode can even be attempted. */
export const HAS_API_TOKEN = API_TOKEN.length > 0

/**
 * Default mode on first load. Demo, deliberately: the scripted narrative is a
 * product feature and it must work with no backend, no token and no network.
 */
export const DEFAULT_DATA_MODE = (raw.VITE_DEFAULT_DATA_MODE === 'live' ? 'live' : 'demo') as
  | 'demo'
  | 'live'

/** Request timeout. Long enough for a cold Timescale query. A hung backend
 *  fails the Live request; it does not swap in demo data. */
export const API_TIMEOUT_MS = 8000
