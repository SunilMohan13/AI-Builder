import { getGridAt, type GridBounds } from '../data/mockGrid'
import { getFiresAt } from '../data/mockFires'
import { defaultWind } from '../data/mockWind'
import { mockIndustries } from '../data/mockPopulation'
import type { GridCell, FireObservation, WindObservation, IndustrySite } from '../types'
import { liveAirQuality, liveFires, liveIndustries, liveWeather } from '../api/live'
import { ApiError } from '../api/client'
import { resolve } from './resolve'

const delay = (ms = 100) => new Promise((r) => setTimeout(r, ms))

/**
 * Observed grid cells at offset 0, forecast cells beyond it.
 *
 * Demo scrubs the scripted episode through `getGridAt`. Live requests the
 * advection forecast for the nearest published horizon, so the scrubber
 * moves real data in both modes. (It previously ignored the offset in Live
 * and redrew the present under a future label; this comment claimed the
 * control was disabled, which it never was.)
 */
export async function fetchAirQuality(
  hourOffset = 0,
  intensity = 1,
  bounds?: GridBounds,
  transportBearingDeg?: number,
): Promise<GridCell[]> {
  return resolve(
    'air-quality',
    async () => {
      await delay()
      return getGridAt(hourOffset, intensity, bounds, transportBearingDeg)
    },
    () => liveAirQuality(hourOffset),
  )
}

export async function fetchFires(hourOffset = 0, intensity = 1): Promise<FireObservation[]> {
  return resolve(
    'fires',
    async () => {
      await delay(80)
      return getFiresAt(hourOffset, intensity)
    },
    async () => {
      if (hourOffset !== 0) {
        throw new ApiError(
          'live fire observations are the latest detections; they are not time-scrubbed',
          404,
          '/api/v1/map/fire',
        )
      }
      return liveFires()
    },
  )
}

export async function fetchWeather(): Promise<WindObservation[]> {
  return resolve(
    'weather',
    async () => {
      await delay(60)
      return defaultWind
    },
    liveWeather,
  )
}

/**
 * Industrial sites.
 *
 * Live via `GET /api/v1/map/industry`, which serves the replayed
 * Industry/OCEMS footprints. Those are product footprints rather than named
 * point assets, so live entries carry a generic label where the demo has a
 * refinery or kiln name — the adapter does not invent one.
 */
export async function fetchIndustries(): Promise<IndustrySite[]> {
  return resolve(
    'industry',
    async () => {
      await delay(40)
      return mockIndustries
    },
    liveIndustries,
  )
}
