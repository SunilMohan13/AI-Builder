/**
 * Wire contracts to UI types.
 *
 * The two vocabularies have genuinely diverged, and this file is where that
 * is resolved in the open rather than papered over:
 *
 * * **Severity.** The contract's top band is `CRITICAL`; the UI calls it
 *   `SEVERE`. A straight cast would render the top band as unstyled text.
 * * **Confidence scale.** Contracts use 0–1, the UI renders 0–100.
 * * **Geometry.** `event.v1` carries WKT `POINT(lon lat)` and `grid_ids`.
 *   The cell centroid on the grid feature is preferred; the WKT point is
 *   used when the feature row is missing so Live does not render at 0,0.
 * * **Fields the API does not have.** `recommendedActions` and
 *   `populationAtRisk` exist in the demo narrative and nowhere in the API.
 *   They are returned empty and listed in `provenance.unavailable`, so a
 *   screen can render "—" instead of quietly showing a demo value while
 *   claiming to be live. That substitution is the single worst failure mode
 *   available to this app, and the plan calls it out by name.
 */

import type {
  ApiEvent,
  ApiEvidence,
  ApiFireProperties,
  ApiForecast,
  ApiGraph,
  ApiGridFeature,
  ApiHazardCell,
  ApiModel,
  ApiPeakForecast,
  ApiSource,
  ApiWeatherProperties,
} from './contracts'
import type {
  DataProvenance,
  EventSeverity,
  EventStatus,
  EventType,
  EvidenceEdge,
  EvidenceItem,
  EvidenceNode,
  FireObservation,
  ForecastPoint,
  GridCell,
  HazardCell,
  ModelCatalogEntry,
  PeakForecastCell,
  PollutionEvent,
  SourceHealth,
  SourceLikelihood,
  TimelineEvent,
  WindObservation,
} from '../types'
import { getAqiFromPm25, getRiskFromPm25 } from '../utils/aqi'

/** Fields the live API has no equivalent for, listed once. */
export const LIVE_UNAVAILABLE_EVENT_FIELDS = [
  'recommendedActions',
  'populationAtRisk',
  'title',
] as const

const pct = (v: number | null | undefined): number => Math.round((v ?? 0) * 100)

/** Parse `event.v1` WKT `POINT(lon lat)`. */
export function parsePointWkt(
  geometry: string | null | undefined,
): { lat: number; lon: number } | null {
  if (!geometry) return null
  const match = geometry
    .trim()
    .match(/^POINT\s*\(\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*\)$/i)
  if (!match) return null
  const lon = Number(match[1])
  const lat = Number(match[2])
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null
  return { lat, lon }
}

/** Contract severity to UI severity. `CRITICAL` is the UI's `SEVERE`. */
export function toSeverity(value: string): EventSeverity {
  switch (value.toUpperCase()) {
    case 'CRITICAL':
    case 'SEVERE':
      return 'SEVERE'
    case 'HIGH':
      return 'HIGH'
    case 'MEDIUM':
      return 'MEDIUM'
    default:
      return 'LOW'
  }
}

const STATUSES: EventStatus[] = [
  'DETECTED',
  'VALIDATING',
  'CONFIRMED',
  'FORECASTING',
  'ACTIVE',
  'DECLINING',
  'RESOLVED',
  'REJECTED',
]

export function toStatus(value: string): EventStatus {
  const upper = value.toUpperCase() as EventStatus
  return STATUSES.includes(upper) ? upper : 'DETECTED'
}

/** Map the dominant source likelihood onto the UI's event-type vocabulary. */
export function toEventType(likelihood: ApiGridFeature['source_likelihood']): EventType {
  if (!likelihood) return 'transport'
  const ranked: [EventType, number][] = [
    ['biomass', likelihood.biomass_burning],
    ['industrial', likelihood.industrial],
    ['traffic', likelihood.traffic],
    ['dust', likelihood.dust],
    ['transport', likelihood.regional_transport],
  ]
  ranked.sort((a, b) => b[1] - a[1])
  return ranked[0][1] > 0 ? ranked[0][0] : 'transport'
}

