import { getEvents, getIncidents } from '../api/regions'
import { useRegionQuery } from './useRegionQuery'

/** Open events for the selected region; shared by the bell, the drawer and the Events page. */
export function useRegionEvents() {
  return useRegionQuery('events', getEvents, { refetchMs: 60_000 })
}

export function useRegionIncidents() {
  return useRegionQuery('incidents', getIncidents, { refetchMs: 60_000 })
}
