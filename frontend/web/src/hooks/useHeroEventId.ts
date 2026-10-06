import { useQuery } from '@tanstack/react-query'
import { useDataMode } from '../context/DataModeContext'
import { fetchEvents } from '../services/eventService'
import { pickHeroEventId } from '../utils/heroEvent'
import { HERO_EVENT_ID } from '../data/mockEvents'

/**
 * Hero event id for the current data mode.
 *
 * Demo always has EVT-1024. Live returns an id from GET /api/v1/events, or
 * an empty string until that list arrives so nav cannot request a demo id
 * the API does not have.
 */
export function useHeroEventId(): string {
  const { mode } = useDataMode()
  const { data } = useQuery({
    queryKey: ['events', mode],
    queryFn: fetchEvents,
    staleTime: 30_000,
  })
  const fromList = pickHeroEventId(data)
  if (fromList) return fromList
  return mode === 'demo' ? HERO_EVENT_ID : ''
}