export function toSourceLikelihood(
  likelihood: ApiGridFeature['source_likelihood'],
): SourceLikelihood[] {
  if (!likelihood) return []
  return [
    { source: 'Biomass burning', probability: pct(likelihood.biomass_burning) },
    { source: 'Regional transport', probability: pct(likelihood.regional_transport) },
    { source: 'Industrial', probability: pct(likelihood.industrial) },
    { source: 'Traffic', probability: pct(likelihood.traffic) },
    { source: 'Dust', probability: pct(likelihood.dust) },
  ].sort((a, b) => b.probability - a.probability)
}

/**
 * Coarse corridor region from a coordinate.
 *
 * A label for the operator, not an administrative boundary lookup. Kept
 * deliberately coarse — claiming district precision from a latitude band
 * would be a fabricated level of detail.
 */
export function toRegion(lat: number, lon: number): string {
  if (lat >= 30.2) return 'Punjab'
  if (lat >= 29.2) return 'Haryana (north)'
  if (lat >= 28.2 && lon >= 76.5) return 'Delhi NCR'
  if (lat >= 28.2) return 'Haryana (south)'
  return 'Indo-Gangetic corridor'
}

/**
 * Build a UI event from the contract plus, when available, the grid feature
 * for its first cell.
 *
 * @param event The `event.v1` record.
 * @param feature Grid feature for `event.grid_ids[0]`, when it could be
 *   fetched. Without it the event still renders, with concentrations and
 *   coordinates marked unavailable rather than guessed.
 */
export function toPollutionEvent(event: ApiEvent, feature?: ApiGridFeature): PollutionEvent {
  const unavailable = [...LIVE_UNAVAILABLE_EVENT_FIELDS] as string[]
  const pm25 = feature?.pm25 ?? feature?.pm25_estimate ?? 0
  const point = parsePointWkt(event.geometry)
  if (!feature) unavailable.push('pm25', 'pm10', 'aqi', 'sourceLikelihood')
  if (feature && feature.pm10 == null) unavailable.push('pm10')
  if (!feature && !point) unavailable.push('lat', 'lon')

  const lat = feature?.center_lat ?? point?.lat ?? 0
  const lon = feature?.center_lon ?? point?.lon ?? 0

  return {
    id: event.event_id,
    // The contract has no title. Composing one from the dominant source and
    // region is a label, so it is listed as unavailable above: a reader must
    // not take it for an operator-authored description.
    title: feature
      ? `${labelForType(toEventType(feature.source_likelihood))} · ${toRegion(lat, lon)}`
      : `Pollution event ${event.event_id.slice(0, 12)}`,
    type: toEventType(feature?.source_likelihood ?? null),
    severity: toSeverity(event.severity),
    status: toStatus(event.status),
    lat,
    lon,
    pm25: Math.round(pm25),
    pm10: Math.round(feature?.pm10 ?? 0),
    aqi: getAqiFromPm25(pm25),
    detectionConfidence: pct(event.detection_confidence),
    sourceConfidence: pct(event.source_confidence),
    forecastConfidence: pct(event.forecast_confidence),
    impactConfidence: pct(event.impact_confidence),
    // The API exposes population *density* on the grid feature, never a
    // headcount at risk. Multiplying density by an assumed area to produce a
    // "2.4M people" figure would be inventing the most quotable number on
    // the screen, so this stays 0 and is flagged.
    populationAtRisk: 0,
    region: toRegion(lat, lon),
    detectedAt: event.created_at,
    updatedAt: event.updated_at,
    fireCount: feature?.fire_count ?? 0,
    frpMw: Math.round(feature?.fire_frp ?? 0),
    sourceLikelihood: toSourceLikelihood(feature?.source_likelihood ?? null),
    // No API field supplies these. An empty list renders as "not provided".
    recommendedActions: [],
    gridIds: event.grid_ids,
    provenance: {
      mode: 'live',
      modelVersion: event.model_versions.join(', ') || null,
      featureVersion: event.feature_version,
      degraded: event.model_versions.every((v) => !v.startsWith('hgb-')),
      unavailable,
      note: feature
        ? undefined
        : `No persisted grid feature for ${event.grid_ids[0] ?? 'this event'}; concentrations unavailable.`,
    },
  }
}

