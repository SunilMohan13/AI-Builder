import { mockRiskAreas } from '../data/mockPopulation'
import type { PopulationRiskArea } from '../types'
import { liveRiskAreas } from '../api/live'
import { isDemo } from './dataMode'
import { resolve } from './resolve'

const delay = (ms = 80) => new Promise((r) => setTimeout(r, ms))

async function demoRiskAreas(): Promise<PopulationRiskArea[]> {
  await delay()
  return mockRiskAreas
}

export async function fetchRiskAreas(): Promise<PopulationRiskArea[]> {
  return resolve('risk-areas', demoRiskAreas, liveRiskAreas)
}

/**
 * Total population across the ranked exposure areas.
 *
 * Previously demo-only: the grid-feature path exposes population *density*
 * per km2, and summing that would have produced a meaningless figure under
 * the label "people at risk". `GET /api/v1/risk/areas` supplies a real
 * per-cell headcount from the population reference layer, so the KPI is now
 * answerable in live mode too.
 *
 * The caveat moves rather than disappears: the reference layer ships as a
 * fixture licensed `replace-before-production`, so the number is structurally
 * correct but not operationally sourced until a licensed WorldPop or Census
 * extract replaces it. `usePopulationProvenance` surfaces that.
 */
export async function fetchTotalExposure(): Promise<number | null> {
  if (isDemo()) {
    await delay(50)
    return mockRiskAreas.reduce((sum, a) => sum + a.population, 0)
  }
  const areas = await fetchRiskAreas()
  if (areas.length === 0) return null
  return areas.reduce((sum, a) => sum + a.population, 0)
}
