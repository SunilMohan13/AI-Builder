import type { ForecastPoint } from '../types'

const base = '2026-09-08T08:30:00Z'

export const mockForecast: ForecastPoint[] = [
  { hour: 0, timestamp: base, pm25: 185, confidenceLow: 170, confidenceHigh: 200 },
  { hour: 1, timestamp: '2026-09-08T09:30:00Z', pm25: 205, confidenceLow: 188, confidenceHigh: 222 },
  { hour: 3, timestamp: '2026-09-08T11:30:00Z', pm25: 230, confidenceLow: 210, confidenceHigh: 250 },
  { hour: 6, timestamp: '2026-09-08T14:30:00Z', pm25: 260, confidenceLow: 235, confidenceHigh: 285 },
  { hour: 12, timestamp: '2026-09-08T20:30:00Z', pm25: 245, confidenceLow: 220, confidenceHigh: 270 },
  { hour: 24, timestamp: '2026-09-09T08:30:00Z', pm25: 198, confidenceLow: 175, confidenceHigh: 221 },
  { hour: 48, timestamp: '2026-09-10T08:30:00Z', pm25: 162, confidenceLow: 140, confidenceHigh: 184 },
]

/** Observed PM2.5 leading up to detection, used for the observed/predicted split. */
export const mockObservedHistory: { hour: number; pm25: number }[] = [
  { hour: -6, pm25: 92 },
  { hour: -5, pm25: 98 },
  { hour: -4, pm25: 109 },
  { hour: -3, pm25: 124 },
  { hour: -2, pm25: 148 },
  { hour: -1, pm25: 167 },
  { hour: 0, pm25: 185 },
]

export function getForecastSeries(): ForecastPoint[] {
  const hours = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
  const values = [185, 192, 198, 205, 212, 218, 230, 238, 246, 255, 260, 252, 245]
  const persistence = values[0]
  return hours.map((h, i) => ({
    hour: h,
    timestamp: new Date(new Date(base).getTime() + h * 3600000).toISOString(),
    pm25: values[i],
    confidenceLow: values[i] - 15,
    confidenceHigh: values[i] + 18,
    baselinePm25: persistence,
  }))
}