function labelForType(type: EventType): string {
  switch (type) {
    case 'biomass':
      return 'Biomass burning event'
    case 'industrial':
      return 'Industrial emission event'
    case 'traffic':
      return 'Traffic emission event'
    case 'dust':
      return 'Dust event'
    default:
      return 'Regional transport event'
  }
}

export function toEvidenceItem(item: ApiEvidence, eventId: string): EvidenceItem {
  const quality = item.quality_score ?? 0
  return {
    id: item.evidence_id,
    category: item.evidence_type.replace(/_/g, ' '),
    source: item.evidence_type.split('_')[0].toUpperCase(),
    observation: item.summary,
    time: item.created_at ?? '',
    confidence: pct(quality),
    supports: eventId,
    strength: quality >= 0.8 ? 'Strong' : quality >= 0.5 ? 'Moderate' : 'Weak',
  }
}

/**
 * Flatten a `forecast.v1` into the UI's per-hour series.
 *
 * The contract is per-cell at a set of horizons; the chart is per-hour for
 * one place. The origin cell is taken as that place, because it is the only
 * cell present at every horizon.
 */
export function toForecastPoints(forecast: ApiForecast): ForecastPoint[] {
  const generated = new Date(forecast.generated_at).getTime()
  const cells = forecast.grid_predictions
  if (cells.length === 0) return []
  const baseline = cells[0]?.pm25 ?? 0
  // Origin cell is hour 0; remaining rows follow `horizons`. If the origin is
  // repeated, prefer the explicit horizon list over duplicating t=0.
  const hours =
    cells.length === forecast.horizons.length
      ? forecast.horizons
      : [0, ...forecast.horizons].slice(0, cells.length)

  return cells.map((cell, i) => {
    const hour = hours[i] ?? i
    const spread = (1 - cell.confidence) * cell.pm25
    return {
      hour,
      timestamp: new Date(generated + hour * 3600000).toISOString(),
      pm25: Math.round(cell.pm25),
      confidenceLow: Math.round(cell.pm25 - spread),
      confidenceHigh: Math.round(cell.pm25 + spread),
      baselinePm25: Math.round(baseline),
      p90: cell.p90,
      p10: cell.p10,
      provenance: {
        mode: 'live',
        modelVersion: forecast.model_version,
        degraded: !forecast.model_version.startsWith('hgb-'),
        note: forecast.cams_applied ? undefined : 'CAMS correction not applied.',
      },
    }
  })
}

/** Grid feature to the map's cell shape. */
export function toGridCell(feature: ApiGridFeature, stepDeg: number): GridCell {
  const pm25 = feature.pm25 ?? feature.pm25_estimate ?? 0
  return {
    gridId: feature.grid_id,
    lat: feature.center_lat,
    lon: feature.center_lon,
    pm25,
    pm10: feature.pm10 ?? 0,
    no2: feature.no2 ?? 0,
    aqi: getAqiFromPm25(pm25),
    // Density per km², which for a ~1 km cell is the closest honest stand-in
    // for cell population. Null stays 0 rather than becoming a guess.
    population: Math.round(feature.population ?? 0),
    risk: getRiskFromPm25(pm25),
    stepDeg,
    // The API does not separate a smoke contribution from total PM2.5. The
    // demo's plume decomposition is a narrative device; live has no such
    // split, so it is zero rather than a fabricated share.
    plume: 0,
    edgeFade: 1,
  }
}

