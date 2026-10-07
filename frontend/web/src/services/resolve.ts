/**
 * The Demo/Live branch, in one place.
 *
 * Demo answers from the recording of the real API (`src/data/regions`).
 * Live answers only from the AeroPulse API. A failed Live call is recorded
 * for the banner and thrown — it never falls back to the recording.
 */

import { ApiError } from '../api/client'
import { httpTransport, recordingTransport, type Transport } from '../api/transport'
import { demoCatalog, loadRecording } from '../data/regions'
import { clearFallback, isDemo, recordFallback } from './dataMode'

/** The transport for the current mode, scoped to one region's recording in Demo. */
export async function transportFor(regionId: string | null): Promise<Transport> {
  if (!isDemo()) return httpTransport
  const recording = regionId ? loadRecording(regionId) : null
  if (recording === null) return recordingTransport(demoCatalog.responses)
  return recordingTransport({ ...demoCatalog.responses, ...(await recording).responses })
}

/**
 * Run one API call on the current mode's transport.
 *
 * @param endpoint Stable label for the Live-failure banner, e.g. `incidents`.
 * @param regionId Region whose recording answers in Demo.
 * @param call The request, written once for both modes.
 */
export async function resolve<T>(
  endpoint: string,
  regionId: string | null,
  call: (transport: Transport) => Promise<T>,
): Promise<T> {
  const transport = await transportFor(regionId)
  if (transport.kind === 'demo') return call(transport)
  try {
    const result = await call(transport)
    clearFallback(endpoint)
    return result
  } catch (error) {
    recordFallback(endpoint, error instanceof ApiError ? error.reason : 'unexpected error')
    throw error
  }
}
