# Graph Report - AeroPulse  (2026-09-23)

## Corpus Check
- 292 files · ~244,218 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4726 nodes · 11279 edges · 174 communities (144 shown, 30 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 1169 edges (avg confidence: 0.54)
- Token cost: 118,176 input · 0 output

## Community Hubs (Navigation)
- MapLibre GL Shared Runtime
- MapLibre Symbol Bucket Ops
- Frontend API Adapters
- MapLibre Tile Symbol Placement
- Live Data Hooks & Map UI
- App Router & UI Primitives
- Connector SDK Base & Fixtures
- MapLibre Geometry Clustering
- ML Inference Serving
- ML Feature Sets & Evaluation
- MapLibre Internal Helpers
- Trainer Promotion Gate Tests
- App Shell & Command Palette
- Anomaly Detector Toolkit
- Model Registry Listing API
- Worker Kafka Entrypoint
- Open-Meteo Weather Ingest
- Detect Decision Lab UI
- FastAPI App Factory & CORS
- Connector Replay Runner
- Live API Client Queries
- Timescale Persistence Layer
- Shadow Scoring Pipeline
- MapLibre Line Vertex Arrays
- Population Exposure Lookup
- Event Reader Store
- Feature Spec & Leakage Guards
- Phase 3 Event Detection
- ML Command Line Interface
- MapLibre Protobuf Writers
- Alert & Event Contracts
- Alerts API Endpoint
- MapLibre Vector Tile Geometry
- ULID & Raster Normalization
- MapLibre Collision Debug
- Feature Parity Harness
- Model Registry Lifecycle Tests
- Auth Settings & Roles
- Open-Meteo Contract Tests
- ML Evaluation Holdout Tests
- Detect Workspace Components
- JWT Auth Claims
- Error Types & Role Guards
- Drift Monitor Service
- MapLibre Core Primitives
- Feature Family Tests
- CPCB Connector
- Event State Machine
- Bhuvan Connector
- MapLibre Glyph Sections
- MapLibre Binding Utilities
- Source Likelihood Features
- Event Reader API Tests
- Copilot Response Contracts
- Source Leakage Assertions
- Observability Logging
- MapLibre Buffer Emplacement
- Grid Store API Tests
- PM2.5 Phase 7 Evaluation
- Grid Reader Protocol
- AQI Utilities & Cell Evidence
- Plume Advection Geometry
- MapLibre Expression Conversion
- TypeScript App Config
- Python Workspace Packaging
- API Cache Tests
- Map Router Endpoints
- CAMS Connector
- Frontend HTTP Client
- Hazard API Tests
- Propagation Feature Builders
- Frontend Runtime Dependencies
- MapLibre Cell Coordinates
- Live HTTP Retry Semantics
- Source Classifier Calibration
- In-Memory Grid Reader
- Hazard Store & Peaks
- Node TypeScript Config
- Observation Quality Scoring
- H3 Grid Geospatial Core
- Drift API Tests
- Multi-Hour Feature Tests
- Propagation Config Loader
- Drift Monitor Tests
- Source Registration API
- Conformal Prediction Intervals
- Timescale Map Reader Tests
- Frontend Dev Tooling
- Circuit Breaker
- Snapshot Air Quality Index
- Propagation Time Guards
- Propagation Baselines & Splits
- Prediction Contracts
- Prometheus Domain Metrics
- Punjab Demo Seed Replay
- Drift Findings Report
- Architecture Doc & ADRs
- API Response Cache
- Data Contract Docs
- Docker Compose Packing
- API Auth Documentation
- Frontend Brand Assets
- Distribution Drift Statistics
- Live HTTP Clock Fakes
- Worker Intelligence Persistence Tests
- Source Config Loader
- README Source Overview
- Citizen Report Contract
- Propagation Model Registry
- Map Store Properties
- Fixture Map Reader
- Rate Limiter
- Anomaly Detection Core
- Map Fixture Features
- Live HTTP Errors
- ML Compose Stack
- Shadow Model Loading
- Evidence Quality Service
- Map Reader Protocol
- Retry Policy
- Hardened HTTP Client
- Oxlint Config
- Frontend Package Manifest
- Source Filesystem Registry
- Grid Reader Fallback
- Map Reader Fallback
- Geography Build Script
- Map Store Cursor Fakes
- Baseline Estimator ADR
- Initial Database Schema
- Fake Map Reader
- Integrated Advection Wind
- Hazard Contracts
- Drift Value Reader
- Hazard Stub Reader
- Regressor Hyperparameters
- Weak Supervision Labeling
- Copilot No-LLM ADR
- Live Mode Test Fixture
- Quantile Regression Bundle
- Beta Calibrator
- Phase 3 Schema Migration
- Deprecated Model Registry Shim
- Station Climatology Baseline
- Vite Build Config
- Phase 4 Schema Migration
- Low Level Design Overview
- Rolling Origin Folds
- IMD Source Config
- TypeScript Project References
- Source Promotion Gates
- Connector App Package
- Worker Package
- MODIS AOD Caveat
- deck.gl Dependency
- React DOM Dependency
- React Router Dependency
- Recharts Dependency
- CI OpenAPI Export
- Shadow Prediction Migration
- JWT Algorithm Note
- CAMS Source Config
- Sentinel-5P Source Config
- FastAPI Depends Symbol
- Pytest Fixture Symbol
- Pydantic BaseModel Symbol
- Anomaly Notebook Entry
- Source Likelihood Notebook Entry
- Typing Protocol Symbol
- AeroPulse Project Root
- Generic Type Var

## God Nodes (most connected - your core abstractions)
1. `push()` - 154 edges
2. `ModelRegistry` - 90 edges
3. `get()` - 66 edges
4. `constructor()` - 58 edges
5. `a()` - 57 edges
6. `r()` - 55 edges
7. `i()` - 54 edges
8. `cn()` - 52 edges
9. `GridFeature` - 52 edges
10. `AeroMap()` - 51 edges

## Surprising Connections (you probably didn't know these)
- `api container` --semantically_similar_to--> `api Compose service aeropulse-api`  [INFERRED] [semantically similar]
  docs/adr/0001-compose-packing.md → infrastructure/docker/compose.yaml
- `test_bhuvan_icar_industry_osm()` --uses--> `FetchRequest`  [INFERRED]
  tests/contract/test_geo_connectors.py → libs/connector_sdk/aeropulse_connector_sdk/contracts.py
- `connector container` --semantically_similar_to--> `connector Compose service aeropulse-connector`  [INFERRED] [semantically similar]
  docs/adr/0001-compose-packing.md → infrastructure/docker/compose.yaml
- `worker container` --semantically_similar_to--> `worker Compose service aeropulse-worker`  [INFERRED] [semantically similar]
  docs/adr/0001-compose-packing.md → infrastructure/docker/compose.yaml
- `Source CPCB` --semantically_similar_to--> `CPCB connector`  [INFERRED] [semantically similar]
  config/sources.yaml → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Vite + React Starter Default Asset Set (unreplaced template branding)** — frontend_web_public_favicon_favicon, frontend_web_src_assets_hero_hero, frontend_web_src_assets_react_react, frontend_web_src_assets_vite_vite, frontend_web_src_assets_vite_starter_template_branding [INFERRED 0.85]
- **Social/External-Link Icon Symbols in Shared Sprite** — frontend_web_public_icons_bluesky_icon, frontend_web_public_icons_discord_icon, frontend_web_public_icons_github_icon, frontend_web_public_icons_x_icon, frontend_web_public_icons_social_icon, frontend_web_public_icons_documentation_icon, frontend_web_public_icons_sprite [EXTRACTED 1.00]
- **Core replay sources** — config_sources_cpcb, config_sources_firms, config_sources_imd [EXTRACTED 1.00]
- **ML notebook suite** — ml_notebooks_pm25, ml_notebooks_anomaly, ml_notebooks_likelihood, ml_notebooks_forecast [EXTRACTED 1.00]

## Communities (174 total, 30 thin omitted)

### Community 0 - "MapLibre GL Shared Runtime"
Cohesion: 0.01
Nodes (170): Ab(), ai(), bb(), bf, Bi, bl(), br(), bt (+162 more)

### Community 1 - "MapLibre Symbol Bucket Ops"
Cohesion: 0.02
Nodes (124): ac(), add(), addFeatures(), addImages(), addIndicesForPlacedSymbol(), addLineDashDependencies(), ay(), backfillBorder() (+116 more)

### Community 2 - "Frontend API Adapters"
Cohesion: 0.04
Nodes (107): graphNodeType(), labelForType(), LIVE_UNAVAILABLE_EVENT_FIELDS, NODE_TYPES, parsePointWkt(), pct(), stationToGridCell(), STATUSES (+99 more)

### Community 3 - "MapLibre Tile Symbol Placement"
Cohesion: 0.07
Nodes (113): addSymbols(), addTileFeatures(), addToSortKeyRanges(), appendLeaves(), Ar(), as(), ax(), b() (+105 more)

### Community 4 - "Live Data Hooks & Map UI"
Cohesion: 0.05
Nodes (92): liveIndustries(), liveWeather(), Sparkline(), trace(), AeroMap(), boundsFor(), CORRIDOR_VIEW, GLOBE_VIEW (+84 more)

### Community 5 - "App Router & UI Primitives"
Cohesion: 0.07
Nodes (65): AppRouter(), queryClient, labelStyles, ScientificBadge(), StatusBadge(), Card(), CardBody(), CardHeader() (+57 more)

### Community 6 - "Connector SDK Base & Fixtures"
Cohesion: 0.04
Nodes (65): ABC, CPCB connector: maps station pollutant snapshots to observation.v1., Yield one raw record per station in the replay fixture., FirmsConnector, DataConnector, Path, FIRMS connector: maps VIIRS fire detections to fire_observation.v1., Reads FIRMS-like fire detection payloads from fixtures or live JSON. (+57 more)

### Community 7 - "MapLibre Geometry Clustering"
Cohesion: 0.04
Nodes (94): ad(), ag(), ah(), at(), av(), bh(), cluster(), _convertIndices() (+86 more)

### Community 8 - "ML Inference Serving"
Cohesion: 0.05
Nodes (80): cmd_predict(), Run the champion models over the latest available grid-hour., feature_completeness(), FeatureContractMismatchError, _insufficient_features(), ModelBundleCache, predict_anomaly(), predict_forecast() (+72 more)

### Community 9 - "ML Feature Sets & Evaluation"
Cohesion: 0.06
Nodes (80): FeatureSet, An ordered, named feature list bound to exactly one prediction target.…, classification_metrics(), ClassificationReport, detection_metrics(), Any, DataFrame, ranking_metrics() (+72 more)

### Community 10 - "MapLibre Internal Helpers"
Cohesion: 0.05
Nodes (63): an(), bn(), en(), et(), fn(), gn(), Hn, I (+55 more)

### Community 11 - "Trainer Promotion Gate Tests"
Cohesion: 0.05
Nodes (70): code_commit(), Return the current git commit, or ``unknown`` outside a checkout. Recorded on…, evaluate_promotion_gate(), Return the reasons a model must not be promoted, empty if it may be. Metrics…, Write a training result into the registry, applying the promotion gate. Args:…, register_result(), _frame(), _hazard_result() (+62 more)

### Community 12 - "App Shell & Command Palette"
Cohesion: 0.06
Nodes (51): liveEvent(), ActionBriefProps, AppShell(), CommandPalette(), PaletteDialog(), DemoOverlay(), phaseMessages, JudgeTourDriver() (+43 more)

### Community 13 - "Anomaly Detector Toolkit"
Cohesion: 0.05
Nodes (57): angular_difference_deg(), apply_alert_policy(), assert_unique_columns(), attach(), bearing_deg(), build_events(), build_fire_transport_cubes(), build_region_key() (+49 more)

### Community 14 - "Model Registry Listing API"
Cohesion: 0.06
Nodes (52): list_models(), Depends, ge, get, get_claims, le, Query, Classify how a record participates in serving. Args: record: Registry record.… (+44 more)

### Community 15 - "Worker Kafka Entrypoint"
Cohesion: 0.06
Nodes (54): _handle(), _init_shadow_scorer(), main(), _persist_intelligence(), Any, Worker entrypoint: consume Kafka envelopes and persist observations. When Kafka…, Best-effort Timescale write for events, graphs, forecasts, features, and health., Score registered challengers on this pass and record the result. Runs *after*… (+46 more)

### Community 16 - "Open-Meteo Weather Ingest"
Cohesion: 0.05
Nodes (43): Insert or ignore a weather row. Returns True if inserted., Store weather if the dedup key is new., Keep raster metadata in the snapshot., Observation, Map a station snapshot into one Observation per pollutant., _confidence_to_unit(), Map a FIRMS detection to a canonical fire observation., Map a weather snapshot to a canonical meteorological observation. (+35 more)

### Community 17 - "Detect Decision Lab UI"
Cohesion: 0.06
Nodes (51): liveCopilot(), applyDetectScenario(), applyHorizon(), DETECT_HORIZONS, DETECT_SCENARIOS, DetectDecisionLab(), DetectHorizon, DetectScenario (+43 more)

### Community 18 - "FastAPI App Factory & CORS"
Cohesion: 0.06
Nodes (47): _allowed_request_origin(), _apply_cors(), _cors_origins(), Request, FastAPI application factory., Local UI, the Netlify demo, plus any extra hosts from env., Return the request Origin when it is on the allow-list, else None., Stamp CORS on responses built outside CORSMiddleware. `@app.middleware("http")`… (+39 more)

### Community 19 - "Connector Replay Runner"
Cohesion: 0.06
Nodes (53): main(), _publish_kafka(), Path, Connector process entrypoint., Run one replay cycle and publish to Kafka when the broker is reachable., _stdout_publish(), _checkpoint_cursor(), _checkpoint_key() (+45 more)

### Community 20 - "Live API Client Queries"
Cohesion: 0.07
Nodes (51): clearLiveCaches(), liveAttachCitizenPhoto(), liveCitizenReports(), liveCreateCitizenReport(), liveForecast(), liveRiskAreas(), primaryEventId(), toRiskBand() (+43 more)

### Community 21 - "Timescale Persistence Layer"
Cohesion: 0.04
Nodes (31): Any, EvidenceGraph, GridPrediction, Observation, PollutionEvent, Timescale persistence for observations, events, forecasts, and lineage., psycopg-backed observation and intelligence repository., Insert air quality; return False on duplicate key. (+23 more)

### Community 22 - "Shadow Scoring Pipeline"
Cohesion: 0.07
Nodes (43): comparison_report(), feature_vector_hash(), Any, ModelRegistry, Scores every registered challenger against the live feature stream. Args:…, Load every challenger artifact up front. Cold loading measured 1.3 s against…, Load and contract-check one challenger artifact. Args: record: Registry record…, Return the loaded challengers as family to version. (+35 more)

### Community 23 - "MapLibre Line Vertex Arrays"
Cohesion: 0.06
Nodes (49): addCurrentVertex(), addFeature(), addHalfVertex(), addLine(), addToLineVertexArray(), angleTo(), angleWith(), angleWithSep() (+41 more)

### Community 24 - "Population Exposure Lookup"
Cohesion: 0.06
Nodes (45): _haversine_km(), population_density(), PopulationEstimate, Path, Gridded population density lookup (LLD §18.5, gap analysis P1-4). Exposure was…, Locate the population fixture, honouring the env override. Searched rather than…, Load the reference dataset once per process. Returns: ``(points, source_id)``.…, Resolve population density for a point. Args: lat: Latitude in degrees. lon:… (+37 more)

### Community 25 - "Event Reader Store"
Cohesion: 0.07
Nodes (21): InMemoryEventReader, Any, EventStatus, EvidenceGraph, PollutionEvent, Timescale when it has events; otherwise the in-memory Punjab replay. Compose…, Read the process-local store used by unit tests and DB-free development., Read worker-persisted intelligence from one request-scoped connection. (+13 more)

### Community 26 - "Feature Spec & Leakage Guards"
Cohesion: 0.06
Nodes (42): _assert_no_target_leakage(), calendar_encodings(), _derivation_closure(), datetime, Canonical ML feature specification shared by training and serving. This module…, Return cyclical hour-of-day and day-of-year encodings. Sine/cosine pairs are…, Return calendar flags derived from the feature timestamp. Both are pure…, Flatten a :class:`GridFeature` into every derivable model input. The returned… (+34 more)

### Community 27 - "Phase 3 Event Detection"
Cohesion: 0.09
Nodes (40): _cams_pm25(), _has_nearby_station(), process_snapshot(), PollutionEvent, Run Phase 3 scoring over a feature snapshot., Build features, score, and evaluate events for every cell with PM2.5. Args:…, build_features(), _cell_pm25_history() (+32 more)

### Community 28 - "ML Command Line Interface"
Cohesion: 0.08
Nodes (41): ArgumentParser, build_parser(), cmd_drift(), cmd_models(), cmd_parity(), cmd_promote(), cmd_train(), _load_frame() (+33 more)

### Community 29 - "MapLibre Protobuf Writers"
Cohesion: 0.07
Nodes (44): f(), jy(), ky, P, qy(), realloc(), writeBoolean(), writeBooleanField() (+36 more)

### Community 30 - "Alert & Event Contracts"
Cohesion: 0.08
Nodes (36): Alert, BaseModel, Canonical alert contract (LLD section 29)., Notification payload. Delivery adapters are out of process., EventConfidence, EventSeverity, PollutionEvent, BaseModel (+28 more)

### Community 31 - "Alerts API Endpoint"
Cohesion: 0.06
Nodes (42): current_store(), Return the process store. Call this at request time — tests replace it., list_alerts(), Depends, ge, get, get_claims, le (+34 more)

### Community 32 - "MapLibre Vector Tile Geometry"
Cohesion: 0.07
Nodes (42): aw(), bbox(), C(), E(), ew(), it(), iw(), loadGeometry() (+34 more)

### Community 33 - "ULID & Raster Normalization"
Cohesion: 0.08
Nodes (35): new_ulid(), Generate a new ULID string, optionally prefixed. Args: prefix: Optional short…, Encode a geospatial asset as raster.v1 metadata (no large arrays)., _opt_float(), Map a product dict to raster.v1. Arrays stay in object storage., FireObservation, FireProperties, BaseModel (+27 more)

### Community 34 - "MapLibre Collision Debug"
Cohesion: 0.07
Nodes (42): _addCollisionDebugVertex(), addCollisionDebugVertices(), addDebugCollisionBoxes(), Af(), ap(), clear(), cp(), createNewSegment() (+34 more)

### Community 35 - "Feature Parity Harness"
Cohesion: 0.07
Nodes (35): _accumulate(), check_parity(), FeatureDivergence, ParityReport, Any, datetime, Observation, Offline/online feature parity harness (integration plan Phase 2). Training and… (+27 more)

### Community 36 - "Model Registry Lifecycle Tests"
Cohesion: 0.10
Nodes (40): ModelStage, StrEnum, Promotion stages from LLD §19., fixture, ModelRegistry, Path, Model registry lifecycle guards., Operators need an escape hatch for incident response. (+32 more)

### Community 37 - "Auth Settings & Roles"
Cohesion: 0.17
Nodes (39): BaseSettings, StrEnum, Platform roles from LLD §35.1., Role, Runtime configuration loaded from ``AEROPULSE_`` environment variables., Settings, _auth(), client() (+31 more)

### Community 38 - "Open-Meteo Contract Tests"
Cohesion: 0.05
Nodes (39): connector(), normalized(), fixture, parametrize, Contract tests for the Open-Meteo connector. These run against a committed…, LLD 18.1 and caveat 65.5: AOD must never become a surface measurement., A negative concentration means a parsing or scaling error., Both fields were previously unreachable dead schema. (+31 more)

### Community 39 - "ML Evaluation Holdout Tests"
Cohesion: 0.06
Nodes (38): _frame(), DataFrame, parametrize, Holdout and metric guards. LLD §19 forbids random splits on this data. These…, Sanity anchor for the metric implementation., Missing observations must not be scored as zero error., A zero MAE on no data would read as a perfect model., Systematic under-prediction must be visible, not hidden by MAE. (+30 more)

### Community 40 - "Detect Workspace Components"
Cohesion: 0.11
Nodes (27): Skeleton(), ConfidenceMeters(), CATEGORY_ICON, DetectWorkspace(), EvidenceRail(), Tile(), ModelRow(), Band (+19 more)

### Community 41 - "JWT Auth Claims"
Cohesion: 0.08
Nodes (30): get_claims(), Extract and validate a Bearer JWT from the Authorization header. Args:…, get_source(), list_sources(), get, List registered data sources., Return a single source or 404., HTTPAuthorizationCredentials (+22 more)

### Community 42 - "Error Types & Role Guards"
Cohesion: 0.08
Nodes (28): Build a dependency that requires at least one of ``roles``., require(), Exception, AeropulseError, AuthError, ConnectorError, ContractError, QualityError (+20 more)

### Community 43 - "Drift Monitor Service"
Cohesion: 0.08
Nodes (28): main(), monitor_once(), Any, datetime, Periodic feature and prediction distribution drift monitor. The scheduling half…, Evaluate every supported signal once and log actionable shifts. Args: reader:…, Run drift scans at the configured interval while the process is alive., DriftReader (+20 more)

### Community 44 - "MapLibre Core Primitives"
Cohesion: 0.10
Nodes (36): A(), aa(), Ba(), ca(), canonicalID(), da(), distance(), _down() (+28 more)

### Community 45 - "Feature Family Tests"
Cohesion: 0.10
Nodes (35): _build(), _obs(), Observation, Servable feature families added in integration plan Phases 1-2. Two things are…, These two are forecast-only inputs, and must reflect pm25(t)., A single observation has no dispersion; None beats a fabricated 0.0., The classic dispersion product, not an invented composite., Stagnation must stay on [0, 1] at both extremes. (+27 more)

### Community 46 - "CPCB Connector"
Cohesion: 0.06
Nodes (24): DataConnector, Instantiate a connector for a registered source when the fixture is present., _source_connector(), CpcbConnector, DataConnector, Path, Replay connector is healthy when a fixture path is configured., Reads CPCB-like station payloads (replay fixtures or live JSON). (+16 more)

### Community 47 - "Event State Machine"
Cohesion: 0.13
Nodes (30): AnomalyResult, EventSeverity, EventStatus, Event state machine (LLD §21.1)., GridFeature, BaseModel, Canonical grid-hour feature contract (grid-features.v1, LLD §15)., Independent source likelihoods (LLD §18.3). Not a softmax. (+22 more)

### Community 48 - "Bhuvan Connector"
Cohesion: 0.06
Nodes (23): BhuvanConnector, Path, NRSC Bhuvan replay connector., Maps NRSC Bhuvan inventory JSON to raster.v1 metadata., IcarConnector, Path, ICAR replay connector., Maps ICAR inventory JSON to raster.v1 metadata. (+15 more)

### Community 49 - "MapLibre Glyph Sections"
Cohesion: 0.07
Nodes (34): addImageSection(), addTextSection(), _appendSection(), calculateGlyphDependencies(), deserialize(), determineAverageLineWidth(), determineLineBreaks(), freeBufferAfterUpload() (+26 more)

### Community 50 - "MapLibre Binding Utilities"
Cohesion: 0.09
Nodes (34): bind(), bo(), checkSubtype(), co(), Do(), eachChild(), Eo(), er() (+26 more)

### Community 51 - "Source Likelihood Features"
Cohesion: 0.09
Nodes (33): add_evidence_availability(), add_pollutant_features(), add_station_context(), add_transport_features(), build_events(), chrono_split(), conflict_report(), dataset_fingerprint() (+25 more)

### Community 52 - "Event Reader API Tests"
Cohesion: 0.10
Nodes (16): Replace the process store (tests)., reset_event_store(), _Connection, _Cursor, _EmptyTimescale, _event(), Any, EventStatus (+8 more)

### Community 53 - "Copilot Response Contracts"
Cohesion: 0.12
Nodes (25): CopilotConfidence, CopilotResponse, BaseModel, Copilot response contract (LLD section 24.2). Numbers must be evidence-grounded., Structured copilot answer. Empty lists mean no retrieved evidence., Split confidence copied from the event, never invented., _actions(), explain_event() (+17 more)

### Community 54 - "Source Leakage Assertions"
Cohesion: 0.12
Nodes (25): assert_no_label_leakage(), _lf_coarse_ratio(), _lf_crop_season(), _lf_dust_cams(), _lf_dust_meteorology(), _lf_family_prefixes(), _lf_fire_local(), _lf_fire_upwind() (+17 more)

### Community 55 - "Observability Logging"
Cohesion: 0.12
Nodes (23): BoundLogger, Observability helpers: JSON logs, correlation IDs, and OpenTelemetry., _add_service_fields(), _add_trace_context(), bind_context(), configure_logging(), get_logger(), Any (+15 more)

### Community 56 - "MapLibre Buffer Emplacement"
Cohesion: 0.09
Nodes (27): dv(), ei(), emplace(), Eu(), feature(), fv(), getPositionIds(), getPositions() (+19 more)

### Community 57 - "Grid Store API Tests"
Cohesion: 0.12
Nodes (14): _client(), _Connection, _Cursor, _FakeGridReader, _feature(), _prediction(), Any, GridPrediction (+6 more)

### Community 58 - "PM2.5 Phase 7 Evaluation"
Cohesion: 0.09
Nodes (25): breakdown(), calibration_error(), classification_metrics(), event_metrics(), extreme_bias(), majority_class_baseline(), persistence(), Shared evaluation contract for the Phase-7 PM2.5 notebooks (06, 07, 08).… (+17 more)

### Community 59 - "Grid Reader Protocol"
Cohesion: 0.13
Nodes (22): GridReader, Protocol, Read contract for materialized grid intelligence., latest_grid_feature(), latest_grid_hazard(), latest_grid_peak(), latest_grid_prediction(), list_grid_features() (+14 more)

### Community 60 - "AQI Utilities & Cell Evidence"
Cohesion: 0.15
Nodes (20): EventIntelPanel(), copilotQuestionForCell(), evidenceForCell(), bands, MapLegend(), MapPopup(), KpiStrip(), GridCell (+12 more)

### Community 61 - "Plume Advection Geometry"
Cohesion: 0.14
Nodes (22): _advect_cell(), _bearing(), _best_neighbor(), forecast_event(), Kinematic wind-advection forecast (wind-advection-0.1). CAMS residual…, Advect origin PM2.5 along the wind vector onto neighboring H3 cells. Args:…, bearing_deg(), cosine_alignment() (+14 more)

### Community 62 - "MapLibre Expression Conversion"
Cohesion: 0.09
Nodes (24): am(), bm(), cm(), convert(), fromLngLat(), hd(), hm(), im() (+16 more)

### Community 63 - "TypeScript App Config"
Cohesion: 0.08
Nodes (23): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+15 more)

