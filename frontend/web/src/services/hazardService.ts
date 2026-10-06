/**
 * 24-hour hazard and peak forecasts, plus the model catalog.
 *
 * These have no demo counterpart in `src/data`: they are new surfaces added
 * with the hazard work, so in demo mode they are derived from the demo grid
 * rather than left blank — the narrative needs a hazard layer to talk about.
 * Live reads the real endpoints, which currently answer from a deterministic
 * persistence rule and say so.
 */

import type { HazardCell, ModelCatalogEntry, PeakForecastCell } from '../types'
import { getGridAt } from '../data/mockGrid'
import { liveHazard, liveModels, livePeak, type LiveHazard, type LivePeak } from '../api/live'
import { resolve } from './resolve'

/** CPCB "Very Poor" breakpoint — the single reconciled hazard threshold. */
export const HAZARD_THRESHOLD = 121

const delay = (ms = 80) => new Promise((r) => setTimeout(r, ms))

/** Same linear ramp the backend baseline uses, so demo and live agree in shape. */
function hazardScoreFor(pm25: number): number {
  return Math.max(0, Math.min(1, (pm25 - 30) / (HAZARD_THRESHOLD - 30)))
}

async function demoHazard(): Promise<LiveHazard> {
  await delay()
  const cells = getGridAt(0, 1)
    .filter((c) => c.pm25 > 60)
    .slice(0, 400)
    .map<HazardCell>((c) => ({
      gridId: c.gridId,
      lat: c.lat,
      lon: c.lon,
      timestamp: new Date().toISOString(),
      hazardScore: hazardScoreFor(c.pm25),
      thresholdUgm3: HAZARD_THRESHOLD,
      horizonHours: 24,
      calibrated: false,
      degraded: true,
      modelVersion: 'persistence-hazard-0.1',
      observedPm25: c.pm25,
    }))
    .sort((a, b) => b.hazardScore - a.hazardScore)
  return {
    cells,
    provenance: {
      model_name: 'pm25_hazard_24h',
      model_version: 'persistence-hazard-0.1',
      degraded: true,
      reason:
        'Demo narrative. Hazard is a persistence ramp over the scripted grid, not a model output.',
    },
  }
}

async function demoPeak(): Promise<LivePeak> {
  await delay()
  const cells = getGridAt(0, 1)
    .filter((c) => c.pm25 > 60)
    .slice(0, 400)
    .map<PeakForecastCell>((c) => {
      // The demo episode builds over the next day, so the scripted peak sits
      // above the current reading rather than equalling it.
      const peak = Math.round(c.pm25 * 1.25)
      return {
        gridId: c.gridId,
        lat: c.lat,
        lon: c.lon,
        timestamp: new Date().toISOString(),
        peakPm25: peak,
        horizonHours: 24,
        exceedsThreshold: peak >= HAZARD_THRESHOLD,
        thresholdUgm3: HAZARD_THRESHOLD,
        degraded: true,
        modelVersion: 'persistence-peak-0.1',
        observedPm25: c.pm25,
      }
    })
    .sort((a, b) => b.peakPm25 - a.peakPm25)
  return {
    cells,
    provenance: {
      model_name: 'pm25_peak_24h',
      model_version: 'persistence-peak-0.1',
      degraded: true,
      reason: 'Demo narrative. Peak is a scripted projection, not a model output.',
    },
  }
}

export async function fetchHazard(): Promise<LiveHazard> {
  return resolve('hazard', demoHazard, liveHazard)
}

export async function fetchPeakForecast(): Promise<LivePeak> {
  return resolve('peak', demoPeak, livePeak)
}

/**
 * The model registry.
 *
 * Demo mode reports the same six families the backend trains, with the
 * stages measured on the 2026-09-22 live 90-day run, so the demo tells the
 * truth about what is and is not serving rather than showing everything
 * green.
 */
const DEMO_MODELS: ModelCatalogEntry[] = [
  {
    modelId: 'baseline-idw-0.1',
    modelName: 'pm25_estimator',
    version: 'baseline-idw-0.1',
    stage: 'PRODUCTION',
    runtimeRole: 'PRIMARY_BASELINE',
    algorithm: 'deterministic: inverse-distance-weighted interpolation',
    artifactAvailable: false,
    gateFailures: [],
    notes: 'Deterministic baseline. No trained artifact; the fallback a champion must beat.',
  },
  {
    modelId: 'hgb-pm25',
    modelName: 'pm25_estimator',
    version: 'hgb-pm25-202609221644',
    stage: 'PRODUCTION',
    runtimeRole: 'PRIMARY_MODEL',
    algorithm: 'sklearn.HistGradientBoostingRegressor',
    artifactAvailable: true,
    gateFailures: [],
    notes: 'Temporal skill +0.409 vs persistence, R² 0.975.',
  },
  {
    modelId: 'hgb-source',
    modelName: 'source_likelihood',
    version: 'hgb-source-202609221644',
    stage: 'PRODUCTION',
    runtimeRole: 'PRIMARY_MODEL',
    algorithm: 'sklearn.HistGradientBoostingClassifier',
    artifactAvailable: true,
    gateFailures: [],
    notes: 'Macro F1 0.592. Weak labels — a probabilistic hint, never proven causality.',
  },
  {
    modelId: 'hgb-anomaly',
    modelName: 'anomaly_detector',
    version: 'hgb-anomaly-202609221644',
    stage: 'VALIDATION',
    runtimeRole: 'REGISTERED_ONLY',
    algorithm: 'sklearn.HistGradientBoostingRegressor (residual over baseline)',
    artifactAvailable: true,
    gateFailures: ['detection F1 is 0.145 against the CPCB exceedance label (must reach 0.3)'],
    notes: 'Withheld by the promotion gate.',
  },
  {
    modelId: 'hgb-forecast',
    modelName: 'propagation_forecast',
    version: 'hgb-forecast-202609221644',
    stage: 'VALIDATION',
    runtimeRole: 'REGISTERED_ONLY',
    algorithm: 'sklearn.HistGradientBoostingRegressor (residual over persistence)',
    artifactAvailable: true,
    gateFailures: ['horizons at or below persistence skill: 24h skill -0.1059'],
    notes: 'Withheld by the promotion gate.',
  },
  {
    modelId: 'hgb-peak',
    modelName: 'pm25_peak_24h',
    version: 'hgb-peak-202609221645',
    stage: 'VALIDATION',
    runtimeRole: 'REGISTERED_ONLY',
    algorithm: 'sklearn.HistGradientBoostingRegressor (forward 24h maximum)',
    artifactAvailable: true,
    gateFailures: [
      'extreme recall is 0.049 (must reach 0.7); episodes would be missed',
      'extreme bias is -41.4 ug/m3 (must not fall below -25.0)',
    ],
    notes: 'Withheld. Squared-error regression under-predicts episodes.',
  },
  {
    modelId: 'hgb-hazard',
    modelName: 'pm25_hazard_24h',
    version: 'hgb-hazard-202609221645',
    stage: 'VALIDATION',
    runtimeRole: 'REGISTERED_ONLY',
    algorithm: 'sklearn.HistGradientBoostingClassifier (P(peak >= 121 within 24h))',
    artifactAvailable: true,
    gateFailures: [
      'PR-AUC 0.3344 does not beat the current-pm25 baseline 0.3795 by 0.05',
    ],
    notes: 'Withheld. Reading the current concentration ranks hazard as well as the model does.',
  },
]

export async function fetchModelCatalog(): Promise<ModelCatalogEntry[]> {
  return resolve(
    'models',
    async () => {
      await delay()
      return DEMO_MODELS
    },
    liveModels,
  )
}
