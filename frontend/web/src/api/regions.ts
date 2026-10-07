/**
 * Region-scoped API calls. Each takes the `Transport` that answers it, so the
 * Demo recording and the Live API go through identical request code.
 */

import type { Transport } from './transport'
import type {
  CitizenCreated,
  CitizenReportDetail,
  CitizenReportPage,
  CitizenUploaded,
  Collection,
  CopilotAnswer,
  EvaluationRun,
  FireCluster,
  ForecastPoint,
  GridCell,
  HazardPoint,
  Incident,
  IncidentSummary,
  LikelihoodEntry,
  Page,
  PlumePage,
  PollutionEvent,
  Region,
  ServedModel,
  WindVector,
} from './regionTypes'

/** Generous enough for a region's served cells; the generator records the same. */
export const MAP_LIMIT = 2000

export const listRegions = (t: Transport) => t.get<Page<Region>>('/api/v1/regions')

export const getRegion = (t: Transport, regionId: string) =>
  t.get<Region>(`/api/v1/regions/${regionId}`)

const layer = <P>(t: Transport, name: string, regionId: string) =>
  t.get<Collection<P>>(`/api/v1/map/${name}`, { region_id: regionId, limit: MAP_LIMIT })

export const getGrid = (t: Transport, regionId: string) => layer<GridCell>(t, 'grid', regionId)
export const getFires = (t: Transport, regionId: string) => layer<FireCluster>(t, 'fire', regionId)
export const getWind = (t: Transport, regionId: string) => layer<WindVector>(t, 'weather', regionId)
export const getForecast = (t: Transport, regionId: string) =>
  layer<ForecastPoint>(t, 'forecast', regionId)
export const getHazard = (t: Transport, regionId: string) =>
  layer<HazardPoint>(t, 'hazard', regionId)

export const getSourceLikelihood = (t: Transport, regionId: string) =>
  t.get<Page<LikelihoodEntry>>('/api/v1/map/source-likelihood', { region_id: regionId })

export const getPlumes = (t: Transport, regionId: string) =>
  t.get<PlumePage>('/api/v1/plumes', { region_id: regionId })

export const getEvents = (t: Transport, regionId: string) =>
  t.get<Page<PollutionEvent>>('/api/v1/events', { region_id: regionId })

export const getEvent = (t: Transport, regionId: string, eventId: string) =>
  t.get<PollutionEvent>(`/api/v1/events/${eventId}`, { region_id: regionId })

export const getIncidents = (t: Transport, regionId: string) =>
  t.get<Page<IncidentSummary>>('/api/v1/incidents', { region_id: regionId })

export const getIncident = (t: Transport, incidentId: string) =>
  t.get<Incident>(`/api/v1/incidents/${incidentId}`)

export const getModels = (t: Transport, regionId: string) =>
  t.get<Page<ServedModel>>('/api/v1/models', { region_id: regionId })

export const getEvaluation = (t: Transport, regionId: string) =>
  t.get<Page<EvaluationRun>>('/api/v1/ml/evaluation', { region_id: regionId })

export const getCitizenReports = (t: Transport, regionId: string) =>
  t.get<CitizenReportPage>('/api/v1/citizen/reports', { region_id: regionId, limit: 100 })

export const getCitizenReport = (t: Transport, reportId: string) =>
  t.get<CitizenReportDetail>(`/api/v1/citizen/reports/${reportId}`)

export interface NewCitizenReport {
  lat: number
  lon: number
  regionId: string
  observationType: string
  notes: string
  contentType: string
  deviceAccuracyM: number | null
}

/** Create, then upload the photo where the API says to. */
export async function submitCitizenReport(
  t: Transport,
  input: NewCitizenReport,
  file: File,
): Promise<{ created: CitizenCreated; uploaded: CitizenUploaded | null }> {
  const created = await t.post<CitizenCreated>('/api/v1/citizen/reports', {
    lat: input.lat,
    lon: input.lon,
    region_id: input.regionId,
    observation_type: input.observationType,
    notes: input.notes || undefined,
    device_accuracy_m: input.deviceAccuracyM ?? undefined,
    content_type: input.contentType,
  })
  if (created.upload.method === 'PUT') {
    // Google Cloud: a signed URL straight to the bucket; the analyzer is notified by GCS.
    const response = await fetch(created.upload.url, {
      method: 'PUT',
      headers: { 'Content-Type': input.contentType },
      body: file,
    })
    if (!response.ok) throw new Error(`photo upload failed (${response.status})`)
    return { created, uploaded: null }
  }
  const form = new FormData()
  form.append(created.upload.field ?? 'file', file)
  const uploaded = await t.postForm<CitizenUploaded>(created.upload.url, form)
  return { created, uploaded }
}

export const askCopilot = (
  t: Transport,
  question: string,
  regionId: string,
  incidentId: string | null,
  history: { role: 'user' | 'assistant'; text: string }[],
) =>
  t.post<CopilotAnswer>('/api/v1/copilot/query', {
    question,
    region_id: regionId,
    incident_id: incidentId ?? undefined,
    history: history.length ? history : undefined,
  })
