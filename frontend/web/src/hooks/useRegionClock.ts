import { useEffect, useState } from 'react'
import { useRegion } from '../context/RegionContext'

/**
 * "Now" for the selected region: the recording's clock in Demo (so ages read
 * as they did when it was recorded), the wall clock in Live.
 */
export function useRegionClock(): { now: Date; timeZone: string; frozen: boolean } {
  const { region, recordedAt } = useRegion()
  const [tick, setTick] = useState(() => new Date())

  useEffect(() => {
    if (recordedAt) return
    const timer = setInterval(() => setTick(new Date()), 15_000)
    return () => clearInterval(timer)
  }, [recordedAt])

  return {
    now: recordedAt ? new Date(recordedAt) : tick,
    timeZone: region?.timezone ?? 'UTC',
    frozen: recordedAt !== null,
  }
}
