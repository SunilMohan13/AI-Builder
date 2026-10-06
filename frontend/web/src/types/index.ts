export type EventType = 'biomass' | 'industrial' | 'traffic' | 'dust' | 'transport'
export type EventSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'SEVERE'
export type EventStatus =
  | 'DETECTED'
  | 'VALIDATING'
  | 'CONFIRMED'
  | 'FORECASTING'
  | 'ACTIVE'
  | 'DECLINING'
  | 'RESOLVED'
  | 'REJECTED'

export type ScientificLabel = 'OBSERVED' | 'INFERRED' | 'PREDICTED' | 'RECOMMENDED'

/**
 * Where a rendered value came from, and what it is not.
 *
 * Attached by the live adapters. Demo records leave it undefined, which the
 * UI reads as "scripted narrative". The point of `unavailable` is that the
 * live API supplies strictly less than the demo does — no recommended
 * actions, no population-at-risk headcount — and a screen that silently
 * shows demo values for those while claiming to be live would be the worst
 * failure this app can have.
 */
export interface DataProvenance {
  mode: 'demo' | 'live'
  /** Model or baseline that produced the value, e.g. `persistence-hazard-0.1`. */
  modelVersion?: string | null
  /** True when a deterministic fallback answered instead of a trained model. */
  degraded?: boolean
  /** False when a score ranks correctly but is not a probability. */
  calibrated?: boolean
  featureVersion?: string | null
  /** UI field names the live API does not provide. Render these as "—". */
  unavailable?: string[]
  /** One line explaining a degraded or partial answer. */
  note?: string
}

/** A 24-hour hazard score for one grid cell (hazard.v1). */
export interface HazardCell {
  gridId: string
  lat: number
  lon: number
  timestamp: string
  hazardScore: number
  thresholdUgm3: number
  horizonHours: number
  calibrated: boolean
  degraded: boolean
  modelVersion: string
  observedPm25: number | null
}

/** A 24-hour peak PM2.5 forecast for one grid cell (peak_forecast.v1). */
export interface PeakForecastCell {
  gridId: string
  lat: number
  lon: number
  timestamp: string
  peakPm25: number
  horizonHours: number
  exceedsThreshold: boolean
  thresholdUgm3: number
  degraded: boolean
  modelVersion: string
  observedPm25: number | null
}

/** One row of `GET /api/v1/models`. */
export interface ModelCatalogEntry {
  modelId: string
  modelName: string
  version: string
  stage: string
  runtimeRole: string
  algorithm: string
  artifactAvailable: boolean
  gateFailures: string[]
  notes: string
}

export interface PollutionEvent {
  id: string
  title: string
  type: EventType
  severity: EventSeverity
  status: EventStatus
  lat: number
  lon: number
  pm25: number
  pm10: number
  aqi: number
  detectionConfidence: number
  sourceConfidence: number
  forecastConfidence: number
  impactConfidence: number
  populationAtRisk: number
  region: string
  detectedAt: string
  updatedAt: string
  fireCount: number
  frpMw: number
  sourceLikelihood: SourceLikelihood[]
  recommendedActions: string[]
  /** H3 cells this event covers. Live adapters fill this; demo may omit it. */
  gridIds?: string[]
  provenance?: DataProvenance
}

export interface SourceLikelihood {
  source: string
  probability: number
}

export interface GridCell {
  gridId: string
  lat: number
  lon: number
  pm25: number
  pm10: number
  no2: number
  aqi: number
  population: number
  risk: 'LOW' | 'MEDIUM' | 'HIGH' | 'SEVERE'
  /** Cell edge length in degrees; the polygon is derived at render time.
   *  Storing the four corners per cell cost ~6 extra objects each, which
   *  dominated memory once tens of thousands of cells were cached. */
  stepDeg: number
  /** Smoke contribution from the fire source alone, in µg/m³. */
  plume: number
  /** 0 at the corridor edge, 1 inland — used to fade the layer boundary. */
  edgeFade: number
}

