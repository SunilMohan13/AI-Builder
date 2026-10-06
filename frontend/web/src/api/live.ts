/**
 * Live implementations of every UI data need.
 *
 * One function per service call, each returning UI types. The service layer
 * chooses between these and the demo narrative; nothing here knows about
 * modes or fallbacks.
 */

import type {
  ApiAlert,
  ApiAqProperties,
  ApiCitizenReport,
  ApiCopilot,
  ApiEvent,
  ApiEvidence,
  ApiFireProperties,
  ApiForecast,
  ApiGraph,
  ApiGridFeature,
  ApiHazardCell,
  ApiIndustryProperties,
  ApiModel,
  ApiPeakForecast,
  ApiPopulationSource,
  ApiProvenance,
  ApiRiskArea,
  ApiSource,
  ApiWeatherProperties,
} from './contracts'
import type {
  CitizenReport,
  CopilotMessage,
  EvidenceEdge,
  EvidenceItem,
  EvidenceNode,
  FireObservation,
  ForecastPoint,
  GridCell,
  HazardCell,
  IndustrySite,
  ModelCatalogEntry,
  Notification,
  PeakForecastCell,
  PollutionEvent,
  PopulationRiskArea,
  SourceHealth,
  TimelineEvent,
  WindObservation,
} from '../types'
import { relativeTime } from '../utils/format'
import { apiGet, apiPost, apiPostForm, ApiError, type FeatureCollection, type ListResponse } from './client'
import {
  stationToGridCell,
  toEvidenceGraph,
  toEvidenceItem,
  toFireObservation,
  toForecastPoints,
  toGridCell,
  toHazardCell,
  toModelCatalogEntry,
  toPeakForecastCell,
  toPollutionEvent,
  toSourceHealth,
  toTimeline,
  toWindObservation,
} from './adapters'
import { KM1_DEG } from '../utils/geo'

/** Cache of grid features within one render pass, keyed by cell. */
const featureCache = new Map<string, ApiGridFeature | null>()

/** Drop memoised features so a refetch sees fresh concentrations. */
export function clearLiveCaches(): void {
  featureCache.clear()
}

async function gridFeature(gridId: string): Promise<ApiGridFeature | null> {
  if (featureCache.has(gridId)) return featureCache.get(gridId) ?? null
  let feature: ApiGridFeature | null = null
  try {
    feature = await apiGet<ApiGridFeature>(`/api/v1/grid-features/${gridId}/latest`)
  } catch {
    // A 404 is ordinary: a cell can have an event without a persisted
    // feature row. The event still renders, with concentrations marked
    // unavailable by the adapter.
    feature = null
  }
  featureCache.set(gridId, feature)
  return feature
}

export async function liveEvents(): Promise<PollutionEvent[]> {
  const response = await apiGet<ListResponse<ApiEvent>>('/api/v1/events', { limit: 50 })
  return Promise.all(
    response.items.map(async (event) =>
      toPollutionEvent(event, (await gridFeature(event.grid_ids[0] ?? '')) ?? undefined),
    ),
  )
}

