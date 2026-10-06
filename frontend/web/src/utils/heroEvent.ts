import { HERO_EVENT_ID } from '../data/mockEvents'
import type { PollutionEvent } from '../types'

/**
 * The event the shell, tour and command palette should open.
 *
 * Demo always uses EVT-1024. Live uses that id when the replay seed (or a
 * real ingest) produced it, otherwise the most recently updated active
 * event so a Timescale-backed API with different ids still has working nav.
 *
 * Live must not fall back to EVT-1024 when the list is empty or still
 * loading — that id 404s against a populated Timescale catalog.
 */
export function pickHeroEvent(events: PollutionEvent[] | undefined): PollutionEvent | undefined {
  if (!events?.length) return undefined
  return (
    events.find((event) => event.id === HERO_EVENT_ID) ??
    events.find((event) => event.status === 'ACTIVE' || event.status === 'CONFIRMED') ??
    events[0]
  )
}

export function pickHeroEventId(events: PollutionEvent[] | undefined): string | undefined {
  return pickHeroEvent(events)?.id
}

/** Sidebar / command-palette path. `/events` waits for the live catalog. */
export function heroEventPath(eventId: string | undefined): string {
  return eventId ? `/events/${eventId}` : '/events'
}
