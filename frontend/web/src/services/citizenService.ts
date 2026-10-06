import { mockCitizenReports } from '../data/mockCitizenReports'
import type { CitizenReport } from '../types'
import {
  liveAttachCitizenPhoto,
  liveCitizenReports,
  liveCreateCitizenReport,
  toUiCitizenReport,
} from '../api/live'
import { isDemo } from './dataMode'
import { resolve } from './resolve'

const delay = (ms = 80) => new Promise((r) => setTimeout(r, ms))

const KEYWORDS = ['smoke', 'fire', 'dust', 'haze', 'clear'] as const

/** Reports submitted in this tab while Demo is on. Live never reads this list. */
const demoSessionReports: CitizenReport[] = []

export const CITIZEN_LIVE_CAVEAT =
  'Reports and photos go to POST /api/v1/citizen/reports then /media. Classification is a ' +
  'keyword heuristic on notes (smoke, fire, dust, haze, clear) — not a trained CV model. ' +
  'A photo alone never opens a HIGH event.'

function classifyFromNotes(observationType: string, notes: string): string {
  const text = `${observationType} ${notes}`.toLowerCase()
  for (const key of KEYWORDS) {
    if (new RegExp(`\\b${key}\\b`).test(text)) return key
  }
  return 'unknown'
}

async function demoReports(): Promise<CitizenReport[]> {
  await delay()
  return [...demoSessionReports, ...mockCitizenReports]
}

export async function fetchCitizenReports(): Promise<CitizenReport[]> {
  return resolve('citizen', demoReports, liveCitizenReports)
}

export async function fetchCitizenStats() {
  const reports = await fetchCitizenReports()
  return {
    totalToday: reports.length,
    awaiting: reports.filter((r) => r.status === 'PENDING').length,
    correlated: reports.filter((r) => r.status === 'CORROBORATED').length,
    reports,
  }
}

export interface CitizenSubmitInput {
  file: File
  notes: string
  observationType: string
  lat: number
  lon: number
}

/**
 * Create a report and attach the photo.
 *
 * Demo processes in-memory with the same keyword heuristic as the API.
 * Live calls the API only — a failure is thrown, not swapped for demo data.
 */
export async function submitCitizenReport(input: CitizenSubmitInput): Promise<CitizenReport> {
  const photoUrl = URL.createObjectURL(input.file)
  const notes = input.notes.trim()

  if (isDemo()) {
    await delay(220)
    const classification = classifyFromNotes(input.observationType, notes)
    const report: CitizenReport = {
      id: `cit_demo_${Date.now()}`,
      type: notes || input.observationType,
      location: `${input.lat.toFixed(3)}, ${input.lon.toFixed(3)}`,
      lat: input.lat,
      lon: input.lon,
      reportedAt: new Date().toISOString(),
      confidence: 0,
      classification,
      corroboration: 0,
      status: 'PENDING',
      mediaUri: `demo://citizen/${input.file.name}`,
      photoUrl,
    }
    demoSessionReports.unshift(report)
    return report
  }

  const created = await liveCreateCitizenReport({
    lat: input.lat,
    lon: input.lon,
    observationType: input.observationType,
    notes,
  })
  const stored = await liveAttachCitizenPhoto(created.report_id, input.file)
  return toUiCitizenReport(stored, photoUrl)
}
