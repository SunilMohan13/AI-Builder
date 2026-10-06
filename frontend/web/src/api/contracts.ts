/**
 * Wire shapes exactly as the API emits them, in `snake_case`.
 *
 * Kept separate from `src/types` on purpose. These mirror the Pydantic
 * contracts in `libs/contracts`; the UI types are a different vocabulary that
 * has legitimately diverged from them. Conflating the two is what makes an
 * adapter layer silently rot — a field renamed on the backend should break a
 * type here, not quietly become `undefined` three components deep.
 */

/** `event.v1` */
export interface ApiEvent {
  event_id: string
  event_type: string
  schema_version: 'event.v1'
  status: string
  /** LOW | MEDIUM | HIGH | CRITICAL. The UI calls the top band SEVERE. */
  severity: string
  created_at: string
  updated_at: string
  geometry: string | null
  grid_ids: string[]
  pollutants: string[]
  detection_confidence: number
  source_confidence: number
  forecast_confidence: number
  impact_confidence: number
  overall_confidence: number
  evidence_ids: string[]
  model_versions: string[]
  feature_version: string
  evidence_freshness: number
  sensor_coverage: number
}

/** One item of `GET /api/v1/events/{id}/evidence` */
export interface ApiEvidence {
  evidence_id: string
  evidence_type: string
  observation_id: string | null
  grid_id: string | null
  summary: string
  quality_score: number | null
  created_at?: string | null
}

/** `grid-features.v1` */
export interface ApiGridFeature {
  schema_version: 'grid-features.v1'
  feature_version: string
  grid_id: string
  timestamp: string
  center_lat: number
  center_lon: number
  pm25: number | null
  pm10: number | null
  no2: number | null
  so2: number | null
  co: number | null
  o3: number | null
  station_distance: number | null
  aod: number | null
  wind_u: number | null
  wind_v: number | null
  wind_speed: number | null
  wind_direction: number | null
  temperature: number | null
  humidity: number | null
  pressure: number | null
  boundary_layer_height: number | null
  fire_count: number
  fire_frp: number
  upwind_fire_score: number
  population: number | null
  pm25_estimate: number | null
  estimate_confidence: number | null
  anomaly_score: number | null
  source_likelihood: {
    biomass_burning: number
    industrial: number
    traffic: number
    dust: number
    regional_transport: number
  } | null
  quality_score: number | null
  source_count: number
  missing_feature_count: number
}

/** `forecast.v1` */
export interface ApiForecast {
  schema_version: 'forecast.v1'
  model_version: string
  event_id: string | null
  origin_grid_id: string
  generated_at: string
  cams_applied: boolean
  horizons: number[]
  horizon_hours: number | null
  grid_predictions: {
    grid_id: string
    pm25: number
    confidence: number
    center_lat: number | null
    center_lon: number | null
    p90: number | null
    p10: number | null
  }[]
}

/** `hazard.v1` */
export interface ApiHazardCell {
  schema_version: 'hazard.v1'
  grid_id: string
  timestamp: string
  center_lat: number | null
  center_lon: number | null
  hazard_score: number
  threshold_ugm3: number
  horizon_hours: number
  calibrated: boolean
  degraded: boolean
  model_version: string
  feature_version: string | null
  feature_completeness: number | null
  observed_pm25: number | null
}

/** `peak_forecast.v1` */
export interface ApiPeakForecast {
  schema_version: 'peak_forecast.v1'
  grid_id: string
  timestamp: string
  center_lat: number | null
  center_lon: number | null
  peak_pm25: number
  prediction_interval_low: number | null
  prediction_interval_high: number | null
  horizon_hours: number
  exceeds_threshold: boolean
  threshold_ugm3: number
  degraded: boolean
  model_version: string
  observed_pm25: number | null
}

/** Provenance envelope on the hazard and peak collections. */
export interface ApiProvenance {
  model_name: string
  model_version: string
  degraded: boolean
  promoted_champion?: string
  reason: string
}

/** One item of `GET /api/v1/sources` */
export interface ApiSource {
  source_id: string
  provider: string
  connector_id: string
  display_name: string
  data_type: string
  enabled: boolean
  status: string
  schema_version: string
  live_capable?: boolean
  last_success_at?: string | null
  latency_ms?: number | null
  records_per_run?: number | null
  error?: string | null
  processing_mode?: string | null
  quality_score?: number | null
  error_rate?: number | null
}

