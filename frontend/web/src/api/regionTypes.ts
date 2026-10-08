/**
 * Wire shapes of the region-scoped API (LLD APAC section 12).
 *
 * Only the fields the UI reads. Nullable means the API may send null, and the
 * UI must then show "—" with the reason from `field_status`.
 */

export type ProvenanceClass =
  | 'measured'
  | 'model_derived'
  | 'predicted'
  | 'simulated'
  | 'heuristic'
  | 'ai_observation'
  | 'citizen'

export interface FieldStatus {
  field: string
  reason: string
}

export interface DataSource {
  kind: 'snapshot' | 'not_configured' | string
  region_id: string
  cycle_id?: string
  cycle_time?: string
  mode?: string
  pack_version?: string
  reason?: string
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number | null
  offset: number
  region_id?: string
  data_source?: DataSource
  field_status?: FieldStatus[]
  status?: string
  reason?: string
}

export interface Feature<P, G = { type: string; coordinates: unknown }> {
  type: 'Feature'
  geometry: G
  properties: P
}

export interface Collection<P> {
  type: 'FeatureCollection'
  generated_at: string
  data_source?: DataSource
  field_status?: FieldStatus[]
  features: Feature<P>[]
}

export interface AqiBand {
  key: string
  label: string
  low: number
  high: number | null
  colour: string | null
}

export interface AqiStandard {
  key: string
  name: string
  status: 'confirmed' | 'unconfirmed' | string
  reason: string | null
  unit: string
  averaging: string | null
  bands: AqiBand[]
  hazard_label: string | null
  source_url: string | null
}

export interface Hazard {
  key: string
  display_name: string
  explainer: string
  source_class: string
}

export interface ServedModel {
  family: string
  model_version: string
  feature_version: string | null
  degraded: boolean
  degraded_reason: string | null
  calibrated: boolean
  verified_by_cycle?: boolean
}

export interface SourceHealth {
  source_id: string
  domain: string
  enabled: boolean
  state: string
  records: number | null
  last_success_at: string | null
  reason: string | null
  secret_ref: string | null
  field_status: FieldStatus[]
}

export interface Region {
  region_id: string
  display_name: string
  country_codes: string[]
  timezone: string
  default: boolean
  pack_version: string
  bbox: [number, number, number, number]
  source_domain_bbox: [number, number, number, number]
  map_view: { lat: number; lon: number; zoom: number }
  ground_truth: string
  aqi_standard: AqiStandard
  hazards: Hazard[]
  snapshot: DataSource | null
  served_models: ServedModel[] | null
  field_status: FieldStatus[]
  sources?: SourceHealth[]
  snapshot_field_status?: FieldStatus[]
}

export interface GridCell {
  grid_id: string
  lat: number
  lon: number
  pm25: number | null
  pm25_source_id: string | null
  observed_at: string | null
  provenance_class: ProvenanceClass | null
  aqi_band: { key: string; label: string } | null
  field_status: FieldStatus[]
}

export interface FireCluster {
  cluster_id: string
  grid_id: string
  frp: number | null
  detection_count: number
  first_seen: string
  observed_at: string
  provenance_class: ProvenanceClass
  source_id: string
}

export interface WindVector {
  site_id: string
  wind_u: number
  wind_v: number
  level: string
  observed_at: string
  provenance_class: ProvenanceClass
}

export interface ForecastPoint {
  grid_id: string
  horizon_hours: number
  /** Present on snapshot rows. Advection rows carry `generated_at` instead. */
  valid_at?: string | null
  p10?: number | null
  /** Median, when a quantile model served one. */
  p50?: number | null
  p90?: number | null
  /** Point forecast from wind advection. Not a quantile. */
  pm25?: number | null
  event_id?: string | null
  generated_at?: string | null
  model_version: string
  feature_version?: string | null
  degraded?: boolean
  degraded_reason?: string | null
  provenance_class?: ProvenanceClass
}

export interface HazardPoint {
  grid_id: string
  horizon_hours: number
  score: number
  threshold_ugm3: number | null
  calibrated: boolean
  model_version: string
  degraded: boolean
  degraded_reason: string | null
  provenance_class: ProvenanceClass
}

export interface LikelihoodEntry {
  grid_id: string
  valid_at: string
  method_version: string
  calibrated: boolean
  provenance_class: ProvenanceClass
  ranking: { source_class: string; score: number; contributing_signals: string[] }[]
  evidence: {
    signal: string
    value: number | string | boolean | null
    unit: string | null
    source_id: string | null
    observed_at: string | null
  }[]
}

export interface PlumeHorizon {
  horizon_hours: number
  p50_cells: string[]
  p90_cells: string[]
  centroid_lat: number | null
  centroid_lon: number | null
  weight_remaining: number
}

