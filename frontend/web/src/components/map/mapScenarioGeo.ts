import { plumeKernel, PUNJAB_FIRE_CENTER, TRANSPORT_BEARING_DEG } from '../../utils/geo'
import type { GridCell } from '../../types'

/** Approximate Delhi NCR GRAP advisory footprint (mock). */
export const GRAP_NCR_RING: [number, number][] = [
  [76.75, 28.35],
  [77.55, 28.35],
  [77.65, 28.75],
  [77.45, 29.05],
  [76.85, 29.0],
  [76.65, 28.7],
  [76.75, 28.35],
]

export function pointInRing(lon: number, lat: number, ring: [number, number][]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    const intersect =
      yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi + 1e-12) + xi
    if (intersect) inside = !inside
  }
  return inside
}

export function grapPlumeIntersection(cells: GridCell[], minPlume = 12): boolean {
  return cells.some(
    (c) => c.plume >= minPlume && pointInRing(c.lon, c.lat, GRAP_NCR_RING),
  )
}

/** Population-weighted corridor ribbon along the active transport bearing. */
export function buildExposureRibbonPath(
  cells: GridCell[],
  bearingDeg: number,
): [number, number][] {
  const samples: { lon: number; lat: number; weight: number }[] = []
  for (const c of cells) {
    if (c.plume < 8) continue
    samples.push({ lon: c.lon, lat: c.lat, weight: c.population * (c.plume / 100) })
  }
  if (samples.length < 4) {
    return [
      [PUNJAB_FIRE_CENTER.lon, PUNJAB_FIRE_CENTER.lat],
      [76.5, 29.8],
      [77.0, 29.2],
      [77.21, 28.61],
    ]
  }
  const theta = (bearingDeg * Math.PI) / 180
  samples.sort((a, b) => {
    const da = a.lon * Math.sin(theta) + a.lat * Math.cos(theta)
    const db = b.lon * Math.sin(theta) + b.lat * Math.cos(theta)
    return da - db
  })
  const step = Math.max(1, Math.floor(samples.length / 24))
  const path: [number, number][] = []
  for (let i = 0; i < samples.length; i += step) {
    path.push([samples[i].lon, samples[i].lat])
  }
  const last = samples[samples.length - 1]
  path.push([last.lon, last.lat])
  return path
}

export function buildBaselinePlumeCells(cells: GridCell[], bearingDeg: number): GridCell[] {
  return cells.map((c) => {
    const plume = plumeKernel(
      c.lat,
      c.lon,
      PUNJAB_FIRE_CENTER.lat,
      PUNJAB_FIRE_CENTER.lon,
      bearingDeg,
      150,
      0,
    )
    return { ...c, plume }
  })
}

export const DEFAULT_TRANSPORT_BEARING = TRANSPORT_BEARING_DEG
