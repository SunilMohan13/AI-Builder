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

  readonly explanation: string | null

  constructor(message: string, status: number, path: string, explanation?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.path = path
    this.explanation = explanation ?? null
  }

  /** A human-readable cause, for the fallback banner. */
  get reason(): string {
    if (this.explanation) return this.explanation
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

/** A non-2xx answer, carrying the API's `detail` string when it sent one. */
async function failure(response: Response, method: string, path: string): Promise<ApiError> {
  let detail: string | undefined
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (body.detail === 'Token expired') {
      detail = `demo token expired; the site needs a freshly minted token (${response.status})`
    } else if (typeof body.detail === 'string') {
      detail = `${body.detail} (${response.status})`
    }
  } catch {
    // Not JSON; the status alone is the reason.
  }
  return new ApiError(`${method} ${path} failed`, response.status, path, detail)
}

/**
 * Abort after `ms`, remembering that it was the timer, so a slow answer is
 * reported as a timeout and not as an unreachable backend.
 */
function deadline(ms: number) {
  const controller = new AbortController()
  let expired = false
  const timer = setTimeout(() => {
    expired = true
    controller.abort()
  }, ms)
  return {
    signal: controller.signal,
    clear: () => clearTimeout(timer),
    error(error: unknown, path: string): ApiError {
      if (error instanceof ApiError) return error
      if (expired) {
        return new ApiError('timeout', 0, path, `timed out after ${Math.round(ms / 1000)} s`)
      }
      // TypeError (CORS, DNS, refused connection) lands here. Status 0
      // distinguishes "never reached the server" from any HTTP answer.
      return new ApiError(error instanceof Error ? error.message : 'network failure', 0, path)
    },
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

  const limit = deadline(API_TIMEOUT_MS)
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Authorization: `Bearer ${API_TOKEN}`, Accept: 'application/json' },
      signal: limit.signal,
    })
    if (!response.ok) throw await failure(response, 'GET', path)
    return (await response.json()) as T
  } catch (error) {
    throw limit.error(error, path)
  } finally {
    limit.clear()
  }
}

/** POST a JSON body and read a JSON response. */
export async function apiPost<T>(
  path: string,
  body: unknown,
  timeoutMs: number = API_TIMEOUT_MS,
): Promise<T> {
  if (!HAS_API_TOKEN) throw new MissingTokenError(path)

  const limit = deadline(timeoutMs)
  try {
    const response = await fetch(requestUrl(path), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${API_TOKEN}`,
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: limit.signal,
    })
    if (!response.ok) throw await failure(response, 'POST', path)
    return (await response.json()) as T
  } catch (error) {
    throw limit.error(error, path)
  } finally {
    limit.clear()
  }
}

/** POST multipart form data (citizen photo). Do not set Content-Type — the boundary must be the browser's. */
export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  if (!HAS_API_TOKEN) throw new MissingTokenError(path)

  const limit = deadline(Math.max(API_TIMEOUT_MS, 20_000))
  try {
    const response = await fetch(requestUrl(path), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${API_TOKEN}`,
        Accept: 'application/json',
      },
      body,
      signal: limit.signal,
    })
    if (!response.ok) throw await failure(response, 'POST', path)
    return (await response.json()) as T
  } catch (error) {
    throw limit.error(error, path)
  } finally {
    limit.clear()
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
