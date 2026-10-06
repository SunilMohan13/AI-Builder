import { mockEvents, HERO_EVENT_ID } from '../data/mockEvents'
import type { PollutionEvent } from '../types'
import { liveEvent, liveEvents } from '../api/live'
import { resolve } from './resolve'

const delay = (ms = 120) => new Promise((r) => setTimeout(r, ms))

let livePm25Offset = 0

export function bumpLivePm25() {
  livePm25Offset += Math.round((Math.random() - 0.3) * 6)
}

export function getLivePm25Offset() {
  return livePm25Offset
}

async function demoEvents(): Promise<PollutionEvent[]> {
  await delay()
  return mockEvents.map((e) =>
    e.id === HERO_EVENT_ID ? { ...e, pm25: e.pm25 + livePm25Offset } : e,
  )
}

async function demoEvent(id: string): Promise<PollutionEvent | null> {
  await delay()
  const event = mockEvents.find((e) => e.id === id)
  if (!event) return null
  return event.id === HERO_EVENT_ID ? { ...event, pm25: event.pm25 + livePm25Offset } : event
}

export async function fetchEvents(): Promise<PollutionEvent[]> {
  return resolve('events', demoEvents, liveEvents)
}

export async function fetchEvent(id: string): Promise<PollutionEvent | null> {
  return resolve(
    'event',
    () => demoEvent(id),
    () => liveEvent(id),
  )
}

export async function fetchActiveEventCount(): Promise<number> {
  const events = await fetchEvents()
  return events.filter((e) => e.status === 'ACTIVE' || e.status === 'CONFIRMED').length
}
