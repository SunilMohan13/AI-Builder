import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { getRegion, listRegions } from '../api/regions'
import type { Region } from '../api/regionTypes'
import { DEFAULT_REGION } from '../config/env'
import { demoCatalog } from '../data/regions'
import { resolve } from '../services/resolve'
import { useDataMode } from './DataModeContext'

/**
 * Which region every page is showing. The URL (`?region=`) is the source of
 * truth so a link opens the same region; the session remembers the last one.
 */

const STORAGE_KEY = 'aeropulse.region'

interface RegionValue {
  regions: Region[]
  regionId: string | null
  /** The region's detail (sources, served models) once loaded, else its list entry. */
  region: Region | null
  setRegion: (regionId: string) => void
  /** Whose clock to show: the recording's in Demo, the wall clock in Live. */
  recordedAt: string | null
  loading: boolean
  error: unknown
}

const RegionContext = createContext<RegionValue | null>(null)

function stored(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function remember(regionId: string): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, regionId)
  } catch {
    // Persistence is a convenience; the URL still carries the region.
  }
}

export function RegionProvider({ children }: { children: ReactNode }) {
  const { mode } = useDataMode()
  const [params, setParams] = useSearchParams()

  const list = useQuery({
    queryKey: ['regions', mode],
    queryFn: () => resolve('regions', null, listRegions),
    staleTime: 60_000,
  })
  const regions = useMemo(() => list.data?.items ?? [], [list.data])

  const requested = params.get('region')
  const regionId = useMemo(() => {
    const known = (id: string | null) => (id && regions.some((r) => r.region_id === id) ? id : null)
    return (
      known(requested) ??
      known(stored()) ??
      known(DEFAULT_REGION) ??
      regions.find((r) => r.default)?.region_id ??
      regions[0]?.region_id ??
      null
    )
  }, [regions, requested])

  useEffect(() => {
    if (regionId) remember(regionId)
  }, [regionId])

  const detail = useQuery({
    queryKey: ['region', mode, regionId],
    queryFn: () => resolve('region', regionId, (t) => getRegion(t, regionId!)),
    enabled: regionId !== null,
    staleTime: 30_000,
  })

  const setRegion = useCallback(
    (next: string) => {
      remember(next)
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          updated.set('region', next)
          updated.delete('incident')
          return updated
        },
        { replace: false },
      )
    },
    [setParams],
  )

  const value = useMemo<RegionValue>(
    () => ({
      regions,
      regionId,
      region: detail.data ?? regions.find((r) => r.region_id === regionId) ?? null,
      setRegion,
      recordedAt: mode === 'demo' ? demoCatalog.clock : null,
      loading: list.isLoading,
      error: list.error ?? detail.error,
    }),
    [regions, regionId, detail.data, detail.error, setRegion, mode, list.isLoading, list.error],
  )

  return <RegionContext.Provider value={value}>{children}</RegionContext.Provider>
}

export function useRegion(): RegionValue {
  const ctx = useContext(RegionContext)
  if (!ctx) throw new Error('useRegion must be used within RegionProvider')
  return ctx
}
