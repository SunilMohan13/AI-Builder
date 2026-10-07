import { useQuery } from '@tanstack/react-query'
import type { Transport } from '../api/transport'
import { isNotRecorded } from '../api/transport'
import { useDataMode } from '../context/DataModeContext'
import { useRegion } from '../context/RegionContext'
import { resolve } from '../services/resolve'

/**
 * A query against the selected region, keyed by mode and region so Demo
 * and Live, or two regions, can never share a cache entry.
 */
export function useRegionQuery<T>(
  endpoint: string,
  call: (transport: Transport, regionId: string) => Promise<T>,
  options: { key?: unknown[]; enabled?: boolean; refetchMs?: number } = {},
) {
  const { mode } = useDataMode()
  const { regionId } = useRegion()
  return useQuery({
    queryKey: [endpoint, mode, regionId, ...(options.key ?? [])],
    queryFn: () => resolve(endpoint, regionId, (t) => call(t, regionId!)),
    enabled: regionId !== null && (options.enabled ?? true),
    retry: (count, error) => !isNotRecorded(error) && count < 1,
    refetchInterval: mode === 'live' ? options.refetchMs : false,
  })
}
