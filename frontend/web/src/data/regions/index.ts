/**
 * The Demo recording: real API responses over a real cycle, written by
 * `scripts/generate_demo_recording.py`. Do not edit the JSON by hand —
 * regenerate it, and `tests/golden/test_demo_recording.py` keeps it current.
 *
 * The catalog (region list) is small and loads with the app. Each region's
 * recording is its own chunk, fetched when that region is opened.
 */

import catalog from './catalog.json'
import type { RecordedResponse } from '../../api/transport'

export interface Recording {
  schema: string
  region_id: string
  clock: string
  cycle_time: string | null
  has_scenario: boolean
  scenario_reason: string | null
  inputs: string
  suggested_questions: string[]
  /** Recorded once per incident, with every suggested question, under that incident. */
  incident_question: string
  responses: Record<string, RecordedResponse>
}

export interface RecordingCatalog {
  schema: string
  clock: string
  inputs: string
  cycled_regions: string[]
  recorded_regions: string[]
  responses: Record<string, RecordedResponse>
}

export const demoCatalog = catalog as RecordingCatalog

const loaders = import.meta.glob<Recording>('./*/recording.json', { import: 'default' })

const cache = new Map<string, Promise<Recording>>()

/** The recording for one region, or `null` when none was generated. */
export function loadRecording(regionId: string): Promise<Recording> | null {
  const load = loaders[`./${regionId}/recording.json`]
  if (load === undefined) return null
  let pending = cache.get(regionId)
  if (pending === undefined) {
    pending = load()
    cache.set(regionId, pending)
  }
  return pending
}
