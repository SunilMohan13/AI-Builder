import { mockNotifications } from '../data/mockPopulation'
import type { Notification } from '../types'
import { liveAlerts } from '../api/live'
import { resolve } from './resolve'

const delay = (ms = 80) => new Promise((r) => setTimeout(r, ms))

/**
 * Mirrors GET /api/v1/alerts.
 *
 * Demo serves the scripted notification set. Live reads alerts the event
 * engine actually raised — previously the drawer was hardcoded to `[]` in
 * Live, so an operator saw nothing no matter how many events were open.
 */
export async function fetchAlerts(): Promise<Notification[]> {
  return resolve(
    'alerts',
    async () => {
      await delay()
      return mockNotifications
    },
    liveAlerts,
  )
}