export async function liveEvent(id: string): Promise<PollutionEvent | null> {
  try {
    const event = await apiGet<ApiEvent>(`/api/v1/events/${id}`)
    const feature = await gridFeature(event.grid_ids[0] ?? '')
    return toPollutionEvent(event, feature ?? undefined)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export async function liveEvidence(eventId: string): Promise<EvidenceItem[]> {
  try {
    const response = await apiGet<ListResponse<ApiEvidence>>(`/api/v1/events/${eventId}/evidence`)
    return response.items.map((item) => toEvidenceItem(item, eventId))
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return []
    throw error
  }
}

export async function liveTimeline(eventId: string): Promise<TimelineEvent[]> {
  const evidence = await liveEvidence(eventId)
  return toTimeline(evidence)
}

export async function liveEvidenceGraph(
  eventId: string,
): Promise<{ nodes: EvidenceNode[]; edges: EvidenceEdge[] }> {
  const graph = await apiGet<ApiGraph>(`/api/v1/events/${eventId}/graph`)
  const laidOut = toEvidenceGraph(graph)
  const evidence = await liveEvidence(eventId)
  const bySource = new Map(evidence.map((item) => [item.source.toLowerCase(), item]))
  return {
    nodes: laidOut.nodes.map((node) => ({
      ...node,
      item: node.item ?? bySource.get(node.id.toLowerCase()) ?? evidence.find((item) =>
        item.category.toLowerCase().includes(node.type),
      ),
    })),
    edges: laidOut.edges,
  }
}

/** The most recently updated event, used where the UI needs "the" event. */
async function primaryEventId(): Promise<string | null> {
  const response = await apiGet<ListResponse<ApiEvent>>('/api/v1/events', { limit: 20 })
  const active = response.items.find((e) => e.status === 'ACTIVE' || e.status === 'CONFIRMED')
  return (active ?? response.items[0])?.event_id ?? null
}

export async function liveForecast(eventId?: string): Promise<ForecastPoint[]> {
  const target = eventId ?? (await primaryEventId())
  if (!target) {
    throw new ApiError('no live event to forecast', 404, '/api/v1/events')
  }
  const forecast = await apiGet<ApiForecast>(`/api/v1/events/${target}/forecast`)
  const points = toForecastPoints(forecast)
  if (points.length === 0) {
    throw new ApiError(
      `no forecast cells for event ${target}`,
      404,
      `/api/v1/events/${target}/forecast`,
    )
  }
  return points
}

export async function liveObservedHistory(
  gridId: string,
): Promise<{ hour: number; pm25: number }[]> {
  const response = await apiGet<{ items: { hour: number; pm25: number }[] }>(
    `/api/v1/grid-features/${encodeURIComponent(gridId)}/history`,
    { limit: 48 },
  )
  return response.items.map((item) => ({ hour: item.hour, pm25: item.pm25 }))
}

/** Horizons the advection forecast actually publishes (forecast.py HORIZONS_H). */
const FORECAST_HORIZONS = [3, 6, 12, 24, 48]

/** Snap a scrubber offset to the nearest published forecast horizon.
 *
 *  Asking for +9h would return nothing, because the forecast is computed at
 *  fixed horizons rather than continuously.
 */
export function nearestHorizon(hourOffset: number): number | null {
  if (hourOffset <= 0) return null
  return FORECAST_HORIZONS.reduce((best, h) =>
    Math.abs(h - hourOffset) < Math.abs(best - hourOffset) ? h : best,
  )
}

/**
 * Grid cells for the pollution layer.
 *
 * At `hourOffset` 0 this is observed data. Beyond that it is the advection
 * forecast for the nearest published horizon — previously the offset was
 * ignored entirely, so scrubbing to "+12h" redrew the present under a future
 * label.
 */
export async function liveAirQuality(hourOffset = 0): Promise<GridCell[]> {
  const horizon = nearestHorizon(hourOffset)
  if (horizon !== null) return liveForecastCells(horizon)

  let cells: GridCell[] = []
  try {
    const response = await apiGet<ListResponse<ApiGridFeature>>('/api/v1/grid-features', {
      limit: 500,
    })
    cells = response.items.map((feature) => toGridCell(feature, KM1_DEG))
  } catch (error) {
    if (!(error instanceof ApiError) || (error.status !== 503 && error.status !== 404)) {
      throw error
    }
  }

  if (cells.length === 0) {
    const stations = await liveStations()
    cells = stations
      .filter((station) => station.parameter.toLowerCase().includes('pm25'))
      .map((station) =>
        stationToGridCell(station.lat, station.lon, station.value, station.sourceId, KM1_DEG),
      )
  }

  try {
    const collection = await apiGet<
      FeatureCollection<{ pm25?: number; grid_id?: string; confidence?: number }>
    >('/api/v1/map/forecast', { limit: 500, horizon_hours: 0 })
    for (const feature of collection.features) {
      const pm25 = feature.properties.pm25
      if (pm25 == null) continue
      const [lon, lat] = feature.geometry.coordinates as unknown as [number, number]
      const existing = cells.find(
        (cell) =>
          cell.gridId === feature.properties.grid_id ||
          (Math.abs(cell.lat - lat) < 0.02 && Math.abs(cell.lon - lon) < 0.02),
      )
      if (existing) {
        existing.plume = pm25
      } else {
        const cell = stationToGridCell(
          lat,
          lon,
          pm25,
          feature.properties.grid_id ?? `forecast_${lat.toFixed(3)}_${lon.toFixed(3)}`,
          KM1_DEG,
        )
        cell.plume = pm25
        cells.push(cell)
      }
    }
  } catch (error) {
    if (!(error instanceof ApiError) || (error.status !== 404 && error.status !== 503)) {
      throw error
    }
  }

  return cells
}

/** Forecast cells for one horizon, used when the timeline is scrubbed forward. */
async function liveForecastCells(horizonHours: number): Promise<GridCell[]> {
  const collection = await apiGet<
    FeatureCollection<{ pm25?: number; grid_id?: string; confidence?: number }>
  >('/api/v1/map/forecast', { limit: 500, horizon_hours: horizonHours })

  const cells: GridCell[] = []
  for (const feature of collection.features) {
    const pm25 = feature.properties.pm25
    if (pm25 == null) continue
    const [lon, lat] = feature.geometry.coordinates as unknown as [number, number]
    const cell = stationToGridCell(
      lat,
      lon,
      pm25,
      feature.properties.grid_id ?? `forecast_${lat.toFixed(3)}_${lon.toFixed(3)}`,
      KM1_DEG,
    )
    cell.plume = pm25
    cells.push(cell)
  }

  if (cells.length === 0) {
    // An empty forecast is a real answer, but a silently empty map is not.
    // Throwing puts the endpoint in the fallback banner with a reason.
    throw new ApiError(
      `no advection forecast published for +${horizonHours}h`,
      404,
      '/api/v1/map/forecast',
    )
  }
  return cells
}

/** Structured explanation of one event, from stored evidence. */
export async function liveExplainEvent(eventId: string): Promise<CopilotMessage> {
  const response = await apiPost<ApiCopilot>('/api/v1/copilot/explain-event', {
    event_id: eventId,
  })
  const sections: string[] = [response.answer]
  if (response.observed_facts?.length) {
    sections.push(`OBSERVED\n${response.observed_facts.map((f) => `• ${f}`).join('\n')}`)
  }
  if (response.predicted_conditions?.length) {
    sections.push(`PREDICTED\n${response.predicted_conditions.map((p) => `• ${p}`).join('\n')}`)
  }
  if (response.limitations?.length) {
    sections.push(`LIMITATIONS\n${response.limitations.map((l) => `• ${l}`).join('\n')}`)
  }
  return {
    id: `explain_${eventId}`,
    role: 'assistant',
    content: sections.join('\n\n'),
    citations: (response.evidence ?? [])
      .map((item) => ({
        source: item.source ?? item.evidence_type ?? '',
        time: item.time ?? '',
      }))
      .filter((item) => item.source),
    recommendedActions: response.recommended_actions ?? [],
    confidence: response.confidence as CopilotMessage['confidence'],
    llmUsed: response.llm_used ?? false,
    grounded: response.grounding?.grounded ?? true,
  }
}

/** Alerts raised by the event engine, newest first. */
export async function liveAlerts(): Promise<Notification[]> {
  const response = await apiGet<ListResponse<ApiAlert>>('/api/v1/alerts', { limit: 50 })
  return response.items.map((alert) => ({
    id: alert.alert_id,
    title: `${alert.severity.toUpperCase()} pollution event`,
    message: alert.message,
    time: relativeTime(alert.created_at),
    route: `/events/${alert.event_id}`,
    // Severity drives the icon: the engine only raises alerts for
    // HIGH/CRITICAL, so there is no "informational" case to style.
    icon: alert.severity.toLowerCase() === 'critical' ? 'warning' : 'fire',
  }))
}

export async function liveFires(): Promise<FireObservation[]> {
  const collection = await apiGet<FeatureCollection<ApiFireProperties>>('/api/v1/map/fire', {
    limit: 500,
  })
  return collection.features.map((f) =>
    toFireObservation(f.properties, f.geometry.coordinates as unknown as [number, number]),
  )
}

export async function liveWeather(): Promise<WindObservation[]> {
  const collection = await apiGet<FeatureCollection<ApiWeatherProperties>>('/api/v1/map/weather', {
    limit: 500,
  })
  return collection.features
    .map((f) =>
      toWindObservation(f.properties, f.geometry.coordinates as unknown as [number, number]),
    )
    .filter((w): w is WindObservation => w !== null)
}

export async function liveSources(): Promise<SourceHealth[]> {
  const response = await apiGet<ListResponse<ApiSource>>('/api/v1/sources', { limit: 50 })
  return response.items.map(toSourceHealth)
}

export async function liveModels(): Promise<ModelCatalogEntry[]> {
  const response = await apiGet<ListResponse<ApiModel>>('/api/v1/models', { limit: 100 })
  return response.items.map(toModelCatalogEntry)
}

export interface LiveHazard {
  cells: HazardCell[]
  provenance: ApiProvenance | null
}

export async function liveHazard(): Promise<LiveHazard> {
  const response = await apiGet<ListResponse<ApiHazardCell> & { provenance?: ApiProvenance }>(
    '/api/v1/grid-hazard',
    { limit: 500 },
  )
  return {
    cells: response.items
      .map(toHazardCell)
      .filter((c): c is HazardCell => c !== null)
      .sort((a, b) => b.hazardScore - a.hazardScore),
    provenance: response.provenance ?? null,
  }
}

export interface LivePeak {
  cells: PeakForecastCell[]
  provenance: ApiProvenance | null
}

export async function livePeak(): Promise<LivePeak> {
  const response = await apiGet<ListResponse<ApiPeakForecast> & { provenance?: ApiProvenance }>(
    '/api/v1/grid-peak',
    { limit: 500 },
  )
  return {
    cells: response.items
      .map(toPeakForecastCell)
      .filter((c): c is PeakForecastCell => c !== null)
      .sort((a, b) => b.peakPm25 - a.peakPm25),
    provenance: response.provenance ?? null,
  }
}

/**
 * Ranked exposure areas from `GET /api/v1/risk/areas`.
 *
 * Replaces an earlier client-side approach that scored each grid cell with
 * its own `/api/v1/risk` call: one request instead of N, and the ranking is
 * computed where the population data lives rather than being re-derived in
 * the browser.
 *
 * `population` here is a real headcount from the reference layer, not a
 * density — unlike the grid-feature path, where only density exists.
 */
export async function liveRiskAreas(): Promise<PopulationRiskArea[]> {
  const response = await apiGet<{
    items: ApiRiskArea[]
    population_source?: ApiPopulationSource
  }>('/api/v1/risk/areas', { pm25: 180, exposure_hours: 6 })

  return response.items.map((area) => ({
    rank: area.rank,
    name: area.name,
    risk: toRiskBand(area.risk),
    population: area.population,
    lat: area.lat,
    lon: area.lon,
  }))
}

/** Population provenance, so the UI can state which provider backs a number. */
export async function livePopulationSource(): Promise<ApiPopulationSource | null> {
  const response = await apiGet<{ population_source?: ApiPopulationSource }>(
    '/api/v1/risk/areas',
    { pm25: 180, exposure_hours: 6 },
  )
  return response.population_source ?? null
}

function toRiskBand(value: string): PopulationRiskArea['risk'] {
  const upper = value.toUpperCase()
  if (upper === 'SEVERE' || upper === 'HIGH' || upper === 'MEDIUM') return upper
  return 'LOW'
}

/**
 * Citizen reports from `GET /api/v1/citizen/reports`.
 *
 * Classification is a notes keyword heuristic. There is no CV model.
 */
export function toUiCitizenReport(report: ApiCitizenReport, photoUrl?: string): CitizenReport {
  return {
    id: report.report_id,
    type: report.notes ?? report.observation_type,
    location: `${report.lat.toFixed(3)}, ${report.lon.toFixed(3)}`,
    lat: report.lat,
    lon: report.lon,
    reportedAt: report.observed_at,
    confidence: 0,
    classification: report.cv_class,
    corroboration: report.correlated_event_id ? 1 : 0,
    status:
      report.moderation === 'accepted'
        ? 'CORROBORATED'
        : report.moderation === 'rejected'
          ? 'REJECTED'
          : 'PENDING',
    relatedEventId: report.correlated_event_id ?? undefined,
    mediaUri: report.media_uri ?? undefined,
    photoUrl,
  }
}

export async function liveCitizenReports(): Promise<CitizenReport[]> {
  const response = await apiGet<ListResponse<ApiCitizenReport>>('/api/v1/citizen/reports')
  return response.items.map((report) => toUiCitizenReport(report))
}

export async function liveCreateCitizenReport(input: {
  lat: number
  lon: number
  observationType: string
  notes: string
}): Promise<ApiCitizenReport> {
  return apiPost<ApiCitizenReport>('/api/v1/citizen/reports', {
    lat: input.lat,
    lon: input.lon,
    observation_type: input.observationType,
    notes: input.notes || null,
  })
}

export async function liveAttachCitizenPhoto(
  reportId: string,
  file: File,
): Promise<ApiCitizenReport> {
  const body = new FormData()
  body.append('file', file)
  return apiPostForm<ApiCitizenReport>(`/api/v1/citizen/reports/${reportId}/media`, body)
}

/** Industrial assets from `GET /api/v1/map/industry`. */
export async function liveIndustries(): Promise<IndustrySite[]> {
  const collection = await apiGet<FeatureCollection<ApiIndustryProperties>>(
    '/api/v1/map/industry',
    { limit: 500 },
  )
  return collection.features.map((feature, index) => {
    const [lon, lat] = feature.geometry.coordinates as unknown as [number, number]
    const properties = feature.properties
    return {
      id: properties.asset_id ?? properties.product_id ?? `industry_${index}`,
      name: properties.name ?? properties.product_id ?? 'Industrial asset',
      lat,
      lon,
      // The replay serves raster product footprints, which carry no asset
      // classification. Labelled generically rather than guessed at.
      type: properties.resolution ? `Asset (${properties.resolution})` : 'Industrial asset',
    }
  })
}

export async function liveCopilot(
  query: string,
  history: { role: 'user' | 'assistant'; text: string }[] = [],
): Promise<CopilotMessage> {
  const response = await apiPost<ApiCopilot>('/api/v1/copilot/query', {
    question: query,
    history,
  })

  // The answer is the model's prose. The structured lists are appended only
  // when the deterministic path produced them; a Gemini answer already reads
  // as prose and does not need OBSERVED/INFERRED headers bolted on.
  const sections: string[] = [response.answer]
  if (!response.llm_used) {
    if (response.observed_facts?.length) {
      sections.push(`OBSERVED\n${response.observed_facts.map((f) => `• ${f}`).join('\n')}`)
    }
    if (response.likely_sources?.length) {
      const lines = response.likely_sources.map((source) => {
        if (typeof source === 'string') return `• ${source}`
        const note = source.note ?? 'Independent source likelihood'
        const conf =
          source.source_confidence != null
            ? ` (${Math.round(source.source_confidence * 100)}%)`
            : ''
        return `• ${note}${conf}`
      })
      sections.push(`INFERRED\n${lines.join('\n')}`)
    }
    if (response.predicted_conditions?.length) {
      sections.push(`PREDICTED\n${response.predicted_conditions.map((p) => `• ${p}`).join('\n')}`)
    }
  }
  if (response.limitations?.length) {
    sections.push(`LIMITATIONS\n${response.limitations.map((l) => `• ${l}`).join('\n')}`)
  }

  return {
    id: `msg_${Date.now()}`,
    role: 'assistant',
    content: sections.join('\n\n'),
    citations: (response.evidence ?? [])
      .map((item) => ({
        source: item.source ?? item.evidence_type ?? '',
        time: item.time ?? '',
      }))
      .filter((item) => item.source),
    // Previously received and silently discarded, while ActionBrief told the
    // user to come here for exactly these.
    recommendedActions: response.recommended_actions ?? [],
    confidence: response.confidence as CopilotMessage['confidence'],
    toolCalls: response.tool_calls ?? [],
    grounded: response.grounding?.grounded ?? true,
    llmUsed: response.llm_used ?? false,
    model: response.model ?? null,
    degradedReason: response.degraded_reason ?? null,
  }
}

/** Air-quality observation points, for the map's station layer. */
export async function liveStations(): Promise<
  { lat: number; lon: number; parameter: string; value: number; sourceId: string }[]
> {
  const collection = await apiGet<FeatureCollection<ApiAqProperties>>('/api/v1/map/air-quality', {
    limit: 500,
  })
  return collection.features.map((f) => {
    const [lon, lat] = f.geometry.coordinates as unknown as [number, number]
    return {
      lat,
      lon,
      parameter: f.properties.parameter,
      value: f.properties.value,
      sourceId: f.properties.source_id,
    }
  })
}
