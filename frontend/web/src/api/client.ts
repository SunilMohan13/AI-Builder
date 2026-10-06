/**
 * Thin fetch wrapper for the AeroPulse API.
 *
 * Responsibilities kept here so no caller repeats them: the bearer token,
 * a timeout, and turning a non-2xx into a typed error carrying the status.
 * Everything above this layer deals in `ApiError`, not in `Response`.
 */

import { API_BASE, API_TIMEOUT_MS, API_TOKEN, HAS_API_TOKEN } from '../config/env'

export class ApiError extends Error {
  readonly status: number
  readonly path: string

  constructor(message: string, status: number, path: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.path = path
  }

  /** A human-readable cause, for the fallback banner. */
  get reason(): string {
    if (this.status === 0) return 'backend unreachable'
    if (this.status === 401) return 'token rejected (401)'
    if (this.status === 403) return 'insufficient role (403)'
    if (this.status === 404) return 'not found (404)'
    if (this.status === 503) return 'backend storage unavailable (503)'
    return `HTTP ${this.status}`
  }
}

/** Raised before any request when live mode cannot be attempted at all. */
export class MissingTokenError extends ApiError {
  constructor(path: string) {
    super(
      'No VITE_API_TOKEN configured. Mint one with `uv run python -c "from ' +
        'aeropulse_auth import encode_token, Role; print(encode_token(\'ui\', ' +
        "[Role.VIEWER]))\" and put it in frontend/web/.env.local",
      401,
      path,
    )
    this.name = 'MissingTokenError'
  }

  get reason(): string {
    return 'no API token configured'
  }
}

/**
 * Resolve an API path against `API_BASE`, or same-origin when the base is empty.
 */
function requestUrl(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>,
): string {
  const url = API_BASE
    ? new URL(API_BASE + path)
    : new URL(path, typeof window === 'undefined' ? 'http://localhost' : window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null) continue
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

/**
 * GET a JSON resource from the API.
 *
 * @param path Path beginning with `/`, e.g. `/api/v1/events`.
 * @param params Query parameters; `undefined` and `null` values are dropped
 *   rather than serialised as the strings "undefined"/"null".
 * @throws {ApiError} On timeout, network failure or a non-2xx response.
 */
export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>,
): Promise<T> {
  if (!HAS_API_TOKEN) throw new MissingTokenError(path)

  const url = requestUrl(path, params)

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS)
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Authorization: `Bearer ${API_TOKEN}`, Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!response.ok) {
      throw new ApiError(`GET ${path} failed`, response.status, path)
    }
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    // AbortError and TypeError (CORS, DNS, refused connection) both land
    // here. Status 0 distinguishes "never reached the server" from any HTTP
    // answer, which is what the banner needs to say.
    const message = error instanceof Error ? error.message : 'network failure'
    throw new ApiError(message, 0, path)
  } finally {
    clearTimeout(timer)
  }
}

/** POST a JSON body and read a JSON response. */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  if (!HAS_API_TOKEN) throw new MissingTokenError(path)

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS)
  try {
    const response = await fetch(requestUrl(path), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${API_TOKEN}`,
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!response.ok) throw new ApiError(`POST ${path} failed`, response.status, path)
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    const message = error instanceof Error ? error.message : 'network failure'
    throw new ApiError(message, 0, path)
  } finally {
    clearTimeout(timer)
  }
}

/** POST multipart form data (citizen photo). Do not set Content-Type — the boundary must be the browser's. */
export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  if (!HAS_API_TOKEN) throw new MissingTokenError(path)

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), Math.max(API_TIMEOUT_MS, 20_000))
  try {
    const response = await fetch(requestUrl(path), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${API_TOKEN}`,
        Accept: 'application/json',
      },
      body,
      signal: controller.signal,
    })
    if (!response.ok) throw new ApiError(`POST ${path} failed`, response.status, path)
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    const message = error instanceof Error ? error.message : 'network failure'
    throw new ApiError(message, 0, path)
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Probe the backend without authentication.
 *
 * `/health` is deliberately unauthenticated, so this separates "backend is
 * down" from "token is wrong" — two problems with very different fixes that
 * would otherwise both surface as a failed request.
 */
export async function probeHealth(): Promise<boolean> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 3000)
  try {
    const response = await fetch(requestUrl('/health'), { signal: controller.signal })
    return response.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

/** Shape shared by every paginated list route. */
export interface ListResponse<T> {
  items: T[]
  total?: number
  limit?: number | null
  offset?: number
}

/** Shape shared by every GeoJSON map route. */
export interface FeatureCollection<P> {
  type: 'FeatureCollection'
  generated_at: string
  features: { type: 'Feature'; geometry: { type: string; coordinates: never }; properties: P }[]
  provenance?: Record<string, unknown>
}