### Community 64 - "Python Workspace Packaging"
Cohesion: 0.37
Nodes (24): aeropulse, aeropulse-api, aeropulse-auth, aeropulse-common, aeropulse-connector-app, aeropulse-connector-bhuvan, aeropulse-connector-cams, aeropulse-connector-cpcb (+16 more)

### Community 65 - "API Cache Tests"
Cohesion: 0.10
Nodes (18): create_app(), Build the AeroPulse API with routers and CORS for the local UI., main(), Uvicorn entrypoint for the API container., Run the API on 0.0.0.0:8000., main(), Export FastAPI OpenAPI 3 document to docs/openapi/openapi.v1.json., Write the OpenAPI spec next to other docs. (+10 more)

### Community 66 - "Map Router Endpoints"
Cohesion: 0.16
Nodes (22): air_quality(), _collection(), fire(), _fixture_assets(), forecast(), grid(), hazard(), industry() (+14 more)

### Community 67 - "CAMS Connector"
Cohesion: 0.10
Nodes (16): CamsConnector, Path, CAMS background composition connector (replay)., Maps CAMS product JSON to raster.v1., ModisConnector, Path, MODIS MAIAC AOD metadata connector (replay). AOD is not surface PM2.5., Maps MODIS AOD product JSON to raster.v1. (+8 more)

