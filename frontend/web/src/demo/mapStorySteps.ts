export interface MapStoryStep {
  hour: number
  caption: string
  layers?: Partial<{
    pollution: boolean
    fires: boolean
    wind: boolean
    forecast: boolean
    population: boolean
  }>
}

export const MAP_STORY_STEPS: MapStoryStep[] = [
  {
    hour: 0,
    caption: 'FIRMS · thermal anomalies detected · Punjab corridor',
    layers: { fires: true, pollution: true },
  },
  {
    hour: 1,
    caption: 'CPCB · PM2.5 anomaly across downwind stations',
    layers: { pollution: true, fires: true },
  },
  {
    hour: 2,
    caption: 'IMD · wind alignment confirms transport toward NCR',
    layers: { wind: true, fires: true, pollution: true },
  },
  {
    hour: 4,
    caption: 'PREDICTED · plume advection along corridor',
    layers: { forecast: true, wind: true, pollution: true },
  },
  {
    hour: 6,
    caption: 'GRAP watch · plume intersects Delhi NCR footprint',
    layers: { forecast: true, population: true },
  },
  {
    hour: 8,
    caption: 'Exposure ribbon · 2.4M in projected path · RECOMMENDED actions',
    layers: { forecast: true, population: true },
  },
]

export const MAP_STORY_STEP_MS = 2800