export function toFireObservation(
  properties: ApiFireProperties,
  coordinates: [number, number],
): FireObservation {
  const [lon, lat] = coordinates
  // Contract confidence is 0–1, matching the demo mock fires. Values already
  // on a 0–100 scale (legacy GeoJSON) are brought back to 0–1 so the popup
  // that multiplies by 100 never shows 9100%.
  const raw = properties.confidence
  const confidence = raw > 1 ? raw / 100 : raw
  return {
    id: `${properties.source_id}_${properties.grid_id ?? `${lon}_${lat}`}_${properties.observed_at}`,
    lat,
    lon,
    frp: properties.frp,
    confidence,
    timestamp: properties.observed_at,
  }
}

export function toWindObservation(
  properties: ApiWeatherProperties,
  coordinates: [number, number],
): WindObservation | null {
  const { wind_u: u, wind_v: v } = properties
  if (u === null || v === null) return null
  const speed = Math.hypot(u, v)
  // Meteorological convention: the bearing the wind blows *from*.
  const direction = (Math.atan2(-u, -v) * 180) / Math.PI
  return {
    lat: coordinates[1],
    lon: coordinates[0],
    u,
    v,
    speed,
    direction: (direction + 360) % 360,
  }
}

export function toHazardCell(cell: ApiHazardCell): HazardCell | null {
  if (cell.center_lat === null || cell.center_lon === null) return null
  return {
    gridId: cell.grid_id,
    lat: cell.center_lat,
    lon: cell.center_lon,
    timestamp: cell.timestamp,
    hazardScore: cell.hazard_score,
    thresholdUgm3: cell.threshold_ugm3,
    horizonHours: cell.horizon_hours,
    calibrated: cell.calibrated,
    degraded: cell.degraded,
    modelVersion: cell.model_version,
    observedPm25: cell.observed_pm25,
  }
}

export function toPeakForecastCell(cell: ApiPeakForecast): PeakForecastCell | null {
  if (cell.center_lat === null || cell.center_lon === null) return null
  return {
    gridId: cell.grid_id,
    lat: cell.center_lat,
    lon: cell.center_lon,
    timestamp: cell.timestamp,
    peakPm25: cell.peak_pm25,
    horizonHours: cell.horizon_hours,
    exceedsThreshold: cell.exceeds_threshold,
    thresholdUgm3: cell.threshold_ugm3,
    degraded: cell.degraded,
    modelVersion: cell.model_version,
    observedPm25: cell.observed_pm25,
  }
}

function healthStatus(source: ApiSource): SourceHealth['status'] {
  const measured = (source.status || '').toUpperCase()
  if (measured === 'HEALTHY' || measured === 'REPLAY' || measured === 'REPLAY_EXHAUSTED') {
    return 'Healthy'
  }
  if (measured === 'DEGRADED' || measured === 'CIRCUIT_OPEN' || measured === 'FIXTURE_MISSING') {
    return 'Degraded'
  }
  if (measured === 'NOT_CONFIGURED') return 'Offline'
  if (measured === 'DISABLED' || source.enabled === false) return 'Disabled'
  return source.enabled ? 'Registered' : 'Disabled'
}

function minutesSince(iso: string | null | undefined): number | null {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(ms)) return null
  return Math.max(0, Math.round(ms / 60_000))
}

/**
 * Source registry entry to the UI's health row.
 *
 * Telemetry is nullable. A registry-only response (no last_success_at) still
 * reads as unknown rather than inventing demo freshness.
 */
export function toSourceHealth(source: ApiSource): SourceHealth {
  return {
    id: source.source_id,
    name: source.display_name || source.provider,
    status: healthStatus(source),
    freshnessMinutes: minutesSince(source.last_success_at),
    quality: source.quality_score ?? null,
    recordsToday: source.records_per_run ?? null,
    lastIngestion: source.last_success_at ?? null,
    latencySec: source.latency_ms == null ? null : source.latency_ms / 1000,
    errorRate: source.error_rate ?? null,
    connector: `${source.connector_id} · ${source.status}`,
  }
}