### Community 68 - "Frontend HTTP Client"
Cohesion: 0.15
Nodes (16): ADR-0003, ApiError, apiGet(), apiPost(), apiPostForm(), FeatureCollection, ListResponse, MissingTokenError (+8 more)

### Community 69 - "Hazard API Tests"
Cohesion: 0.19
Nodes (21): _auth(), client(), fixture, TestClient, Hazard and peak prediction endpoints (integration plan Phase 6). The plan's…, The map layer is where a number is most likely to be read uncritically., Registering a challenger at SHADOW must not alter any response., "No data" and "no hazard" must not render identically on a map. (+13 more)

### Community 70 - "Propagation Feature Builders"
Cohesion: 0.10
Nodes (19): add_cyclical_time(), add_regime_features(), add_stability_features(), evaluate_promotion(), geographic_blocks(), leakage_scan(), Timestamp, Assign each station to a geographic block via k-means on lat/lon (S24). A… (+11 more)

### Community 71 - "Frontend Runtime Dependencies"
Cohesion: 0.10
Nodes (21): clsx, @deck.gl/core, @deck.gl/layers, @deck.gl/react, framer-motion, dependencies, clsx, @deck.gl/core (+13 more)

### Community 72 - "MapLibre Cell Coordinates"
Cohesion: 0.10
Nodes (21): _convertFromCellCoord(), _convertToCellCoord(), es, expandBy(), _forEachCell(), getId(), insert(), kw() (+13 more)