export interface PlumeArrival {
  place_id: string
  name: string
  lat: number
  lon: number
  probability: number
  eta_hours_median: number | null
  population: number | null
}

export interface Plume {
  plume_id: string
  region_id: string
  direction: 'forward' | 'backward'
  label: string
  model_version: string
  provenance_class: ProvenanceClass
  experimental: boolean
  degraded: boolean
  degraded_reasons: string[]
  release_time: string
  origin: { kind: string; ref_id: string | null; lat: number; lon: number }
  horizons: PlumeHorizon[]
  arrivals: PlumeArrival[]
  exposure: unknown[]
  source_candidates: unknown[]
  incident_id?: string | null
}

export interface PlumePage extends Page<Plume> {
  label: string
}

export interface PollutionEvent {
  event_id: string
  event_type: string
  status: string
  severity: string
  geometry: string | null
  grid_ids: string[]
  pollutants: string[]
  detection_confidence: number | null
  source_confidence: number | null
  forecast_confidence: number | null
  impact_confidence: number | null
  overall_confidence: number | null
  sensor_coverage: number | null
  evidence_ids: string[]
  model_versions: string[]
  created_at: string
  updated_at: string
}

export interface IncidentSummary {
  incident_id: string
  region_id: string
  root_kind: string
  first_seen: string
  last_updated: string
  node_count: number
  edge_count: number
  node_ids: string[]
  place_ids_reached: string[]
}

export interface GraphValue {
  value: number | string | boolean | null
  unit: string | null
  provenance_class: ProvenanceClass | null
  source_id: string | null
  observed_at: string | null
}

export interface GraphNode {
  node_id: string
  kind: string
  region_id: string
  valid_from: string
  valid_to: string | null
  attributes: Record<string, GraphValue | unknown>
}

export interface GraphEdge {
  edge_id: string
  kind: string
  src: string
  dst: string
  producer: string
  provenance_class: ProvenanceClass
  cycle_time: string
  attributes: Record<string, unknown>
}

export interface Incident {
  incident_id: string
  region_id: string
  root_kind: string
  first_seen: string
  last_updated: string
  node_ids: string[]
  place_ids_reached: string[]
  nodes: GraphNode[]
  edges: GraphEdge[]
  data_source?: DataSource
}

export interface CitizenReportRow {
  report_id: string
  region_id: string
  status: string
  created_at: string
  recorded_at: string
  lat_rounded: number | null
  lon_rounded: number | null
  visual_class: string | null
  visual_class_provenance: ProvenanceClass | null
  visual_class_source: string | null
  corroboration: string | null
  geo_trust: string | null
  decision: string | null
  moderation: string | null
  plume_id: string | null
  incident_id: string | null
  degraded_reasons: string[]
}

export interface CitizenReportPage extends Page<CitizenReportRow> {
  days: number
}

export interface CitizenSignal {
  signal: string
  supports: boolean
  weight: number
  detail: string
  value: number | string | null
  source_id: string | null
  observed_at: string | null
}

export interface CitizenReportDetail {
  report_id: string
  region_id: string
  status: string
  created_at: string
  claimed_lat?: number
  claimed_lon?: number
  observation_type: string
  notes: string | null
  has_media: boolean
  moderation: string
  moderated_class: string | null
  visual_class: string | null
  visual_class_provenance: ProvenanceClass | null
  analysis?: {
    decision: string
    degraded_reasons: string[]
    observation: {
      visual_class: string
      visual_certainty: string
      scene_summary: string
      likely_source_type: string
      possible_confusers: string[]
      image_quality: string
      observer_version: string
      provenance_class: ProvenanceClass
    } | null
    corroboration: {
      level: string
      score: number
      method_version: string
      provenance_class: ProvenanceClass
      signals: CitizenSignal[]
    } | null
    geo_trust: { level: string; score: number; components: Record<string, number> } | null
    plume_id: string | null
    incident_id: string | null
  } | null
  field_status?: FieldStatus[]
}

export interface CitizenCreated {
  report: CitizenReportDetail
  upload: { method: string; url: string; field?: string; max_bytes: number }
}

export interface CitizenUploaded {
  report_id: string
  status: string
  analysis: string
  field_status?: FieldStatus[]
}

export interface EvaluationRun {
  family: string
  run_id: string
  model_version: string
  region_id: string
  passed: boolean
  metrics: {
    strategy: string | null
    group: string | null
    subject: string | null
    metric: string | null
    value: number | null
    passed: boolean
    region_id: string | null
  }[]
}

export interface CopilotAnswer {
  answer: string
  llm_used: boolean
  model: string | null
  degraded_reason: string | null
  evidence: { source: string; time: string }[]
  tool_calls: { name: string; arguments: Record<string, unknown> }[]
  limitations: string[]
  grounding: { grounded: boolean; numbers_checked: number; ungrounded_values: number[] } | null
  recommended_actions: string[]
}