export interface FireObservation {
  id: string
  lat: number
  lon: number
  frp: number
  confidence: number
  timestamp: string
}

export interface WindObservation {
  lat: number
  lon: number
  u: number
  v: number
  speed: number
  direction: number
}

export interface ForecastPoint {
  hour: number
  timestamp: string
  pm25: number
  confidenceLow: number
  confidenceHigh: number
  /** Persistence baseline: hold last observed PM2.5 (honest comparison for promotion). */
  baselinePm25?: number
  /** Upper-decile forecast, for alert thresholding. Null on the deterministic path. */
  p90?: number | null
  /** Lower-decile forecast, carried with p90 so uncertainty is not one-sided. */
  p10?: number | null
  provenance?: DataProvenance
}

export interface EvidenceItem {
  id: string
  category: string
  source: string
  observation: string
  time: string
  confidence: number
  supports: string
  strength: 'Weak' | 'Moderate' | 'Strong'
}

export interface EvidenceNode {
  id: string
  label: string
  type: 'event' | 'fire' | 'cpcb' | 'satellite' | 'weather' | 'cams' | 'forecast'
  x: number
  y: number
  item?: EvidenceItem
}

export interface EvidenceEdge {
  from: string
  to: string
}

export interface SourceHealth {
  id: string
  name: string
  /**
   * `Registered` / `Disabled` are registry facts; the rest are measured
   * health. Live must not claim a measured state it never observed.
   */
  status: 'Healthy' | 'Delayed' | 'Degraded' | 'Offline' | 'Registered' | 'Disabled'
  /**
   * Operational telemetry. Null where it is genuinely unknown.
   *
   * `GET /api/v1/sources` is a *registry* — source id, provider, connector,
   * enabled flag — and carries none of these. Nullable rather than a
   * sentinel so the compiler forces every consumer to render "unknown"
   * instead of printing `-1 min` at an operator.
   */
  freshnessMinutes: number | null
  quality: number | null
  recordsToday: number | null
  lastIngestion: string | null
  latencySec: number | null
  errorRate: number | null
  connector: string
}

export interface CitizenReport {
  id: string
  type: string
  location: string
  lat: number
  lon: number
  reportedAt: string
  confidence: number
  classification: string
  corroboration: number
  status: 'PENDING' | 'CORROBORATED' | 'REJECTED'
  relatedEventId?: string
  mediaUri?: string
  photoUrl?: string
}

export interface PopulationRiskArea {
  rank: number
  name: string
  risk: 'LOW' | 'MEDIUM' | 'HIGH' | 'SEVERE'
  population: number
  lat: number
  lon: number
}

export interface IndustrySite {
  id: string
  name: string
  lat: number
  lon: number
  type: string
}

export interface Notification {
  id: string
  title: string
  message: string
  time: string
  route: string
  icon: 'fire' | 'forecast' | 'warning'
}

export interface TimelineEvent {
  id: string
  time: string
  label: string
  icon: string
}

export interface CopilotMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: { source: string; time: string }[]
  /** Actions the backend retrieved. Previously dropped on the floor even
   *  though ActionBrief sends users here expecting them. */
  recommendedActions?: string[]
  /** Split confidence, when the answer is about a specific event. */
  confidence?: { detection?: number; source?: number; forecast?: number; overall?: number }
  /** Tools the backend actually called, for honest provenance. */
  toolCalls?: { name: string; arguments?: Record<string, unknown> }[]
  /** False only if the server surfaced an ungrounded answer, which it should
   *  never do; rendered as a warning if it ever happens. */
  grounded?: boolean
  llmUsed?: boolean
  model?: string | null
  degradedReason?: string | null
}

export interface MapLayerVisibility {
  pollution: boolean
  fires: boolean
  wind: boolean
  forecast: boolean
  industry: boolean
  population: boolean
}

export type DemoPhase =
  | 'idle'
  | 'fire'
  | 'anomaly'
  | 'wind'
  | 'plume'
  | 'confirmed'
  | 'forecast'
  | 'risk'
  | 'complete'
