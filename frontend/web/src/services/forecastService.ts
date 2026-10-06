import { getForecastSeries, mockForecast, mockObservedHistory } from '../data/mockForecast'
import type { ForecastPoint } from '../types'
import { ApiError } from '../api/client'
import { liveForecast, liveObservedHistory } from '../api/live'
import { resolve } from './resolve'

const delay = (ms = 80) => new Promise((r) => setTimeout(r, ms))

/**
 * Observed PM2.5 leading up to detection.
 *
 * Live reads `GET /api/v1/grid-features/{grid_id}/history`. An empty series
 * is a real answer (no PM2.5 yet), not a missing route.
 */
export async function fetchObservedHistory(
  gridId?: string,
): Promise<{ hour: number; pm25: number }[]> {
  return resolve(
    'observed-history',
    async () => {
      await delay(60)
      return mockObservedHistory
    },
    async () => {
      if (!gridId) {
        throw new ApiError(
          'this event has no grid cell, so there is no observed PM2.5 series',
          404,
          '/api/v1/grid-features/{grid_id}/history',
        )
      }
      return liveObservedHistory(gridId)
    },
  )
}

async function demoForecast(): Promise<ForecastPoint[]> {
  await delay()
  return mockForecast
}

async function demoForecastSeries(): Promise<ForecastPoint[]> {
  await delay()
  return getForecastSeries()
}

/**
 * Forecast series.
 *
 * @param eventId Scope to one event. Omitted, live mode picks the most
 *   recently updated active event, which is what the Overview wants; the
 *   event detail page passes its own id so it cannot show another event's
 *   plume.
 */
export async function fetchForecast(eventId?: string): Promise<ForecastPoint[]> {
  return resolve(
    'forecast',
    demoForecast,
    () => liveForecast(eventId),
  )
}

export async function fetchForecastSeries(eventId?: string): Promise<ForecastPoint[]> {
  return resolve('forecast-series', demoForecastSeries, () => liveForecast(eventId))
}