### Community 73 - "Live HTTP Retry Semantics"
Cohesion: 0.17
Nodes (16): _client(), Any, A 404 is permanent; retrying wastes the source's rate budget., 429 is transient and must be replayed., Connect/read failures are transient., A recovered source must close its breaker., A missing timeout is how connectors hang forever., Records calls and replays a scripted sequence of responses. (+8 more)

### Community 74 - "Source Classifier Calibration"
Cohesion: 0.13
Nodes (13): calibration_metrics(), make_classifier(), ndarray, One binary classifier per source, comparable across families (S21)., A calibrated binary classifier for one source., Calibrated P(source | evidence). Every calibrator takes 1-D input., Fit a calibrator on validation only (plan section 25)., Platt scaling with a 1-D ``predict`` interface. (+5 more)

### Community 75 - "In-Memory Grid Reader"
Cohesion: 0.16
Nodes (9): _filters(), InMemoryGridReader, _prediction(), Any, datetime, GridPrediction, Serve the replay episode's latest features when Timescale is not configured., Read materialized feature and prediction rows from TimescaleDB. (+1 more)

### Community 76 - "Hazard Store & Peaks"
Cohesion: 0.15
Nodes (19): baseline_hazard(), baseline_peak(), hazard_cells(), peak_forecasts(), promoted_version(), _provenance(), Any, Hazard and peak forecast serving (integration plan Phase 6). The governing rule… (+11 more)

