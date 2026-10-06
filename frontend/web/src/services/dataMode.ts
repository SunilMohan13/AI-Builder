/**
 * The Demo / Live switch.
 *
 * `demo` serves the scripted narrative from `src/data/mock*.ts`: a curated
 * Punjab stubble-burning episode that transports into Delhi NCR. It is a
 * product feature, not a stub. It works with no backend, no token and no
 * network, which is exactly what a demo has to do.
 *
 * `live` calls the AeroPulse API. Without Timescale the API serves the same
 * Punjab replay episode the demo narrates, as contract-valid records. With
 * Timescale it shows whatever the worker has persisted. Models withheld by
 * the promotion gate stay labelled baselines.
 *
 * Why a module-level store rather than React state alone: the service layer
 * is plain async functions called from React Query `queryFn`s, and threading
 * a mode argument through every call site would touch every page for no
 * behavioural gain. The store is tiny, explicit and observable; the React
 * binding lives in `DataModeProvider`.
 */

import { DEFAULT_DATA_MODE } from '../config/env'

export type DataMode = 'demo' | 'live'

/** Why live mode is unavailable, when it is. */
export type LiveBlocker = 'no-token' | 'unreachable' | null

type Listener = () => void

/**
 * Persist the choice for the tab.
 *
 * Session, not local: a demo machine should start fresh tomorrow, but a
 * reload mid-demo must not silently flip a judge from Live back to Demo
 * while the numbers on screen change underneath them.
 */
const STORAGE_KEY = 'aeropulse.dataMode'

function readStored(): DataMode | null {
  try {
    const value = sessionStorage.getItem(STORAGE_KEY)
    return value === 'live' || value === 'demo' ? value : null
  } catch {
    // Private browsing and blocked site data both throw here. The toggle
    // still works; it just will not survive a reload.
    return null
  }
}

function writeStored(value: DataMode): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, value)
  } catch {
    // Non-fatal: persistence is a convenience, not a requirement.
  }
}

let mode: DataMode = readStored() ?? DEFAULT_DATA_MODE
let blocker: LiveBlocker = null
const listeners = new Set<Listener>()

/** Endpoints that answered from demo data because live failed, this session. */
const fallbacks = new Map<string, string>()

function emit(): void {
  for (const listener of listeners) listener()
}

/** Subscribe to mode changes. Returns an unsubscribe function. */
export function subscribeDataMode(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Current mode. Services call this; components use `useDataMode()`. */
export function getDataMode(): DataMode {
  return mode
}

/** True when the demo narrative should answer. */
export function isDemo(): boolean {
  return mode === 'demo'
}

export function setDataMode(next: DataMode): void {
  if (next === mode) return
  mode = next
  writeStored(next)
  // A fresh mode starts with a clean slate: a fallback recorded against the
  // previous session would otherwise keep warning about a failure that is no
  // longer happening.
  fallbacks.clear()
  emit()
}

export function getLiveBlocker(): LiveBlocker {
  return blocker
}

export function setLiveBlocker(next: LiveBlocker): void {
  if (next === blocker) return
  blocker = next
  emit()
}

/**
 * Record that a live call failed.
 *
 * Live never substitutes demo data. The banner lists the failed endpoint so
 * the operator sees a gap, not a scripted Punjab episode under a Live header.
 */
export function recordFallback(endpoint: string, reason: string): void {
  if (fallbacks.get(endpoint) === reason) return
  fallbacks.set(endpoint, reason)
  emit()
}

export function clearFallback(endpoint: string): void {
  if (!fallbacks.has(endpoint)) return
  fallbacks.delete(endpoint)
  emit()
}

/** Endpoints currently failing in live mode. */
export function getFallbacks(): { endpoint: string; reason: string }[] {
  return [...fallbacks.entries()].map(([endpoint, reason]) => ({ endpoint, reason }))
}
