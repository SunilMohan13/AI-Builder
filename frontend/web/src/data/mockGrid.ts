import type { GridCell } from '../types'
import { getAqiFromPm25, getRiskFromPm25 } from '../utils/aqi'
import {
  CORRIDOR_BOUNDS,
  KM1_DEG,
  plumeKernel,
  PUNJAB_FIRE_CENTER,
  TRANSPORT_BEARING_DEG,
} from '../utils/geo'
import { hashNoise } from '../utils/seededRandom'

export interface GridBounds {
  west: number
  east: number
  south: number
  north: number
}

/**
 * Keeps the layer inside a GPU- and memory-friendly budget while zoomed out.
 * Each cached snapshot costs roughly this many cells' worth of objects, and
 * several snapshots can be live at once, so this ceiling is deliberately
 * conservative — 70k crashed the renderer during a timeline drag.
 */
const MAX_CELLS = 34_000

/** Release ages sampled to approximate a continuously burning source. */
const RELEASE_FRACTIONS = [0, 0.25, 0.5, 0.75, 1]

const URBAN_CENTRES: { lat: number; lon: number; weight: number; sigma: number }[] = [
  { lat: 28.61, lon: 77.21, weight: 74, sigma: 0.055 },
  { lat: 28.67, lon: 77.45, weight: 42, sigma: 0.03 },
  { lat: 29.39, lon: 76.97, weight: 30, sigma: 0.022 },
  { lat: 30.9, lon: 75.85, weight: 34, sigma: 0.028 },
  { lat: 30.34, lon: 76.38, weight: 22, sigma: 0.02 },
]

/** Clean rural background. Kept low so unaffected land reads as clear air. */
const RURAL_BASELINE = 14

/**
 * Chooses the coarsest step that keeps the viewport under the cell budget.
 * Returns the native 1 km resolution whenever the view is tight enough to
 * render it honestly.
 */
export function resolveStep(bounds: GridBounds): number {
  const spanLat = bounds.north - bounds.south
  const spanLon = bounds.east - bounds.west
  for (const multiple of [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 24]) {
    const step = KM1_DEG * multiple
    if ((spanLat / step) * (spanLon / step) <= MAX_CELLS) return step
  }
  return KM1_DEG * 24
}

export function stepToKm(step: number): number {
  return step / KM1_DEG
}

function urbanBoost(lat: number, lon: number): number {
  let total = 0
  for (const c of URBAN_CENTRES) {
    const d2 = (lat - c.lat) ** 2 + (lon - c.lon) ** 2
    total += c.weight * Math.exp(-d2 / c.sigma)
  }
  return total
}

function buildCell(
  i: number,
  j: number,
  step: number,
  hourOffset: number,
  intensity: number,
  transportBearingDeg: number,
): GridCell {
  const lat = i * step
  const lon = j * step

  const noise = hashNoise(i, j)
  const smooth =
    (hashNoise(Math.floor(i / 4), Math.floor(j / 4)) +
      hashNoise(Math.floor(i / 12), Math.floor(j / 12))) /
    2

  const density = urbanBoost(lat, lon)
  const base = RURAL_BASELINE + density + smooth * 10 + noise * 5
  // Burning is continuous, so superpose puffs released across the elapsed
  // window. A single puff would leave the source cold once it drifted away.
  const elapsed = Math.max(0, hourOffset)
  let plume = 0
  for (const frac of RELEASE_FRACTIONS) {
    plume = Math.max(
      plume,
      plumeKernel(
        lat,
        lon,
        PUNJAB_FIRE_CENTER.lat,
        PUNJAB_FIRE_CENTER.lon,
        transportBearingDeg,
        150 * intensity,
        elapsed * frac,
      ),
    )
  }

  const pm25 = Math.round(base + plume)
  const population = Math.round(400 + density * 420 + noise * 2200)

  return {
    gridId: `grid_${i}_${j}`,
    lat,
    lon,
    pm25,
    pm10: Math.round(pm25 * 1.3),
    no2: Math.round(18 + density * 0.6 + noise * 34),
    aqi: getAqiFromPm25(pm25),
    population,
    risk: getRiskFromPm25(pm25),
    stepDeg: step,
    plume,
    edgeFade: edgeFade(lat, lon),
  }
}

/**
 * Softens the layer's outer boundary. Without it the generated extent renders
 * as a hard-edged rectangle floating over the basemap.
 */
function edgeFade(lat: number, lon: number): number {
  const margin = 1.1
  const dLon = Math.min(lon - CORRIDOR_BOUNDS.west, CORRIDOR_BOUNDS.east - lon)
  const dLat = Math.min(lat - CORRIDOR_BOUNDS.south, CORRIDOR_BOUNDS.north - lat)
  const t = Math.min(dLon, dLat) / margin
  return Math.min(Math.max(t, 0), 1) ** 0.8
}

/**
 * Generates only the cells inside the requested bounds. The field is a pure
 * function of position, so panning never changes a cell's values.
 */
export function getGridAt(
  hourOffset = 0,
  intensity = 1,
  bounds: GridBounds = CORRIDOR_BOUNDS,
  transportBearingDeg = TRANSPORT_BEARING_DEG,
): GridCell[] {
  const west = Math.max(bounds.west, CORRIDOR_BOUNDS.west)
  const east = Math.min(bounds.east, CORRIDOR_BOUNDS.east)
  const south = Math.max(bounds.south, CORRIDOR_BOUNDS.south)
  const north = Math.min(bounds.north, CORRIDOR_BOUNDS.north)
  if (east <= west || north <= south) return []

  const step = resolveStep({ west, east, south, north })
  const cells: GridCell[] = []

  const iStart = Math.floor(south / step)
  const iEnd = Math.ceil(north / step)
  const jStart = Math.floor(west / step)
  const jEnd = Math.ceil(east / step)

  for (let i = iStart; i <= iEnd; i++) {
    for (let j = jStart; j <= jEnd; j++) {
      cells.push(buildCell(i, j, step, hourOffset, intensity, transportBearingDeg))
    }
  }
  return cells
}