/** One item of `GET /api/v1/models` */
export interface ApiModel {
  model_id: string
  model_name: string
  version: string
  stage: string
  runtime_role: string
  algorithm: string
  artifact_available: boolean
  gate_failures?: string[]
  notes: string
  metrics: Record<string, unknown>
}

/** `GET /api/v1/risk` */
export interface ApiRisk {
  pollution_severity: number
  population_risk: number
  exposure_duration_hours: number
  population_density: number
  confidence: number
  formula_version: string
  population_measured: boolean
  population_source: string
  population_reference: string | null
}

/** One item of `GET /api/v1/risk/areas` */
export interface ApiRiskArea {
  cell_id: string
  name: string
  lat: number
  lon: number
  population: number
  population_density: number
  risk: string
  population_risk: number
  pollution_severity: number
  rank: number
}

/** Provenance envelope on `GET /api/v1/risk/areas`. */
export interface ApiPopulationSource {
  provider: string | null
  provider_version: string | null
  license: string | null
  source_uri: string | null
}

/** `citizen_report.v1` */
export interface ApiCitizenReport {
  schema_version: 'citizen_report.v1'
  report_id: string
  lat: number
  lon: number
  observed_at: string
  observation_type: string
  notes: string | null
  media_uri: string | null
  cv_class: 'smoke' | 'fire' | 'dust' | 'haze' | 'clear' | 'unknown'
  moderation: 'pending' | 'accepted' | 'rejected'
  grid_id: string | null
  correlated_event_id: string | null
}

/** Properties on `/map/industry` features. */
export interface ApiIndustryProperties {
  source_id?: string
  asset_id?: string
  name?: string
  product_id?: string
  resolution?: string
}

/** `alert.v1` */
export interface ApiAlert {
  alert_id: string
  event_id: string
  severity: string
  recipient_group?: string
  message_template?: string
  message: string
  evidence?: { evidence_id?: string; type?: string }[]
  channel?: string
  created_at: string
  expires_at?: string | null
}

/** `copilot.v2` */
export interface ApiCopilotToolCall {
  name: string
  arguments?: Record<string, unknown>
}

/** Verdict from the server-side numeric grounding check. */
export interface ApiCopilotGrounding {
  grounded: boolean
  numbers_checked?: number
  ungrounded_values?: number[]
}

/** `copilot.v2` */
export interface ApiCopilot {
  schema_version?: string
  answer: string
  observed_facts?: string[]
  predicted_conditions?: string[]
  likely_sources?: string[] | { note?: string; source_confidence?: number }[]
  evidence?: { source?: string; time?: string; summary?: string; evidence_type?: string }[]
  recommended_actions?: string[]
  limitations?: string[]
  /** True only when a model produced the text AND its numbers passed grounding. */
  llm_used?: boolean
  model?: string | null
  /** Which tools were actually consulted. Replaces the old scripted spinner. */
  tool_calls?: ApiCopilotToolCall[]
  grounding?: ApiCopilotGrounding
  /** Why deterministic retrieval answered, when it did. */
  degraded_reason?: string | null
  confidence?: Record<string, number>
}

/** Properties on `/map/air-quality` features. */
export interface ApiAqProperties {
  source_id: string
  parameter: string
  value: number
  unit: string
  observed_at: string
  quality_flag: string
  quality_score: number
  grid_id: string
}

/** Properties on `/map/fire` features. */
export interface ApiFireProperties {
  source_id: string
  frp: number
  confidence: number
  sensor?: string
  observed_at: string
  quality_score?: number
  grid_id?: string
}

/** Properties on `/map/weather` features. */
export interface ApiWeatherProperties {
  source_id: string
  wind_u: number | null
  wind_v: number | null
  temperature?: number | null
  humidity?: number | null
  pressure?: number | null
  boundary_layer_height?: number | null
  observed_at: string
  quality_score?: number
  grid_id?: string
}

/** `graph.v1` from `GET /api/v1/events/{id}/graph`. */
export interface ApiGraphVertex {
  id: string
  type: string
  properties?: Record<string, unknown>
}

export interface ApiGraphEdge {
  edge_id: string
  edge_type: string
  from_id: string
  to_id: string
  confidence: number
  evidence_ids?: string[]
}

export interface ApiGraph {
  schema_version?: 'graph.v1'
  event_id: string
  vertices: ApiGraphVertex[]
  edges: ApiGraphEdge[]
}
