import { useCallback } from 'react'
import { useRegion } from '../context/RegionContext'

/** A path that keeps the selected region in the URL, so links and reloads open the same region. */
export function useRegionLink(): (path: string, extra?: Record<string, string | null>) => string {
  const { regionId } = useRegion()
  return useCallback(
    (path, extra = {}) => {
      const params = new URLSearchParams()
      if (regionId) params.set('region', regionId)
      for (const [k, v] of Object.entries(extra)) if (v) params.set(k, v)
      const query = params.toString()
      return query ? `${path}?${query}` : path
    },
    [regionId],
  )
}
