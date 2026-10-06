import type { FireObservation } from '../types'
import { createSeededRandom } from '../utils/seededRandom'
import { PUNJAB_FIRE_CENTER } from '../utils/geo'

function generateFires(count: number, spread: number): FireObservation[] {
  const rand = createSeededRandom(99)
  const base = '2026-09-08T08:32:00Z'
  const fires: FireObservation[] = []

  for (let i = 0; i < count; i++) {
    const angle = rand() * Math.PI * 2
    const dist = rand() * spread
    fires.push({
      id: `fire_${i}`,
      lat: PUNJAB_FIRE_CENTER.lat + Math.cos(angle) * dist,
      lon: PUNJAB_FIRE_CENTER.lon + Math.sin(angle) * dist,
      frp: 20 + rand() * 120,
      confidence: 0.7 + rand() * 0.28,
      timestamp: base,
    })
  }
  return fires
}

export function getFiresAt(hourOffset: number, demoIntensity = 1): FireObservation[] {
  const count = Math.round(42 * demoIntensity * (1 + hourOffset * 0.05))
  const spread = 0.15 + hourOffset * 0.02
  return generateFires(Math.min(count, 60), spread)
}

export const defaultFires = getFiresAt(0, 1)
