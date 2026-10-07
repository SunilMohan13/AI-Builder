/**
 * Map colour for a served hourly PM2.5 value.
 *
 * This is a neutral display ramp, not an air-quality standard. Official bands
 * (CPCB, NEA, NSW) average over hours the map does not have, so a cell shows
 * its band only when the API sent `aqi_band`; otherwise the band reads "—"
 * with the API's reason. The stops below place colours and claim nothing.
 */

export const RAMP_STOPS_UGM3 = [0, 25, 50, 100, 150, 250] as const

const RAMP: [number, number, number][] = [
  [56, 189, 248],
  [45, 212, 191],
  [163, 230, 53],
  [250, 204, 21],
  [249, 115, 22],
  [190, 24, 93],
]

export function rampColour(value: number, alpha = 190): [number, number, number, number] {
  let i = RAMP_STOPS_UGM3.length - 1
  while (i > 0 && value < RAMP_STOPS_UGM3[i]) i -= 1
  if (i === RAMP_STOPS_UGM3.length - 1) return [...RAMP[i], alpha]
  const lo = RAMP_STOPS_UGM3[i]
  const hi = RAMP_STOPS_UGM3[i + 1]
  const t = Math.min(1, Math.max(0, (value - lo) / (hi - lo)))
  const mix = RAMP[i].map((c, k) => Math.round(c + (RAMP[i + 1][k] - c) * t)) as [
    number,
    number,
    number,
  ]
  return [...mix, alpha]
}

export function rampCss(value: number): string {
  const [r, g, b] = rampColour(value)
  return `rgb(${r} ${g} ${b})`
}