export function toModelCatalogEntry(model: ApiModel): ModelCatalogEntry {
  return {
    modelId: model.model_id,
    modelName: model.model_name,
    version: model.version,
    stage: model.stage,
    runtimeRole: model.runtime_role,
    algorithm: model.algorithm,
    artifactAvailable: model.artifact_available,
    gateFailures: model.gate_failures ?? [],
    notes: model.notes,
  }
}

/** Provenance stamp for any live value with no richer detail to report. */
export function liveProvenance(partial: Partial<DataProvenance> = {}): DataProvenance {
  return { mode: 'live', ...partial }
}

const NODE_TYPES: EvidenceNode['type'][] = [
  'event',
  'fire',
  'cpcb',
  'satellite',
  'weather',
  'cams',
  'forecast',
]

function graphNodeType(type: string, id: string): EvidenceNode['type'] {
  const token = `${type} ${id}`.toLowerCase()
  const hit = NODE_TYPES.find((name) => token.includes(name))
  if (hit) return hit
  if (token.includes('firms') || token.includes('modis')) return token.includes('modis') ? 'satellite' : 'fire'
  if (token.includes('observation') || token.includes('station')) return 'cpcb'
  if (token.includes('pollution')) return 'event'
  return 'cpcb'
}

/**
 * Place `graph.v1` vertices on the explorer canvas.
 *
 * The API stores lineage, not x/y. A radial layout around the event hub is
 * enough to read who supports whom; it is not the curated demo illustration.
 */
export function toEvidenceGraph(graph: ApiGraph): { nodes: EvidenceNode[]; edges: EvidenceEdge[] } {
  const cx = 400
  const cy = 200
  const hub =
    graph.vertices.find((v) => graphNodeType(v.type, v.id) === 'event') ?? graph.vertices[0]
  const spokes = graph.vertices.filter((v) => v.id !== hub?.id)
  const nodes: EvidenceNode[] = []
  if (hub) {
    nodes.push({
      id: hub.id,
      label: String(hub.properties?.label ?? 'Pollution Event'),
      type: 'event',
      x: cx,
      y: cy,
    })
  }
  spokes.forEach((vertex, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(spokes.length, 1) - Math.PI / 2
    nodes.push({
      id: vertex.id,
      label: String(vertex.properties?.label ?? vertex.id),
      type: graphNodeType(vertex.type, vertex.id),
      x: cx + Math.cos(angle) * 280,
      y: cy + Math.sin(angle) * 140,
    })
  })
  return {
    nodes,
    edges: graph.edges.map((edge) => ({ from: edge.from_id, to: edge.to_id })),
  }
}

/** Build a timeline from evidence plus the event clock when one is known. */
export function toTimeline(items: EvidenceItem[], detectedAt?: string): TimelineEvent[] {
  const events: TimelineEvent[] = items.map((item) => {
    const clock = item.time || detectedAt
    return {
      id: item.id,
      time: clock
        ? new Date(clock).toLocaleTimeString('en-IN', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: 'Asia/Kolkata',
          })
        : '—',
      label: item.observation,
      icon: item.category.toLowerCase().includes('fire') ? 'fire' : 'alert',
    }
  })
  if (detectedAt && events.length === 0) {
    events.push({
      id: 'detected',
      time: new Date(detectedAt).toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'Asia/Kolkata',
      }),
      label: 'Event detected',
      icon: 'alert',
    })
  }
  return events
}

/** Station observation as a 1 km map cell when grid-features are empty. */
export function stationToGridCell(
  lat: number,
  lon: number,
  pm25: number,
  sourceId: string,
  stepDeg: number,
): GridCell {
  return {
    gridId: `${sourceId}_${lat.toFixed(3)}_${lon.toFixed(3)}`,
    lat,
    lon,
    pm25,
    pm10: 0,
    no2: 0,
    aqi: getAqiFromPm25(pm25),
    population: 0,
    risk: getRiskFromPm25(pm25),
    stepDeg,
    plume: 0,
    edgeFade: 1,
  }
}
