import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { HAS_API_TOKEN, API_BASE, DEFAULT_DATA_MODE } from '../config/env'
import { probeHealth, clearLiveCaches } from '../api'
import {
  getDataMode,
  getFallbacks,
  getLiveBlocker,
  setDataMode,
  setLiveBlocker,
  subscribeDataMode,
  type DataMode,
  type LiveBlocker,
} from '../services/dataMode'

interface DataModeValue {
  mode: DataMode
  setMode: (mode: DataMode) => void
  /** Why live is unavailable, or null when it is fine. */
  blocker: LiveBlocker
  /** Human-readable explanation of `blocker`. */
  blockerMessage: string | null
  /** Endpoints that failed in live mode this session. */
  fallbacks: { endpoint: string; reason: string }[]
  /** True while the health probe is in flight. */
  checking: boolean
  apiBase: string
  recheck: () => void
}

const DataModeContext = createContext<DataModeValue | null>(null)

const BLOCKER_MESSAGES: Record<NonNullable<LiveBlocker>, string> = {
  'no-token':
    'No API token configured. Mint one with `uv run python -c "from aeropulse_auth import ' +
    'encode_token, Role; print(encode_token(\'ui\', [Role.VIEWER]))"` and set VITE_API_TOKEN ' +
    'in frontend/web/.env.local.',
  unreachable:
    'The AeroPulse API did not answer /health. Is it running on ' +
    (API_BASE || 'http://127.0.0.1:8000') +
    '?',
}

export function DataModeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [mode, setModeState] = useState<DataMode>(getDataMode)
  const [blocker, setBlockerState] = useState<LiveBlocker>(getLiveBlocker)
  const [fallbacks, setFallbacks] = useState(getFallbacks)
  const [checking, setChecking] = useState(false)

  // The store is the source of truth; React mirrors it. Services read the
  // store synchronously, which is what lets them stay plain functions.
  useEffect(
    () =>
      subscribeDataMode(() => {
        setModeState(getDataMode())
        setBlockerState(getLiveBlocker())
        setFallbacks(getFallbacks())
      }),
    [],
  )

  const recheck = useCallback(async () => {
    if (!HAS_API_TOKEN) {
      setLiveBlocker('no-token')
      return
    }
    setChecking(true)
    try {
      setLiveBlocker((await probeHealth()) ? null : 'unreachable')
    } finally {
      setChecking(false)
    }
  }, [])

  // Probe once at mount so the toggle can show live as unavailable before
  // anyone clicks it, rather than after a screen of failed requests.
  useEffect(() => {
    void recheck()
  }, [recheck])

  // Reconcile the desired mode with what is actually reachable.
  useEffect(() => {
    if (blocker === null) {
      // Enter live only when explicitly configured to; a restored session
      // choice is already in the store.
      if (DEFAULT_DATA_MODE === 'live' && getDataMode() === 'demo') setDataMode('live')
    }
  }, [blocker])

  const setMode = useCallback(
    (next: DataMode) => {
      if (next === 'live') void recheck()
      // Memoised grid features belong to one mode's view of the world.
      clearLiveCaches()
      setDataMode(next)
      // Every query key is mode-scoped, but resetting is what makes the
      // switch feel immediate instead of showing the previous mode's data
      // until something happens to refetch.
      void queryClient.invalidateQueries()
    },
    [queryClient, recheck],
  )

  const value = useMemo<DataModeValue>(
    () => ({
      mode,
      setMode,
      blocker,
      blockerMessage: blocker ? BLOCKER_MESSAGES[blocker] : null,
      fallbacks,
      checking,
      apiBase: API_BASE,
      recheck: () => void recheck(),
    }),
    [mode, setMode, blocker, fallbacks, checking, recheck],
  )

  return <DataModeContext.Provider value={value}>{children}</DataModeContext.Provider>
}

export function useDataMode(): DataModeValue {
  const ctx = useContext(DataModeContext)
  if (!ctx) throw new Error('useDataMode must be used within DataModeProvider')
  return ctx
}
