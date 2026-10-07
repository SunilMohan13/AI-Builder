/**
 * Where an API call is answered: the AeroPulse API (Live) or a recording of
 * that same API over a real cycle (Demo).
 *
 * Every region endpoint takes a `Transport`, so Demo and Live run the same
 * request code and the same parsing. `services/resolve.ts` is the only place
 * that chooses one.
 */

import { ApiError, apiGet, apiPost, apiPostForm } from './client'

export type Params = Record<string, string | number | boolean | undefined | null>

export interface Transport {
  readonly kind: 'live' | 'demo'
  get<T>(path: string, params?: Params): Promise<T>
  post<T>(path: string, body: Record<string, unknown>): Promise<T>
  postForm<T>(path: string, body: FormData): Promise<T>
}

export const httpTransport: Transport = {
  kind: 'live',
  get: (path, params) => apiGet(path, params),
  post: (path, body) => apiPost(path, body),
  postForm: (path, body) => apiPostForm(path, body),
}

export interface RecordedResponse {
  status: number
  body: unknown
  request?: Record<string, unknown>
}

/** Python's `urlencode(sorted(...))`, which the generator used for the key. */
export function recordingKey(method: string, path: string, params?: Params): string {
  const pairs = Object.entries(params ?? {})
    .filter((entry): entry is [string, string | number | boolean] => entry[1] != null)
    .map(([k, v]) => [k, String(v)] as const)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  const query = new URLSearchParams(pairs.map(([k, v]) => [k, v])).toString()
  return `${method} ${path}${query ? `?${query}` : ''}`
}

/** `json.dumps(value, sort_keys=True)` with Python's default separators and ASCII escaping. */
export function pythonJson(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string') {
    return JSON.stringify(value).replace(
      /[\u0080-\uffff]/g,
      (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`,
    )
  }
  if (typeof value === 'number' || typeof value === 'boolean') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(pythonJson).join(', ')}]`
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  return `{${entries.map(([k, v]) => `${pythonJson(k)}: ${pythonJson(v)}`).join(', ')}}`
}

const NOT_RECORDED = 'not in the Demo recording — switch to Live to ask the API'

/**
 * Answers from a recording. A request that was not recorded is a 404 with
 * that reason, never an invented answer.
 */
export function recordingTransport(responses: Record<string, RecordedResponse>): Transport {
  const answer = <T>(key: string, path: string): T => {
    const hit = responses[key]
    if (hit === undefined) throw new ApiError(NOT_RECORDED, 404, path, NOT_RECORDED)
    if (hit.status >= 400) {
      const detail = (hit.body as { detail?: unknown } | null)?.detail
      throw new ApiError(
        `recorded ${hit.status}`,
        hit.status,
        path,
        typeof detail === 'string' ? `${detail} (${hit.status})` : undefined,
      )
    }
    return hit.body as T
  }
  return {
    kind: 'demo',
    get: async (path, params) => answer(recordingKey('GET', path, params), path),
    post: async (path, body) => {
      // Recorded answers carry no conversation history; the key ignores it.
      const { history: _history, ...keyed } = body
      return answer(`${recordingKey('POST', path)}#${pythonJson(keyed)}`, path)
    },
    postForm: async (path) => {
      const why = 'uploads need Live mode; Demo only replays recorded reads'
      throw new ApiError(why, 405, path, why)
    },
  }
}

/** True when an error means "Demo has no answer for this", not a failure. */
export function isNotRecorded(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 405)
}
