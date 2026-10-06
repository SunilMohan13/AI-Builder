import type { WindObservation } from '../types'
import {
  CORRIDOR_BOUNDS,
  TRANSPORT_BEARING_DEG,
  WIND_FROM_DEG,
  WIND_SPEED_MS,
} from '../utils/geo'

/**
 * Uniform northwesterly flow down the corridor. `u`/`v` are the east/north
 * components of the direction the air is moving toward, so the rendered
 * arrows agree with the plume transport used by the forecast.
 */
export function generateWindGrid(): WindObservation[] {
  const theta = (TRANSPORT_BEARING_DEG * Math.PI) / 180
  const u = WIND_SPEED_MS * Math.sin(theta)
  const v = WIND_SPEED_MS * Math.cos(theta)

  const points: WindObservation[] = []
  for (let lat = CORRIDOR_BOUNDS.south; lat <= CORRIDOR_BOUNDS.north; lat += 0.3) {
    for (let lon = CORRIDOR_BOUNDS.west; lon <= CORRIDOR_BOUNDS.east; lon += 0.3) {
      points.push({
        lat,
        lon,
        u,
        v,
        speed: WIND_SPEED_MS,
        direction: WIND_FROM_DEG,
      })
    }
  }
  return points
}

export const defaultWind = generateWindGrid()
