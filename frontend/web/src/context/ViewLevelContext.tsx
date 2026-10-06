import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

/**
 * Progressive disclosure.
 *
 * AeroPulse is read by two audiences with incompatible needs. An operator or
 * a citizen wants to know how bad it is, where it is going and what to do. A
 * judge or an engineer wants the confidence decomposition, the model version
 * and the endpoint that answered.
 *
 * Showing both at once is what made every screen read as a debug console.
 * `customer` is the default because it is the larger audience and the one
 * that cannot recover from jargon; `advanced` adds the instrumentation back
 * without moving anything to a different page.
 *
 * This is presentation only. It never changes a request, a query key or a
 * value — hiding a number must not alter the number.
 */
export type ViewLevel = 'customer' | 'advanced'

const STORAGE_KEY = 'aeropulse.viewLevel'

interface ViewLevelValue {
  level: ViewLevel
  setLevel: (level: ViewLevel) => void
  /** True when engineering detail should render. */
  advanced: boolean
}

const ViewLevelContext = createContext<ViewLevelValue | null>(null)

function readStored(): ViewLevel {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === 'advanced' ? 'advanced' : 'customer'
  } catch {
    return 'customer'
  }
}

export function ViewLevelProvider({ children }: { children: ReactNode }) {
  const [level, setLevelState] = useState<ViewLevel>(readStored)

  const setLevel = useCallback((next: ViewLevel) => {
    setLevelState(next)
    try {
      sessionStorage.setItem(STORAGE_KEY, next)
    } catch {
      // A blocked sessionStorage costs persistence, not function.
    }
  }, [])

  const value = useMemo<ViewLevelValue>(
    () => ({ level, setLevel, advanced: level === 'advanced' }),
    [level, setLevel],
  )

  return <ViewLevelContext.Provider value={value}>{children}</ViewLevelContext.Provider>
}

export function useViewLevel(): ViewLevelValue {
  const ctx = useContext(ViewLevelContext)
  if (!ctx) throw new Error('useViewLevel must be used within ViewLevelProvider')
  return ctx
}

/** Renders children only in advanced view. */
export function AdvancedOnly({ children }: { children: ReactNode }) {
  const { advanced } = useViewLevel()
  if (!advanced) return null
  return <>{children}</>
}