### Community 77 - "Node TypeScript Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 78 - "Observation Quality Scoring"
Cohesion: 0.14
Nodes (16): _clip(), evaluate_observation(), BaseModel, datetime, QualityResult, Deterministic data-quality rules (LLD §16.2: configurable weighted score).…, Outcome of quality evaluation for a single observation., Score a scalar observation using range, temporal, and spatial rules. Args:… (+8 more)

### Community 79 - "H3 Grid Geospatial Core"
Cohesion: 0.14
Nodes (17): in_default_aoi(), neighbors(), Deterministic 1 km-scale grid indexing using H3 resolution 8. H3 res 8 has…, Return a stable H3 cell index for a WGS84 point. Args: lat: Latitude in…, Return H3 cells in the k-ring around ``grid_id``, excluding itself., Return True if the point lies inside the default NCR corridor AOI., to_grid_id(), Geospatial helpers: H3 grid IDs and default Indo-Gangetic AOI. (+9 more)

### Community 80 - "Drift API Tests"
Cohesion: 0.14
Nodes (11): _client(), _Connection, _Cursor, _FakeDriftReader, _params(), Any, TestClient, Drift API and Timescale signal reader tests. (+3 more)

### Community 81 - "Multi-Hour Feature Tests"
Cohesion: 0.19
Nodes (19): _grid(), _observation(), Regression tests for time selection in the grid feature builder. The builder…, Co-located weather must be matched to the requested hour., Meteorology far from the feature hour must not be borrowed., A gap in the series must stay a gap, not inherit a neighbour., Point-in-time safety: a window must never contain its own target., The defect affected every pollutant, not just pm25. (+11 more)

### Community 82 - "Propagation Config Loader"
Cohesion: 0.15
Nodes (10): load_config(), PropagationConfig, Any, Path, quality_report(), Read .env (walking upward), build a config, create the directories., Hard contract check. Raises on a violation — training must fail fast., Per-dataset and per-station quality gates. Returns the report dict (S4.2). (+2 more)

