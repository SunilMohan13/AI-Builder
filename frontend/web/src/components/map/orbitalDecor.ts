import { PUNJAB_FIRE_CENTER } from '../../utils/geo'
import { hashNoise } from '../../utils/seededRandom'

export interface OrbitalPoint {
  lon: number
  lat: number
  phase: number
  band: number
}

/** Decorative shell of points — reads as orbital traffic, not real TLE data. */
export function buildOrbitalShell(count: number, time: number): OrbitalPoint[] {
  const pts: OrbitalPoint[] = []
  for (let i = 0; i < count; i++) {
    const band = i % 9
    const phase = (i / count) * Math.PI * 2
    const drift = time * (0.025 + band * 0.006)
    const ring = 28 + (band % 4) * 14 + hashNoise(i, 2) * 18
    const hemisphere = band % 2 === 0 ? 1 : -1
    const lat =
      hemisphere * ring + Math.sin(phase * 3.7 + band) * 6 + (hashNoise(i, 5) - 0.5) * 8
    const lon = ((phase + drift) * 57.3 + hashNoise(i, 3) * 22) % 360 - 180
    pts.push({ lon, lat, phase, band })
  }
  return pts
}

function arcPoints(
  from: { lon: number; lat: number },
  to: { lon: number; lat: number },
  segments = 48,
): [number, number][] {
  const path: [number, number][] = []
  for (let i = 0; i <= segments; i++) {
    const t = i / segments
    const lon = from.lon + (to.lon - from.lon) * t
    const mid = Math.sin(t * Math.PI)
    const lat = from.lat + (to.lat - from.lat) * t + mid * 8
    path.push([lon, lat])
  }
  return path
}

const DELHI = { lon: 77.21, lat: 28.61 }

export function buildCorridorArcs(): { path: [number, number][]; id: string }[] {
  const hubs = [
    { lon: 75.85, lat: 30.9, id: 'ludhiana' },
    { lon: 76.78, lat: 30.73, id: 'patiala' },
    { lon: DELHI.lon, lat: DELHI.lat, id: 'delhi' },
    { lon: 76.96, lat: 29.39, id: 'karnal' },
  ]
  const paths: { path: [number, number][]; id: string }[] = [
    {
      id: 'plume-axis',
      path: arcPoints(PUNJAB_FIRE_CENTER, DELHI, 64),
    },
  ]
  for (const hub of hubs) {
    paths.push({
      id: `link-${hub.id}`,
      path: arcPoints(PUNJAB_FIRE_CENTER, { lon: hub.lon, lat: hub.lat }, 40),
    })
  }
  return paths
}
