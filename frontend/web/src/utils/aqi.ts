export type PollutionBand =
  | 'good'
  | 'satisfactory'
  | 'moderate'
  | 'poor'
  | 'very-poor'
  | 'severe'

export type Rgba = [number, number, number, number]

/** CPCB National AQI breakpoints for PM2.5 (µg/m³). One table for labels and the legend. */
export const PM25_BANDS: { id: PollutionBand; label: string; max: number | null; sample: number }[] =
  [
    { id: 'good', label: 'Good', max: 30, sample: 18 },
    { id: 'satisfactory', label: 'Satisfactory', max: 60, sample: 45 },
    { id: 'moderate', label: 'Moderate', max: 90, sample: 75 },
    { id: 'poor', label: 'Poor', max: 120, sample: 105 },
    { id: 'very-poor', label: 'Very Poor', max: 250, sample: 180 },
    { id: 'severe', label: 'Severe', max: null, sample: 300 },
  ]

export function getPollutionBand(pm25: number): PollutionBand {
  const band = PM25_BANDS.find((entry) => entry.max != null && pm25 <= entry.max)
  return band?.id ?? 'severe'
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

/** CPCB sub-index. Concentration breakpoints map onto AQI 0–50, 51–100, 101–200, 201–300, 301–400, 401–500. */
export function getAqiFromPm25(pm25: number): number {
  const value = Math.max(0, pm25)
  const segments: [number, number, number, number][] = [
    [0, 30, 0, 50],
    [31, 60, 51, 100],
    [61, 90, 101, 200],
    [91, 120, 201, 300],
    [121, 250, 301, 400],
    [251, 380, 401, 500],
  ]
  const segment =
    segments.find(([, high]) => value <= high) ?? segments[segments.length - 1]
  const [low, high, indexLow, indexHigh] = segment
  const span = high - low || 1
  const index = ((indexHigh - indexLow) / span) * (value - low) + indexLow
  return Math.round(Math.min(500, Math.max(0, index)))
}

export function getBandLabel(pm25: number): string {
  const id = getPollutionBand(pm25)
  return PM25_BANDS.find((band) => band.id === id)?.label ?? 'Severe'
}

export function getRiskFromPm25(pm25: number): 'LOW' | 'MEDIUM' | 'HIGH' | 'SEVERE' {
  if (pm25 <= 60) return 'LOW'
  if (pm25 <= 90) return 'MEDIUM'
  if (pm25 <= 120) return 'HIGH'
  return 'SEVERE'
}