### Community 83 - "Drift Monitor Tests"
Cohesion: 0.13
Nodes (16): Scheduled drift sweep (LLD §46, gap analysis P1-12). On-demand drift already…, Overlapping windows would compare a period against itself., Distribution drift is not error drift, and the payload must say so., Explicit two-window reader, avoiding date arithmetic in the stub., Identical distributions must not page anyone., A feed that changes units or scale must be caught., A signal that stopped flowing must not look healthy., Otherwise a single bad column hides drift in every other. (+8 more)

### Community 84 - "Source Registration API"
Cohesion: 0.12
Nodes (18): backfill_source(), BackfillRequest, create_source(), BaseModel, Path, post, Historical replay window (LLD §38)., Return the project root for fixture-backed connector health checks. (+10 more)

### Community 85 - "Conformal Prediction Intervals"
Cohesion: 0.15
Nodes (13): bias_metrics(), conformal_widths(), constrain_prediction(), coverage_metrics(), event_metrics(), ndarray, Treat "will PM2.5 exceed *threshold*" as a classification problem (S27)., Overall vs high-pollution bias (S28). A model that looks fine on aggregate MAE… (+5 more)

### Community 86 - "Timescale Map Reader Tests"
Cohesion: 0.18
Nodes (14): Read latest station/source observations from TimescaleDB., TimescaleMapReader, grid_boundary(), Return a closed GeoJSON longitude/latitude ring for an H3 cell., _client(), _Connection, TestClient, Timescale-backed operational map layer tests. (+6 more)

### Community 87 - "Frontend Dev Tooling"
Cohesion: 0.12
Nodes (17): devDependencies, oxlint, tailwindcss, @tailwindcss/vite, @types/node, @types/react, @types/react-dom, vite (+9 more)

### Community 88 - "Circuit Breaker"
Cohesion: 0.15
Nodes (11): CircuitBreaker, CircuitState, StrEnum, In-process circuit breaker for source isolation. A production deployment can…, Fail-fast after consecutive source errors. Args: failure_threshold: Consecutive…, Return True if a call may proceed., Reset failure count after a successful call., Increment failures and open the circuit when the threshold is hit. (+3 more)

### Community 89 - "Snapshot Air Quality Index"
Cohesion: 0.18
Nodes (10): _hour(), datetime, Observation, Return every cell observing PM2.5 in one hour, with its location. Args: hour:…, Return this cell's observations for one hour. Args: grid_id: H3 cell. hour:…, Return this cell's PM2.5 by hour bucket. Args: grid_id: H3 cell. Returns: Hour…, Return weather observations within a time tolerance of an hour. Args: hour:…, Return raster samples acquired in one hour. Args: hour: Hour-floored timestamp.… (+2 more)

### Community 90 - "Propagation Time Guards"
Cohesion: 0.17
Nodes (14): assert_past_only(), Series, AeroPulse propagation forecasting toolkit. Shared library behind notebooks…, Per-station MAE/RMSE/bias/skill (S25). Aggregate MAE hides the failures., Metrics by concentration band and by dynamic regime (S26)., Builder for a *wall-clock* lag: the value observed exactly ``hours`` ago. Not…, Recompute *column* from the past-only ``builder`` and assert equality.…, Coarse concentration band for per-regime reporting (S26). (+6 more)

### Community 91 - "Propagation Baselines & Splits"
Cohesion: 0.17
Nodes (12): baseline_forecasts(), best_baseline(), chrono_split(), dataset_fingerprint(), PropagationPredictor, DataFrame, Name of the strongest baseline — the bar the ML model has to clear., Chronological split with an *h*-hour purge at each boundary.… (+4 more)

### Community 92 - "Prediction Contracts"
Cohesion: 0.16
Nodes (14): AnomalyResult, GridPrediction, BaseModel, Anomaly detector output (quantile-baseline-0.1)., PM2.5 estimate for a cell (baseline-idw-0.1)., estimate_pm25(), datetime, Baseline inverse-distance PM2.5 estimator (baseline-idw-0.1). AOD is never… (+6 more)

### Community 93 - "Prometheus Domain Metrics"
Cohesion: 0.19
Nodes (14): Low-cardinality Prometheus metrics for AeroPulse HTTP services., Return the matched route template, avoiding IDs in metric labels., route_label(), _counter_value(), _observation(), datetime, Domain metrics actually increment (LLD §33.2, gap analysis P1-9). A declared-…, Read one labelled counter's current value, 0.0 when never incremented. (+6 more)

### Community 94 - "Punjab Demo Seed Replay"
Cohesion: 0.28
Nodes (14): _evidence_for(), _put_cell(), In-memory replay of the Punjab → Delhi episode used by the UI. When Timescale…, Populate the current process store with the UI hero episode if it is empty., _seed_citizen(), _seed_events(), _seed_forecast(), _seed_graph() (+6 more)

### Community 95 - "Drift Findings Report"
Cohesion: 0.14
Nodes (11): DriftFinding, DriftReport, _emit(), Any, Return only the findings that warrant an operator alert., Return signals that had too little data to judge. Worth surfacing separately: a…, Return a JSON-serialisable summary., Log the sweep outcome, one structured line per alerting signal. Alerting goes… (+3 more)

### Community 96 - "Architecture Doc & ADRs"
Cohesion: 0.15
Nodes (14): Canonical contracts, DataConnector, ADR-0002: H3 resolution 8 as the ~1 km analytical grid, grid_id H3 index string, H3 resolution 8 grid, AeroPulse architecture (implemented), grid-features-0.3.0, Redpanda Kafka (+6 more)

### Community 97 - "API Response Cache"
Cohesion: 0.19
Nodes (13): cache_key(), get_cached(), is_cacheable(), Any, Fail-open Redis response cache for bounded read-only API routes., Return whether a request is an allowlisted read endpoint., Build a non-secret key scoped to the full URL and caller token digest., Return cached response and ``hit``/``miss``/``error`` outcome. (+5 more)

### Community 98 - "Data Contract Docs"
Cohesion: 0.15
Nodes (14): Copernicus, raster.v1 output contract, satellite_gas data type, Sentinel-5P connector metadata, event.v1, ADR-0005: Timescale evidence lineage instead of ArangoDB in Phase 4, graph.v1, Events endpoints /api/v1/events (+6 more)

### Community 99 - "Docker Compose Packing"
Cohesion: 0.23
Nodes (14): ADR-0001: Pack logical services into few Compose containers, api container, Compose packing of logical services, connector container, worker container, AeroPulse India web shell, api Compose service aeropulse-api, aeropulse Compose stack (+6 more)

