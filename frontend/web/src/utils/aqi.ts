export type PollutionBand = 'good' | 'moderate' | 'poor' | 'very-poor' | 'severe'

export type Rgba = [number, number, number, number]

export function getPollutionBand(pm25: number): PollutionBand {
  if (pm25 <= 30) return 'good'
  if (pm25 <= 60) return 'moderate'
  if (pm25 <= 90) return 'poor'
  if (pm25 <= 120) return 'very-poor'
  return 'severe'
}

/**
 * Continuous ramp keyed to the CPCB bands. Clean air is almost fully
 * transparent so the basemap reads through it and only real pollution draws
 * the eye; discrete opaque bands turned the whole corridor into a flat slab.
 */
const RAMP: { stop: number; color: [number, number, number]; alpha: number }[] = [
  { stop: 0, color: [16, 78, 92], alpha: 0 },
  { stop: 25, color: [34, 197, 160], alpha: 24 },
  { stop: 45, color: [163, 210, 92], alpha: 60 },
  { stop: 65, color: [250, 204, 21], alpha: 96 },
  { stop: 95, color: [251, 146, 60], alpha: 140 },
  { stop: 130, color: [239, 68, 68], alpha: 180 },
  { stop: 200, color: [190, 24, 93], alpha: 215 },
  { stop: 300, color: [136, 19, 132], alpha: 235 },
]

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t
}

export function getPollutionColor(pm25: number, fade = 1): Rgba {
  const v = Math.max(0, pm25)
  let lo = RAMP[0]
  let hi = RAMP[RAMP.length - 1]

  for (let i = 0; i < RAMP.length - 1; i++) {
    if (v >= RAMP[i].stop && v <= RAMP[i + 1].stop) {
      lo = RAMP[i]
      hi = RAMP[i + 1]
      break
    }
  }

  const span = hi.stop - lo.stop || 1
  const t = Math.min(Math.max((v - lo.stop) / span, 0), 1)

  return [
    Math.round(lerp(lo.color[0], hi.color[0], t)),
    Math.round(lerp(lo.color[1], hi.color[1], t)),
    Math.round(lerp(lo.color[2], hi.color[2], t)),
    Math.round(lerp(lo.alpha, hi.alpha, t) * fade),
  ]
}

/** Opaque swatch for legends and chips, where transparency would read as washed out. */
export function getPollutionSwatch(pm25: number): string {
  const [r, g, b] = getPollutionColor(pm25)
  return `rgb(${r}, ${g}, ${b})`
}

/**
 * Warm smoke tint used by the plume overlay. Deliberately distinct from the
 * pollution ramp so transported smoke reads as its own phenomenon.
 */
export function getSmokeColor(plume: number, fade = 1): Rgba {
  const t = Math.min(plume / 110, 1)
  if (t <= 0.02) return [0, 0, 0, 0]
  const eased = t ** 0.85
  return [
    Math.round(lerp(214, 252, eased)),
    Math.round(lerp(220, 186, eased)),
    Math.round(lerp(232, 146, eased)),
    Math.round(lerp(6, 88, eased) * fade),
  ]
}

export function getAqiFromPm25(pm25: number): number {
  if (pm25 <= 30) return Math.round((pm25 / 30) * 50)
  if (pm25 <= 60) return Math.round(50 + ((pm25 - 30) / 30) * 50)
  if (pm25 <= 90) return Math.round(100 + ((pm25 - 60) / 30) * 50)
  if (pm25 <= 120) return Math.round(150 + ((pm25 - 90) / 30) * 100)
  return Math.round(250 + Math.min((pm25 - 120) / 2, 50))
}

export function getBandLabel(pm25: number): string {
  const band = getPollutionBand(pm25)
  return band.replace('-', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function getRiskFromPm25(pm25: number): 'LOW' | 'MEDIUM' | 'HIGH' | 'SEVERE' {
  if (pm25 <= 60) return 'LOW'
  if (pm25 <= 90) return 'MEDIUM'
  if (pm25 <= 120) return 'HIGH'
  return 'SEVERE'
}