### Community 100 - "API Auth Documentation"
Cohesion: 0.16
Nodes (14): ADR-0003: Development HS256 JWT with RBAC stubs, AEROPULSE_JWT_SECRET, HS256 JWT development auth, OIDC/OAuth2 identity, Alerts and risk endpoints, Citizen endpoints /api/v1/citizen, AeroPulse HTTP API, Map endpoints /api/v1/map (+6 more)

### Community 101 - "Frontend Brand Assets"
Cohesion: 0.18
Nodes (14): AeroPulse Web Favicon (Purple Lightning-Bolt Mark), Accent Purple (#aa3bff) Stroke Icon Convention, bluesky-icon symbol, discord-icon symbol, documentation-icon symbol (stroked outline style), github-icon symbol, social-icon symbol (stroked outline style), SVG Icon Sprite Sheet (symbol/use pattern) (+6 more)

### Community 102 - "Distribution Drift Statistics"
Cohesion: 0.22
Nodes (12): distribution_drift(), _ks_statistic(), _psi(), Any, ndarray, Feature and prediction distribution drift metrics (LLD §46)., Compute PSI and two-sample KS drift with explicit sample-size gates., Distribution-drift metric tests (LLD §46). (+4 more)

### Community 103 - "Live HTTP Clock Fakes"
Cohesion: 0.18
Nodes (10): _FakeClock, Reliability primitives must be wired into the live transport, not merely exist., Burst capacity is spendable, after which callers must wait., A slow poller accumulates permits rather than being penalised., Throttling must be observable, not silent., Guard the documented default so live mode stays opt-in., test_client_records_throttled_seconds(), test_default_settings_are_replay_mode() (+2 more)

### Community 104 - "Worker Intelligence Persistence Tests"
Cohesion: 0.14
Nodes (3): GridPrediction, Fake Timescale writer that records every call it receives., _RecordingWriter

### Community 105 - "Source Config Loader"
Cohesion: 0.26
Nodes (3): load_config(), Path, SourceConfig

### Community 106 - "README Source Overview"
Cohesion: 0.15
Nodes (13): No LLM on event path, Source CPCB, Source FIRMS, CPCB CAAQMS metadata, FIRMS metadata, Propagation forecast notebook, PM2.5 estimator notebook, CPCB connector (+5 more)

### Community 107 - "Citizen Report Contract"
Cohesion: 0.23
Nodes (10): CitizenReport, BaseModel, Citizen report contract (LLD section 23). Corroborative only., Citizen observation. Never opens a HIGH event by itself., classify_report(), Heuristic citizen image labels (LLD section 23). Not a trained CV model., Assign cv_class from whole-word keywords. Unknown if none match., Heuristic citizen CV tests. (+2 more)

### Community 108 - "Propagation Model Registry"
Cohesion: 0.27
Nodes (3): ModelRegistry, Filesystem registry: ``registry/{horizon}h/{version}/``. Each version holds…, ``point_source`` selects what the ``pm25`` field carries. ``"residual_model"``…

### Community 109 - "Map Store Properties"
Cohesion: 0.29
Nodes (6): _aq_properties(), _bbox_where(), _fire_properties(), Any, Read repositories for operational GeoJSON map layers., _weather_properties()

### Community 110 - "Fixture Map Reader"
Cohesion: 0.20
Nodes (4): _filter_bbox(), FixtureMapReader, _point(), DB-free fallback matching the committed connector fixtures.

### Community 111 - "Rate Limiter"
Cohesion: 0.20
Nodes (7): RateLimiter, Per-source client-side rate limiting (LLD §7.1). Sources publish their own…, Token bucket enforcing a sustained rate with a burst allowance. The bucket…, Take one permit if available, without blocking. Returns: True if a permit was…, Block until a permit is available, then take it. Returns: Seconds spent…, A zero rate would deadlock every fetch., test_limiter_rejects_non_positive_rate()

### Community 112 - "Anomaly Detection Core"
Cohesion: 0.26
Nodes (10): _clip(), detect_anomaly(), _percentile(), datetime, Quantile / threshold anomaly detector (quantile-baseline-0.1)., Score a PM2.5 observation against history or an operational threshold. With…, Anomaly detector tests., test_low_quality_does_not_trigger() (+2 more)

### Community 113 - "Map Fixture Features"
Cohesion: 0.27
Nodes (10): air_quality_features(), fire_features(), _point(), Replay GeoJSON used when Timescale has no operational rows. Coordinates and…, FIRMS-shaped detections for the Punjab cluster., IMD-shaped wind samples along the corridor., CPCB-shaped PM2.5 points for the replay episode., weather_features() (+2 more)

### Community 114 - "Live HTTP Errors"
Cohesion: 0.22
Nodes (8): CircuitBreaker, ConnectorError, CircuitOpenError, LiveModeDisabledError, Raised when a source's breaker is open and the call was not attempted., Raised when live HTTP is attempted while the platform is in replay mode., This is the wiring the audit found missing: failures must reach the breaker., test_breaker_opens_after_repeated_failures_and_blocks_calls()

### Community 115 - "ML Compose Stack"
Cohesion: 0.18
Nodes (10): ArangoDB environmental reasoning, evidence_edge lineage rows, Disaster recovery (development / MVP), AEROPULSE_CONNECTOR_MODE replay, ArangoDB Compose profile graph, compose.ml.yaml optional ML extras, MLflow server profile ml, otel-collector observability profile (+2 more)

### Community 116 - "Shadow Model Loading"
Cohesion: 0.22
Nodes (7): LoadedModel, A champion artifact plus the registry record describing it. Attributes: record:…, Return the artifact's baked-in feature order., _PinnedCache, Adapter presenting one preloaded challenger through the cache interface. The…, Return the parent cache's recorded load failures., Return the pinned challenger, or defer to the parent cache.

### Community 117 - "Evidence Quality Service"
Cohesion: 0.27
Nodes (6): evidence_quality(), Series, Production source-likelihood service. Returns independent per-source…, Wording is a safety control, not presentation (plan section 47)., HIGH/MEDIUM/LOW from evidence coverage (S37)., SourceLikelihoodPredictor

### Community 118 - "Map Reader Protocol"
Cohesion: 0.20
Nodes (3): MapReader, Protocol, Read contract for recent operational map observations.

### Community 119 - "Retry Policy"
Cohesion: 0.22
Nodes (9): BaseException, is_retryable(), T, HTTP retry policy with jittered exponential backoff., Return True when an exception represents a transient transport fault. A 4xx…, Retry an HTTP callable on throttling and 5xx/transport faults. Backoff is…, retry_http(), 401/403/404 must never appear in the retry set. (+1 more)

### Community 120 - "Hardened HTTP Client"
Cohesion: 0.24
Nodes (7): Return the shared hardened client, building it on first use., fetch_json(), LiveHttpClient, Any, GET JSON from a live endpoint using a single-use hardened client. Prefer…, Hardened JSON transport scoped to a single upstream source. One instance per…, GET and parse JSON, applying every reliability primitive. Args: url: Absolute…

### Community 121 - "Oxlint Config"
Cohesion: 0.20
Nodes (9): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, typescript, oxc, warn (+1 more)

### Community 122 - "Frontend Package Manifest"
Cohesion: 0.20
Nodes (9): name, private, scripts, build, dev, lint, preview, type (+1 more)

### Community 124 - "Grid Reader Fallback"
Cohesion: 0.33
Nodes (4): get_grid_reader(), Timescale when it has feature rows; otherwise the in-memory Punjab replay.…, Provide a request-scoped Timescale grid reader, or the in-memory replay., ReplayFallbackGridReader

### Community 126 - "Geography Build Script"
Cohesion: 0.25
Nodes (7): BBOX, clipLine(), features, inBox(), json, out, SETS

### Community 128 - "Baseline Estimator ADR"
Cohesion: 0.29
Nodes (8): ADR-0004: Baseline IDW estimator instead of LightGBM in Phase 3, baseline-idw-0.1, LightGBM/XGBoost hyper-local PM2.5, quantile-baseline-0.1, Models in-process registry, wind-advection-0.1, forecast.v1 ForecastResult, prediction.v1 GridPrediction

### Community 129 - "Initial Database Schema"
Cohesion: 0.25
Nodes (7): air_quality_observation, connector_checkpoint, connector_dead_letter, data_source, fire_observation, grid_cell, weather_observation

### Community 131 - "Integrated Advection Wind"
Cohesion: 0.29
Nodes (5): integrated_advection(), (station, month, hour) mean wind vector, fitted on the training window. Used to…, Simulated forecast wind valid at t+lead, known at t., Step-integrated displacement over the forecast window (S12 "MVP+"). Replaces…, WindClimatology

### Community 132 - "Hazard Contracts"
Cohesion: 0.33
Nodes (6): HazardCell, PeakForecast, BaseModel, Hazard and peak forecast contracts (hazard.v1, peak_forecast.v1). These carry…, Probability that one cell reaches the hazard threshold within a horizon., Maximum PM2.5 expected for one cell over a forward window.

### Community 133 - "Drift Value Reader"
Cohesion: 0.33
Nodes (5): DriftValueReader, datetime, Protocol, Scheduled drift evaluation and alerting (LLD §46, gap analysis P1-12). ``GET…, Reads one bounded numeric signal over a time window.

### Community 135 - "Regressor Hyperparameters"
Cohesion: 0.33
Nodes (5): make_regressor(), Map one canonical hyperparameter dict onto each library's spelling. Without…, One factory for every candidate family so the comparison stays fair., translate_params(), HistGradientBoostingRegressor

### Community 136 - "Weak Supervision Labeling"
Cohesion: 0.33
Nodes (6): aggregate_weak_labels(), apply_labeling_functions(), LabelingFunction, One independent heuristic voting on one source. Returns +1 (supports), 0…, Run every LF and return one int8 column per function., Reliability-weighted aggregation into per-source probabilistic labels. For each…

### Community 137 - "Copilot No-LLM ADR"
Cohesion: 0.40
Nodes (6): ADR-0006: Copilot is evidence retrieval, not an LLM in this build, Copilot deterministic retrieval, EventStore, llm_used always false, Copilot endpoints /api/v1/copilot, copilot.v1 CopilotResponse

### Community 138 - "Live Mode Test Fixture"
Cohesion: 0.33
Nodes (6): _live_mode(), fixture, MonkeyPatch, Force live connector mode for these transport tests., The platform default must never silently reach the network., test_replay_mode_blocks_live_calls()

### Community 139 - "Quantile Regression Bundle"
Cohesion: 0.40
Nodes (3): make_quantile_regressor(), QuantileBundle, P10/P50/P90 residual models plus a conformal width correction (S21/S22).

### Community 141 - "Phase 3 Schema Migration"
Cohesion: 0.40
Nodes (4): event_evidence, grid_feature, grid_prediction, pollution_event

### Community 142 - "Deprecated Model Registry Shim"
Cohesion: 0.40
Nodes (4): list_production_models(), Deprecated shim for the former in-process model registry (LLD §19). This module…, Raise, pointing the caller at the registry that replaced this one. Raises:…, NoReturn

### Community 145 - "Phase 4 Schema Migration"
Cohesion: 0.50
Nodes (3): evidence_edge, forecast_value, source_health

### Community 146 - "Low Level Design Overview"
Cohesion: 0.50
Nodes (4): ArangoDB evidence graph, Citizen intelligence, AI Copilot, Pollution event engine

### Community 147 - "Rolling Origin Folds"
Cohesion: 0.67
Nodes (3): Expanding-window folds; each validation block is purged by *h* hours., rolling_origin_folds(), Index

### Community 148 - "IMD Source Config"
Cohesion: 0.67
Nodes (3): Source IMD, IMD metadata, IMD connector

## Knowledge Gaps
- **241 isolated node(s):** `air_quality_observation`, `connector_checkpoint`, `connector_dead_letter`, `data_source`, `fire_observation` (+236 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **30 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FireObservation` connect `Frontend API Adapters` to `Open-Meteo Weather Ingest`, `Detect Decision Lab UI`, `Live Data Hooks & Map UI`, `AQI Utilities & Cell Evidence`?**
  _High betweenness centrality (0.424) - this node is a cross-community bridge._
- **Why does `cn()` connect `Detect Workspace Components` to `Live Data Hooks & Map UI`, `App Router & UI Primitives`, `App Shell & Command Palette`, `Detect Decision Lab UI`, `MapLibre Expression Conversion`?**
  _High betweenness centrality (0.359) - this node is a cross-community bridge._
- **Why does `hm()` connect `MapLibre Expression Conversion` to `MapLibre GL Shared Runtime`, `MapLibre Buffer Emplacement`, `Detect Workspace Components`, `MapLibre Geometry Clustering`?**
  _High betweenness centrality (0.356) - this node is a cross-community bridge._
- **Are the 67 inferred relationships involving `ModelRegistry` (e.g. with `promoted_version()` and `list_models()`) actually correct?**
  _`ModelRegistry` has 67 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `get()` (e.g. with `n()` and `r()`) actually correct?**
  _`get()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `constructor()` (e.g. with `i()` and `n()`) actually correct?**
  _`constructor()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 52 inferred relationships involving `a()` (e.g. with `ah()` and `ax()`) actually correct?**
  _`a()` has 52 INFERRED edges - model-reasoned connections that need verification._