# AeroPulse APAC — Hackathon Low-Level Design

Status: proposal for review. This replaces the hackathon scope of [LLD_AeroPulse_Global.md](LLD_AeroPulse_Global.md). It does not replace that document's long-term design: the Global LLD becomes the **Production Evolution Architecture** (Section 16), and this document is what gets built in the 17-day hackathon window.

> **AeroPulse APAC** — an AI-powered environmental intelligence platform for Asia-Pacific. It combines ground sensors, satellite observations, weather, fire detection, citizen reports and Google AI to work out where pollution comes from, where it is moving, and which communities may be affected.

Read first: [README.md](../README.md) (setup), [architecture.md](architecture.md) (current system), [AGENTS.md](../AGENTS.md) (contributor rules), [LLD_AeroPulse_Global.md](LLD_AeroPulse_Global.md) Section 1 (current-state review; not repeated here).

## How to read this document

- **Section 0** lists what changed from the Global LLD and the decisions that need sign-off before day 1.
- **Sections 1–3** cover the product story, principles, and the reduced Google Cloud architecture.
- **Sections 4–11** are the design: Region Packs, ingestion, data model, ML, plume, citizen AI, the Environmental Intelligence Graph, and the Ask AeroPulse agent.
- **Sections 12–14** cover API and UI, security and cost, and rule changes.
- **Sections 15–17** are the 17-day plan, what is deferred, and open risks.
- **Numbers.** Same rule as the Global LLD. A figure shown as a *result* names the file it came from. A figure shown as a *setting* or *target* is labelled that way and must be tuned before it is quoted to users. External facts (dataset ids, API coverage, AQI tables) are marked "confirm" where they must be checked against the provider. Example outputs use placeholders such as `<n>` or `—`, never invented values.

## Contents

0. [What changed from the Global LLD](#0-what-changed-from-the-global-lld)
1. [Product story](#1-product-story)
2. [Principles and the provenance labels](#2-principles-and-the-provenance-labels)
3. [Hackathon architecture on Google Cloud](#3-hackathon-architecture-on-google-cloud)
4. [APAC Region Packs and hazard profiles](#4-apac-region-packs-and-hazard-profiles)
5. [Data ingestion](#5-data-ingestion)
6. [Data model: BigQuery, Cloud Storage, serving snapshots](#6-data-model-bigquery-cloud-storage-serving-snapshots)
7. [ML: four intelligence strategies](#7-ml-four-intelligence-strategies)
8. [Plume intelligence (the hero feature)](#8-plume-intelligence-the-hero-feature)
9. [Citizen Smoke Intelligence](#9-citizen-smoke-intelligence)
10. [Environmental Intelligence Graph](#10-environmental-intelligence-graph)
11. [Ask AeroPulse agent](#11-ask-aeropulse-agent)
12. [API and the command-centre UI](#12-api-and-the-command-centre-ui)
13. [Security and cost](#13-security-and-cost)
14. [Proposed AGENTS.md amendments](#14-proposed-agentsmd-amendments)
15. [17-day plan and agent workstreams](#15-17-day-plan-and-agent-workstreams)
16. [Production evolution (deferred, not forgotten)](#16-production-evolution-deferred-not-forgotten)
17. [Risks and open questions](#17-risks-and-open-questions)

---

## 0. What changed from the Global LLD

The guiding line: **broad in AI capability, narrow in infrastructure.** About 70% of the Global LLD's thinking is kept; about 30–40% of it is built now.

### 0.1 Kept, simplified, deferred, new

| Area | Global LLD | APAC hackathon build |
| --- | --- | --- |
| Positioning | Any city, country or continent | **Three APAC regions**: North India, Singapore, Sydney / NSW |
| Region Packs | Built | **Built, and made the headline capability** ("no application code changes") |
| Hazard profiles | Seasonal priors only | **New**: crop burning, transboundary haze, bushfire smoke, urban pollution, dust |
| Cross-border sources | Not modelled | **New**: a region's *source domain* can be larger than its display area (Sumatra and Borneo fires for Singapore) |
| Connectors | Entry-point plugins, many sources | Plugins kept; only OpenAQ, FIRMS, Open-Meteo, Earth Engine are built. AirNow, EEA, PurpleAir dropped. |
| Earth Engine | Eight products | **Two or three**: Sentinel-5P aerosol index, WorldPop; Sentinel-5P CO as a stretch |
| Serving store | Cloud SQL + PostGIS | **Removed.** Precomputed serving snapshots in Cloud Storage plus BigQuery for history |
| Cache | Memorystore | **Removed.** In-process cache in Cloud Run |
| Pub/Sub | Twelve topics plus DLQs | **Two topics**: citizen reports, alerts (plus one dead-letter topic) |
| Worker / detector split | Push worker plus detector job | **One Cloud Run Job per region per cycle**: fetch, normalize, detect, plume, snapshot |
| ML families | Six, with nowcast kriging | **Four**: PM2.5 forecast, 24 h hazard, anomaly, source likelihood. One pooled model per family. |
| Evaluation | Five split types | **Two plus one**: purged rolling-origin, leave-region-out, and a season check where data allows |
| Promotion | Shadow, canary, live gate, auto-demotion | **One reviewed file** (`config/model_serving.yaml`) that may only point at a passing gate report |
| Training | Vertex AI Pipelines + Model Registry | **One Vertex AI custom training job** (or local run); artifacts in Cloud Storage |
| Plume | Lagrangian ensemble, forward and backward | **Kept in full**; settings reduced for cost |
| Citizen photo | AutoML detector decides, Gemini describes | **Gemini multimodal gives a visual observation; deterministic environmental corroboration decides what happens next.** No detector training. |
| Privacy filter | SafeSearch, face and plate blur | **Deferred.** Photos are visible only to operators and the uploader until it exists. |
| Ask AeroPulse | Region-aware, four new tools | **Expanded into an agent** with 16 tools, including an incident-graph tool |
| Knowledge graph | — | **New**: Environmental Intelligence Graph, logical only (BigQuery tables plus snapshot), no graph database |
| ML evaluation page | Models page per region | **New dedicated page**, filled only from real evaluation reports |
| Terraform | Thirteen modules, two environments | **One environment**, the modules the build actually uses |

### 0.2 Decisions that need sign-off before day 1

1. **Gemini on the citizen-photo path.** The feedback asks for Gemini multimodal as the first visual analysis instead of a trained detector. Today's rules say Ask AeroPulse is the only LLM surface. Section 9 keeps pollution *events* free of any language model and confines Gemini's output to a separate, labelled "AI visual observation" track. It still needs the rule change in Section 14. If the team rejects it, the fallback is in Section 9.9.
2. **No serving database.** Live map reads come from snapshots written by the cycle job. If the day-4 latency check fails (Section 6.5), a serving store is added then, not before.
3. **AQI standards follow the region.** Singapore and NSW labels must use their own official scales. This also needs a rule change (Section 14).
4. **Three regions only**: `in-north`, `sg-singapore`, `au-nsw`. A fourth is a stretch goal and must arrive as a pack only, with no code change, or it does not ship.

---

## 1. Product story

### 1.1 Observe → Understand → Predict → Reason → Act

| Stage | What AeroPulse does | Built from |
| --- | --- | --- |
| **Observe** | Ground sensors, satellites, weather, fires, citizen photos | OpenAQ, Open-Meteo, FIRMS, Earth Engine, citizen uploads |
| **Understand** | Anomalies, likely sources, relationships between fires, air and places | Anomaly model, source likelihood, Environmental Intelligence Graph |
| **Predict** | PM2.5 for the next 1–24 h, 24 h hazard, smoke transport, population exposure | Forecast model, hazard model, Lagrangian plume, WorldPop |
| **Reason** | Plain-language answers grounded in tool results | Gemini agent with tools and a grounding validator |
| **Act** | Alerts, affected places with arrival times, citizen watches | Alerts topic, incident view, operator queue |

The shift is from **"AQI dashboard"** to **pollution source → atmospheric transport → population impact**.

### 1.2 Three regions, one platform

| Region pack | Main scenario | Hazard profiles | AQI standard |
| --- | --- | --- | --- |
| `in-north` (Punjab–Haryana–Delhi NCR) | Crop-residue burning, urban pollution, dust | `crop_residue_burning`, `urban_pollution`, `dust` | CPCB (India) |
| `sg-singapore` | Transboundary haze from fires in neighbouring countries | `transboundary_haze`, `urban_pollution` | NEA (Singapore) — confirm which index (Section 4.4) |
| `au-nsw` (Sydney / NSW) | Bushfire smoke reaching cities | `bushfire_smoke`, `urban_pollution`, `dust` | NSW Air Quality Categories — confirm (Section 4.4) |

Headline message for judges: **same AI platform, different geography, different environmental conditions, different AQI standards — no application code changes.**

### 1.3 The demo narrative

```mermaid
flowchart LR
  A["Select Singapore"] --> B["PM2.5 rising above expected range - anomaly"]
  B --> C["Backward plume finds fire clusters upwind"]
  C --> D["Source likelihood: transboundary haze, with evidence"]
  D --> E["Forward plume: footprint, arrival times, exposed population"]
  E --> F["Citizen uploads smoke or haze photo"]
  F --> G["Gemini visual observation + FIRMS, wind, PM2.5 corroboration"]
  G --> H["Incident updated in the graph"]
  H --> I["Ask: where is this smoke coming from and where will it go next?"]
```

Every step in this flow must work in **Live** for at least one region and in **Demo** for all three (Section 15.4). If a Live step fails on stage, the presenter switches to Demo and the banner says so. Demo is never shown under a Live banner.

---

## 2. Principles and the provenance labels

### 2.1 Kept from the current build (non-negotiable)

- Vendor JSON stops at `normalize()`. Only shared contracts travel further.
- Missing live key means *not configured* and zero records. Never a silent fixture.
- No language model on detection, anomaly, likelihood, forecast, or plume. Gemini explains and orchestrates; deterministic code and trained models calculate.
- Every served prediction states its version and whether it is degraded. Hazard also states whether it is calibrated; an uncalibrated hazard is a rank.
- Ground stations outrank model-derived values (CAMS) for the same cell-hour. CAMS is never a label.
- A model is served only if it beats an honest baseline. Gates are never lowered.
- Demo works with no API. Live never paints Demo data. Missing fields show "—" with a reason.

### 2.2 Provenance classes (new, shown everywhere)

The feedback asks for a clear separation between measured, predicted, and AI-generated information. Every value in the snapshot, API, graph, and agent ledger carries one `provenance_class`. The UI uses one consistent badge per class.

| `provenance_class` | Meaning | Examples | UI label |
| --- | --- | --- | --- |
| `measured` | A reference instrument or satellite retrieval | OpenAQ reference monitor, FIRMS hotspot, S5P aerosol index | "Measured" |
| `model_derived` | Output of an external physical model | CAMS PM2.5 via Open-Meteo, Open-Meteo wind forecast | "Model output (CAMS / forecast)" |
| `predicted` | AeroPulse ML model | PM2.5 forecast, hazard, anomaly | "Predicted · model version · calibrated / rank" |
| `simulated` | AeroPulse physics | Plume footprint, arrival time, exposed population | "Simulated · experimental" until Section 8.7 metrics exist |
| `heuristic` | Transparent rule with configured weights | Source likelihood, corroboration score | "Heuristic score" |
| `ai_observation` | Gemini output | Citizen-photo visual observation, agent prose | "AI observation — requires corroboration" |
| `citizen` | Unverified human input | Report location, notes | "Citizen report" |

Contract change: `provenance_class: ProvenanceClass` is added to `Provenance` in `libs/contracts`. The grounding validator (Section 11.4) refuses an answer that presents an `ai_observation` or `simulated` value as `measured`.

---

## 3. Hackathon architecture on Google Cloud

### 3.1 Picture

```mermaid
flowchart TB
  subgraph packs [APAC Region Packs]
    IN["in-north"]
    SG["sg-singapore"]
    AU["au-nsw"]
  end
  subgraph ingest [Cycle - Cloud Run Job per region]
    SCH["Cloud Scheduler"] --> CYC["aeropulse-cycle --region R"]
    CYC --> FETCH["Connectors: OpenAQ, FIRMS, Open-Meteo, Earth Engine"]
    FETCH --> NORM["normalize to contracts"]
    NORM --> DETECT["Detect, ML score, source likelihood"]
    DETECT --> PLUME["Plume engine forward and backward"]
    PLUME --> GRAPH["Environmental Intelligence Graph"]
  end
  subgraph store [Storage]
    GCS[("Cloud Storage: raw, photos, models, snapshots")]
    BQ[("BigQuery: history, features, labels, predictions, eval, graph")]
  end
  subgraph citizen [Citizen AI]
    UP["Signed URL upload"] --> CPS["Pub/Sub aero.citizen.reports"]
    CPS --> CA["citizen-analyzer Cloud Run"]
    CA --> GEMV["Gemini multimodal - visual observation"]
    CA --> CORR["Corroboration: FIRMS, wind, PM2.5, S5P"]
  end
  subgraph serve [Serving]
    API["Cloud Run API"] --> WEB["Cloud Run web"]
    API --> AGENT["Ask AeroPulse agent - Gemini on Vertex AI"]
  end
  EE["Earth Engine"] --> FETCH
  VTX["Vertex AI custom training job"] --> GCS
  packs --> CYC
  NORM --> BQ
  NORM --> GCS
  GRAPH --> GCS
  GRAPH --> BQ
  CORR --> PLUME2["Plume seeded from report"]
  CA --> BQ
  CA --> ALR["Pub/Sub aero.alerts"]
  PLUME --> ALR
  GCS --> API
  BQ --> API
  BQ --> VTX
```

### 3.2 Components

| Component | Google Cloud | Local (dev / Demo) | Responsibility |
| --- | --- | --- | --- |
| Region registry | `config/regions/*` baked into images | Same files | Geography, timezone, AQI standard, hazards, sources |
| Scheduler | Cloud Scheduler, one entry per region | `apps/connector` interval loop | Start a cycle per region on its cadence (setting: 15 min) |
| Cycle job | Cloud Run Job `aeropulse-cycle --region R` | Same CLI in Compose | Fetch due sources, normalize, write, detect, score, plume, graph, snapshot |
| History and analytics | BigQuery | Parquet files under `var/` | Observations, forecasts, features, labels, predictions, evaluation, graph |
| Objects | Cloud Storage (four buckets, Section 6.2) | MinIO | Raw payloads, photos, model artifacts, serving snapshots |
| Citizen analyzer | Cloud Run service with Pub/Sub push | Same app in Compose, local queue | Sanitize, Gemini observation, corroboration, plume seed |
| Events bus | Pub/Sub: `aero.citizen.reports`, `aero.alerts`, one DLQ | Redpanda (existing) | Only where asynchronous work adds visible value |
| API | Cloud Run service | `apps/api` | Reads snapshots and BigQuery; citizen upload; agent |
| Web | Cloud Run service (static build) | Vite dev server | Command-centre UI, Demo and Live |
| LLM | Gemini on Vertex AI (ADC) | `google-genai` with API key | Agent and citizen visual observation |
| Training | Vertex AI custom training job, one container | `uv run aeropulse-ml train` | Four families, gate reports |
| Earth Engine | Earth Engine API, service account | Fixture replays | S5P aerosol index, WorldPop; S5P CO stretch |
| Observability | Cloud Logging, Cloud Monitoring (basic) | OTel collector debug exporter | Cycle success, freshness, errors, spend |

### 3.3 What is removed and why

| Removed | Why | Trigger to add it back (Section 16) |
| --- | --- | --- |
| Cloud SQL / PostGIS | Two databases, migrations, sync, always-on cost. Snapshots cover the map. | Snapshot reads miss the latency target, or operator writes outgrow per-document storage |
| Memorystore Redis | Data volume does not justify it; in-process cache is enough at three regions | Many API instances causing repeated BigQuery reads |
| Most Pub/Sub topics | A batch cycle per region is simpler and has fewer failure modes | Sub-minute freshness needed, or more than a handful of sources per region |
| Separate worker and detector services | One job per region-cycle has all the state it needs in one process | Cycles start overlapping or exceeding their window |
| Vertex Pipelines, Model Registry, canary, auto-demotion | MLOps machinery does not change the demo | First real production deployment |
| AutoML smoke detector | No labelled dataset; training and validation would eat the window | A moderated, licence-checked photo set exists (Section 9.9) |
| GKE, Dataflow, multi-region GCP | Not needed at this scale | — |

### 3.4 Why one cycle job replaces the worker/detector split

The Global LLD split a stateless worker from a detector job because Cloud Run recycles in-memory state. A batch cycle sidesteps the problem: each run loads the window it needs from BigQuery (current hours plus the anomaly history window), adds what it just fetched, and finishes. It holds no state between runs.

```mermaid
sequenceDiagram
  participant SCH as CloudScheduler
  participant CYC as CycleJob
  participant SRC as Providers
  participant GCS as CloudStorage
  participant BQ as BigQuery
  participant PS as PubSubAlerts
  SCH->>CYC: run region=R
  CYC->>BQ: read watermarks and history window
  CYC->>SRC: fetch due sources since watermark minus overlap
  CYC->>GCS: archive raw payloads
  CYC->>CYC: normalize, QC, H3, dedup
  CYC->>BQ: load observations and meteo_forecast
  CYC->>CYC: features, rules or served model, anomaly, source likelihood
  CYC->>CYC: plume forward for events and fire clusters, backward for anomalies
  CYC->>CYC: build graph and incidents
  CYC->>BQ: predictions, graph edges, source health
  CYC->>GCS: write snapshot R/cycle_time.json then repoint latest
  CYC->>PS: alerts for new or escalated incidents
```

- **Idempotent.** A cycle is keyed by `(region_id, cycle_time)`. Re-running it overwrites the same snapshot object and loads with the same `dedup_key`s.
- **No overlap.** Cloud Run Job parallelism is 1 per region and the schedule interval is longer than the job timeout (both settings).
- **Existing code reused.** `process_snapshot` in `libs/intelligence` runs unchanged; the cycle passes `history_by_grid`, which fixes the "anomaly never sees history" bug (Global LLD 1.3 item 4).
- **Locally**, the existing worker and `DetectionTrigger` keep working for the current endpoints; `aeropulse-cycle` runs alongside them and writes snapshots to MinIO.

### 3.5 Adapters (reduced set)

From the Global LLD Section 2.5, only these are built. `AEROPULSE_PLATFORM=local|gcp` picks implementations in one factory module.

```python
class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str,
            if_generation_match: int | None = None) -> StoredObject: ...  # raises on failure
    def get(self, key: str) -> StoredObject: ...                         # bytes + generation
    def signed_upload_url(self, key: str, *, content_type: str, max_bytes: int, ttl_s: int) -> str: ...
    def signed_download_url(self, key: str, *, ttl_s: int) -> str: ...

class AnalyticsStore(Protocol):  # BigQuery or local Parquet
    def load(self, table: str, rows: Sequence[Mapping[str, object]]) -> int: ...
    def query(self, template_id: str, params: Mapping[str, object], *, max_bytes: int) -> list[dict]: ...

class SnapshotStore(Protocol):
    def write(self, snapshot: RegionSnapshot) -> str: ...   # versioned object, then repoint latest
    def latest(self, region_id: str) -> RegionSnapshot | None: ...

class LLMClient(Protocol):
    def generate(self, *, system: str, contents: Sequence[Content], tools: Sequence[Tool] | None,
                 response_schema: dict | None) -> LLMResponse: ...
```

`AnalyticsStore.query` takes only a template id and parameters; free SQL is never accepted (Section 11.3). `ObjectStore.put` raises on failure, fixing the "upload succeeds with a URI that points at nothing" bug (Global LLD 1.5).

---

## 4. APAC Region Packs and hazard profiles

### 4.1 Layout

```text
config/
  regions/
    in-north/      region.yaml  gazetteer.parquet  population_h3r8.parquet  stations.json
    sg-singapore/  region.yaml  ...
    au-nsw/        region.yaml  ...
  hazard_profiles/
    crop_residue_burning.yaml
    transboundary_haze.yaml
    bushfire_smoke.yaml
    urban_pollution.yaml
    dust.yaml
  aqi_standards/
    cpcb_in.yaml
    sg_nea.yaml        # confirm index and bands from NEA
    au_nsw_aqc.yaml    # confirm categories and thresholds from NSW
  model_serving.yaml   # Section 7.7
  citizen.yaml         # Section 9
```

Validated by a Pydantic `RegionPack` model in a new `libs/regions/aeropulse_regions/` package with `extra="forbid"`, like every other contract.

### 4.2 `region.yaml` (APAC schema)

Two additions over the Global LLD: `hazards` and `source_domain`.

- **`hazards`** lists hazard profiles. They drive source-likelihood classes, seasonal features, plume defaults, and UI copy.
- **`source_domain`** is the area where pollution *sources* and *wind* are watched. It can be much larger than the display area. This is what makes transboundary haze possible: Singapore's display area is the island, but the fires that affect it are elsewhere.

```yaml
schema_version: region.v1
region_id: sg-singapore
display_name: Singapore
country_codes: [SG]
timezone: Asia/Singapore
h3_resolution: 8                       # AGENTS.md: 1 km cells
aqi_standard: sg_nea
geometry:
  bbox: [103.6, 1.15, 104.1, 1.48]     # display area — setting, confirm at onboarding
source_domain:
  bbox: [95.0, -6.0, 120.0, 8.0]       # fires and wind watched here — setting, confirm
  wind_site_resolution: 4              # coarser H3 sites over the large domain
  max_wind_sites: 60                   # setting; bounds Open-Meteo request volume
map_view: { lon: 103.82, lat: 1.35, zoom: 9.5 }
hazards: [transboundary_haze, urban_pollution]
sources:
  - id: openaq
    enabled: true
    params: { parameters: [pm25, pm10], monitor_only: true }
    secret_ref: projects/<p>/secrets/openaq-api-key   # name only
  - id: firms
    enabled: true
    params: { products: [VIIRS_NOAA20_NRT, VIIRS_SNPP_NRT], day_range: 1, domain: source }
    secret_ref: projects/<p>/secrets/firms-map-key
  - id: openmeteo
    enabled: true
    params: { keep_forecast_hours: 48, domain: source }
  - id: earthengine
    enabled: true
    interval_seconds: 86400
    params: { products: [s5p_aer_ai], domain: source }
model_derived_sources: [openmeteo]
ground_truth_sources: [openaq]
gazetteer: { source: geonames, min_population: 10000 }
population: { source: worldpop }
demo: { enabled: true }
```

The other two packs differ only in data:

```yaml
# in-north — today's corridor, migrated first; golden-tested against current output
region_id: in-north
timezone: Asia/Kolkata
aqi_standard: cpcb_in
geometry: { bbox: [73.5, 27.0, 78.5, 32.5] }        # today's DEFAULT_AOI
source_domain: { bbox: [73.5, 27.0, 78.5, 32.5] }   # sources are inside the region
hazards: [crop_residue_burning, urban_pollution, dust]

# au-nsw
region_id: au-nsw
timezone: Australia/Sydney
aqi_standard: au_nsw_aqc
geometry: { bbox: [150.0, -34.4, 151.5, -33.3] }    # Greater Sydney display area — setting, confirm
source_domain: { bbox: [141.0, -37.5, 153.7, -28.0] } # NSW — setting, confirm
hazards: [bushfire_smoke, urban_pollution, dust]
```

Validator rules (kept from the Global LLD, plus two):

- A source in `ground_truth_sources` must not appear in `model_derived_sources`.
- `secret_ref` holds a name, never a value. A value-shaped string fails validation.
- `h3_resolution` must be 8.
- **New:** `source_domain.bbox` must contain `geometry.bbox`.
- **New:** every entry in `hazards` must name an existing hazard profile.

**H3 cells are only materialised inside the display area**, plus the sparse cells that plume outputs touch. The source domain is sampled by coarse wind sites and FIRMS bounding-box queries. It is never tiled at resolution 8, because a domain the size of the Singapore one would mean millions of cells.

### 4.3 Hazard profiles

A hazard profile is configuration that tells the shared engine what to look for. Example:

```yaml
# config/hazard_profiles/transboundary_haze.yaml
key: transboundary_haze
display_name: "Transboundary haze"
source_class: peat_and_forest_fire          # class used by source likelihood (Section 7.6)
seasonal_prior:
  months: [8, 9, 10]                        # setting — confirm from regional climatology
  feature: is_haze_season
signals:                                    # evidence the source-likelihood score may use
  - upwind_fire_frp_on_back_trajectory
  - s5p_aerosol_index_anomaly
  - pm25_above_expected
plume_defaults:
  release_level_weights: { "10m": 0.3, "100m": 0.7 }   # setting
  horizons_hours: [1, 3, 6, 12, 24, 48]
copy:
  explainer: "Smoke from vegetation and peat fires carried across borders by regional winds."
```

| Profile | `source_class` | Key signals | Plume defaults (settings) |
| --- | --- | --- | --- |
| `crop_residue_burning` | `crop_residue_burning` | FIRMS on cropland in season, upwind transport, PM2.5 above expected | Near-surface release, 1–24 h |
| `transboundary_haze` | `peat_and_forest_fire` | FIRMS in the source domain, back-trajectory FRP, S5P aerosol index | Mixed release, 1–48 h |
| `bushfire_smoke` | `bushfire` | FIRMS intensity (FRP), wind, S5P aerosol index | Higher release weighting, 1–48 h |
| `urban_pollution` | `urban_combustion` | Population density, time of day, low wind, no upwind fire | No plume; anomaly and forecast only |
| `dust` | `dust` | High wind, low humidity, S5P aerosol index with no fire nearby | Near-surface, 1–12 h |

The months on each profile replace today's hardcoded `_STUBBLE_MONTHS` in `feature_spec.py`. Every month list is a setting to confirm against published regional climatology before it is shown to users.

### 4.4 AQI standards

Same mechanism as the Global LLD Section 3.3: bands are data, copied from the official publication with a `source_url`, never typed from memory.

| Key | Standard | Notes |
| --- | --- | --- |
| `cpcb_in` | CPCB National AQI (India) | Already in the code (`CPCB_PM25_BANDS`, `HAZARD_THRESHOLD_UGM3 = 121.0`); moves to YAML unchanged |
| `sg_nea` | Singapore NEA | NEA publishes a PSI and separate 1-hour PM2.5 bands. **Confirm which index AeroPulse shows, its averaging period, and the band table** from NEA before day 3. |
| `au_nsw_aqc` | NSW Air Quality Categories | **Confirm categories, per-pollutant thresholds, and averaging** from the NSW government source before day 3. |

- Each standard declares its `averaging` period. The hazard label (Section 7.4) uses the same averaging as the standard, so a 1-hour standard is not compared against a 24-hour mean.
- `hazard_label` (the band whose lower bound is the region's hazard threshold) is a team decision taken from the official health advice and recorded in the YAML with its source.
- The web app receives bands from `GET /api/v1/regions/{id}`; `frontend/web/src/utils/aqi.ts` stops holding CPCB constants.

### 4.5 Onboarding: `aeropulse-region init`

The Global LLD's nine onboarding steps (Section 3.4) are reduced to what the three packs need:

1. Validate bboxes and write a skeleton `region.yaml`.
2. **Discover ground stations** with OpenAQ v3 `/locations` (reference monitors only) inside the display area. Write `stations.json`. **Zero stations ⇒ `ground_truth: none`**: the region runs rules marked degraded and no model can be validated there.
3. Place wind sites: H3 resolution-5 centroids over the display area and resolution-4 (setting) over the rest of the source domain, capped by `max_wind_sites`.
4. Gazetteer from GeoNames (confirm licence and attribution) above `min_population`.
5. Population: WorldPop through Earth Engine, aggregated to H3 resolution 8 inside the display area and to coarser cells over the plume reach (setting). This replaces the five-point fixture and the Delhi-tuned `DENSITY_SCALE_PER_KM2`.
6. Print a health summary: stations found, sites placed, sources configured vs *not configured*.

Climate zone, basemap clipping, and the admin onboarding API are deferred.

### 4.6 Acceptance criterion (the headline)

> `sg-singapore` and `au-nsw` ingest live data and show their own map, timezone, AQI scale, hazard profiles, and plumes **with zero code changes** — only a pack and an onboarding run.

Enforced by tests:

- A golden test shows `in-north` produces the same events as before the refactor on the replay fixtures.
- A grep-style test fails if any Python or TypeScript file outside `config/` and `fixtures/` contains a region bbox, city coordinate, or timezone string.
- A test loads a synthetic fourth pack from `tests/fixtures/regions/` and runs one cycle end to end on fixtures.

---

## 5. Data ingestion

### 5.1 Connectors

The plugin mechanism from the Global LLD Section 4.1 (`ConnectorPlugin`, `ConnectorContext`, entry-point discovery) is kept, because it is what makes "no code changes" true. The difference is how many plugins get built, and that each plugin receives a `domain` choice (`display` or `source`) for its bbox.

| Source | Plugin | Contract(s) | Status today | Hackathon work |
| --- | --- | --- | --- | --- |
| OpenAQ v3 | `openaq` | `observation` | live, India bbox hardcoded | bbox from pack; station discovery |
| NASA FIRMS | `firms` | `fire_observation` | live, India bbox hardcoded | bbox from `source_domain`; VIIRS NOAA-20 and SNPP products |
| Open-Meteo forecast | `openmeteo` | `meteo`, **`meteo_forecast`** | live, forecast hours dropped | sites from pack; keep forecast hours |
| Open-Meteo air quality | `openmeteo` | `observation` (model-derived) | live | CAMS PM2.5 as a feature and baseline only |
| Earth Engine | `earthengine` (new) | `raster` | fixture stubs | S5P aerosol index daily; WorldPop once at onboarding |
| Citizen reports | API, not a connector | `citizen_report` | in memory | Section 9 |

Optional, only if OpenAQ coverage turns out to be too thin in Singapore or NSW (checked on day 3, Section 17): a regional ground-truth plugin (`sg_nea` or `au_nsw`) built against the government's public API. Confirm the API terms before building.

### 5.2 Prerequisite fixes from the Global LLD (days 1–2)

These change what the plume and models see, so they come first.

| Fix | Why it matters here | Files |
| --- | --- | --- |
| Keep forecast hours as `meteo_forecast` (never as observations) | The plume has no future wind without it | `connectors/openmeteo/.../connector.py`, new `libs/contracts/aeropulse_contracts/meteo_forecast.py` |
| IDW uses only the scoring hour and only ground-truth sources | Snapshot PM2.5 must not mix hours or CAMS | `libs/intelligence/aeropulse_intelligence/detect.py`, `estimator.py` |
| Pass `history_by_grid` | Anomaly needs history | the cycle job, replacing `apps/worker/aeropulse_worker/pipeline.py` line 264 |
| Locate the CAMS blend to the cell | No "last CAMS value anywhere" | `detect.py`; `RasterObservation` gains `grid_id` |
| Citizen linking regardless of severity | Today's rule skips HIGH and CRITICAL cells (`routers/citizen.py` lines 76–81) | `apps/api/aeropulse_api/routers/citizen.py` |
| `jwt_secret` fails closed; OIDC algorithms pinned | Public Cloud Run deployment | `libs/common/aeropulse_common/settings.py`, `libs/auth/aeropulse_auth/jwt.py` |
| Gate Demo constants in `EventDetectMap.tsx` | Live must not show Demo wind | `frontend/web/src/components/events/EventDetectMap.tsx` |

The `MeteoForecast` contract and the `issued_at <= t` leak rule are exactly as in the Global LLD Section 4.6.

### 5.3 Cadence (settings)

| Source | Interval (setting) | Notes |
| --- | --- | --- |
| OpenAQ | 15 min | Upstream agency latency varies; confirm per region |
| FIRMS NRT | 15 min | NASA documents NRT latency; confirm before quoting |
| Open-Meteo forecast and air quality | 60 min | One request per batch of sites |
| Earth Engine S5P aerosol index | 24 h | Valid-pixel fraction carried; cloudy cells are missing, not zero |
| WorldPop | once, at onboarding | Static |
| Citizen report | push | Analysis target ≤ 2 min after upload (target, to be measured) |

A cycle runs each source whose interval has elapsed since its watermark, so one 15-minute schedule per region covers all of them.

### 5.4 Pub/Sub: only where it adds visible value

| Topic | Producer | Consumer | Why asynchronous |
| --- | --- | --- | --- |
| `aero.citizen.reports` (exists, unused today) | Cloud Storage upload notification | `citizen-analyzer` (push, OIDC-authenticated) | The upload returns at once; analysis takes seconds and calls Gemini |
| `aero.alerts` (exists) | cycle job, citizen analyzer | BigQuery subscription (alert log) and one webhook pusher | Alerts fan out without blocking the cycle |
| `aero.citizen.reports.dlq` | dead-letter policy | operator inspection | Failed analyses are visible, not lost |

Delivery is at least once. The analyzer is idempotent on `report_id`. Max delivery attempts is a setting (initial setting 5). The full topology from the Global LLD Section 4.5 moves to Section 16.

### 5.5 Backfill and training data

- `aeropulse-cycle --mode backfill --start --end` runs the same connectors through the same contracts with `processing_mode=BACKFILL`. Backfill never raises alerts.
- Historical training data is loaded straight into BigQuery by batch jobs:
  - The India notebook dataset: 1,705,252 station-hours across 149 OpenAQ stations over 567 days (`AeroPulse_ML_Notebooks/pm25_estimator/artifacts/pm25/phase7/historical_coverage_audit.json`), imported with its fingerprint.
  - OpenAQ history for Singapore and NSW stations. The access route (the OpenAQ archive or the API) and the resulting station-hours must be measured on day 3. **The design does not assume coverage it has not measured.**
  - FIRMS archive for the same periods (standard-processing archive; confirm product and access).
  - Open-Meteo historical weather and CAMS for the same sites (confirm the historical endpoints).

---

## 6. Data model: BigQuery, Cloud Storage, serving snapshots

### 6.1 BigQuery

One dataset per concern. Tables are partitioned by day and clustered by `region_id, grid_id`. Writes use **batch load jobs** from newline-delimited JSON written by the cycle, not streaming inserts (cheaper and simpler; confirm current pricing).

| Table | Written by | Purpose |
| --- | --- | --- |
| `aeropulse_raw.air_quality`, `.fire`, `.weather`, `.raster`, `.meteo_forecast` | cycle job | History, replay, training |
| `aeropulse_features.features_hourly` | cycle job | Offline feature store; same `build_features` output, plus `ml_feature_version` |
| `aeropulse_labels.pm25_hourly` | scheduled query over ground-truth sources only | Labels |
| `aeropulse_predictions.served`, `.shadow` | cycle job | What was served and what challengers said |
| `aeropulse_eval.reports` | training job | One row per gate report (family, region, split, metric, baseline, value, pass) |
| `aeropulse_eval.daily_metrics` | scheduled query | Live skill once labels arrive (stretch) |
| `aeropulse_graph.nodes`, `.edges` | cycle job, citizen analyzer | Environmental Intelligence Graph (Section 10) |
| `aeropulse_citizen.reports` | API, analyzer (append-only status events) | Listing, analytics. No images, no raw reporter ids. |
| `aeropulse_ops.source_health`, `.cycles` | cycle job | Freshness, *not configured* states, cycle durations |

A scheduled-query test fails if a model-derived source id appears in a label table. Spatial joins use a `grid_cell` dimension table written at onboarding.

### 6.2 Cloud Storage

| Bucket | Contents | Access | Lifecycle (settings) |
| --- | --- | --- | --- |
| `<project>-aeropulse-raw` | Vendor payloads by `source/region/date` | cycle job write; nobody else reads | Delete after retention |
| `<project>-aeropulse-citizen` | `incoming/` originals, `sanitized/` copies, `reports/{report_id}.json` | Private, uniform access, public access prevention; signed URLs only | Originals deleted after processing retention |
| `<project>-aeropulse-models` | Artifacts, gate reports (JSON + HTML) | Training job write; cycle job read | Kept |
| `<project>-aeropulse-serving` | `snapshots/{region_id}/{cycle_time}.json`, `snapshots/{region_id}/latest.json` | cycle job write; API read | Versioned snapshots kept for the replay window |

### 6.3 Serving snapshot contract (`region_snapshot.v1`)

The cycle job precomputes everything the map needs for one region. The API serves it from memory.

```python
class RegionSnapshot(BaseModel):            # "region_snapshot.v1"
    model_config = ConfigDict(extra="forbid")
    region_id: str
    cycle_time: datetime                    # UTC
    pack_version: str                       # hash of region.yaml
    mode: Literal["live", "backfill"]       # Demo never produces a snapshot
    cells: list[CellState]                  # PM2.5 served value + provenance_class + AQI band + field_status
    fires: list[FireCluster]
    wind: list[WindVector]                  # observed now + forecast hours, each with issued_at
    forecasts: list[CellForecast]           # quantiles per horizon, model_version, degraded
    hazard: list[HazardCell]                # probability or rank, calibrated flag
    anomalies: list[AnomalyFlag]
    source_likelihood: list[SourceLikelihoodV2]
    plumes: list[PlumeSummary]              # full plume.v1 objects stored separately, linked by id
    incidents: list[IncidentSummary]        # graph roots, Section 10
    citizen_watches: list[CitizenWatchSummary]
    source_health: list[SourceHealth]       # including NOT_CONFIGURED with reason
    served_models: list[ServedModel]        # family, version, degraded, degraded_reason, calibrated
```

- `mode` is never `demo`. Demo data lives only in `frontend/web/src/data/` and is never written to the serving bucket, so Live cannot paint it.
- A missing value is `null` with an entry in `field_status` giving the reason; the UI renders "—" with that reason.
- The `latest.json` pointer is rewritten only after the versioned object is written successfully, so the API never reads a half-written snapshot.

### 6.4 Operator and citizen writes without a database

The hackathon has two kinds of mutable state: citizen report status and operator moderation.

- The **system of record** for a report is `reports/{report_id}.json` in the citizen bucket. It is written with `if_generation_match` preconditions, so two writers cannot silently overwrite each other; a conflict is retried after re-reading.
- Every state change also appends a row to `aeropulse_citizen.reports`. A view keeps the latest row per report, and the list API reads that view.
- Event acknowledgement and other operator workflows are read-only in the hackathon build: events are owned by the cycle job.

### 6.5 Latency check (day 4) and the escape hatch

- **Target (setting):** map payload for one region served at p95 under a stated budget from a warm Cloud Run instance. The budget is agreed in review and measured on day 4.
- **Trend and history** endpoints query BigQuery through templates with `maximum_bytes_billed`. Their target is looser and stated separately.
- If the map target fails because snapshots are too large, the snapshot is split per layer first. If writes or queries outgrow the per-document approach, a small serving store (Firestore or Cloud SQL) is added then, behind the same `SnapshotStore` / repository interfaces.

---

## 7. ML: four intelligence strategies

### 7.1 What is built

| # | Family | Sophistication | Algorithm | Output | Baselines it must beat |
| --- | --- | --- | --- | --- | --- |
| 1 | `pm25_forecast` | **Trained** | LightGBM quantile (P10 / P50 / P90), horizons {1, 3, 6, 12, 24} h, pooled across regions | Quantiles per cell with a station, per horizon | Persistence; raw CAMS forecast for the same valid hour; hour-of-week climatology |
| 2 | `pm25_hazard_24h` | **Trained** | LightGBM classifier; isotonic calibration on a calibration slice | Probability if calibrated, otherwise rank | Current PM2.5 as a score; persistence of "already above threshold"; max CAMS forecast over the next 24 h |
| 3 | `anomaly` | Cheap, statistical | Observed vs the forecast's own P90 for that hour; fallback to hour-of-week quantiles per station fitted on training rows | Score, expected range, reason | Today's absolute-threshold rule |
| 4 | `source_likelihood` | Transparent heuristic | Weighted evidence per hazard-profile class; weights in config | Ranked classes, uncalibrated scores, evidence list | Today's `score_sources` in `likelihood.py` (as a sanity comparison; no gold labels exist) |

Peak prediction and the no-station nowcast with kriging (Global LLD 6.4) are deferred. Cells without a station show the IDW / CAMS value with its `provenance_class`, as today.

### 7.2 One pooled model per family, not one per region

```mermaid
flowchart TB
  DATA["BigQuery features_hourly + labels, all regions with ground truth"] --> TRAIN["One model per family"]
  TRAIN --> EVAL["Evaluate per region: rolling-origin + leave-region-out"]
  EVAL --> IN["in-north gate"]
  EVAL --> SG["sg-singapore gate"]
  EVAL --> AU["au-nsw gate"]
  IN --> SERVE["config/model_serving.yaml lists only regions whose gate passed"]
  SG --> SERVE
  AU --> SERVE
```

- Features are **transferable**: no `lat`, `lon`, `grid_id`, or per-cell baselines. The notebooks found that a coordinate-free set matched the coordinate version for hazard (PR-AUC 0.760 vs 0.758, `AeroPulse_ML_Notebooks/anomaly_detector/artifacts/anomaly/phase7_spatial/phase7_report.json`).
- Region context enters through features, not separate models: hazard-profile flags, seasonal-prior flags, the region's hazard threshold (`region_threshold_ugm3`), and region climatology percentiles fitted on training rows.
- The demo claim is **"train once, evaluate per region"**. Whether the model is *served* in a region depends on that region's gate.

### 7.3 Features (`ml-features-3.0.0`)

Feature names stay in one place (`libs/contracts/aeropulse_contracts/feature_spec.py`); training and serving both import them. The version bumps because the set changes.

| Group | Features | Leak rule |
| --- | --- | --- |
| History | Current PM2.5, lags, rolling means and max (station cells) | Only hours `< t` for lags; never the label row |
| Forecast weather | Wind u/v at 10 m and 100 m, boundary-layer height, temperature, humidity, precipitation at `valid_at = t + h` | `issued_at <= t` enforced by the feature builder and by `aeropulse-ml parity` |
| CAMS | CAMS PM2.5 now and forecast at `t + h` | Feature only, never a label |
| Fire | Count and FRP in rings; **transport-weighted FRP**: sum of fire FRP weighted by back-trajectory particle fraction from the plume engine | Back-trajectory uses wind issued `<= t` |
| Satellite | S5P aerosol index, valid-pixel fraction | Daily product, latest available `<= t` |
| Time and region | Hour, day of week, month, seasonal-prior flags, hazard-profile flags, region threshold | — |

Features derived from the target are leaks; `DERIVED_FROM` gains the new families and the parity test checks them.

### 7.4 Labels

- `pm25_forecast`: station PM2.5 at `t + h` from `ground_truth_sources` only.
- `pm25_hazard_24h`: in `t+1 .. t+24`, the region-standard concentration (using the standard's own averaging period) reaches the region's hazard threshold. The threshold comes from the AQI standard YAML, not from code.
- `anomaly`: no training label. The gate measures agreement with the hazard label, as the existing gate does.
- `source_likelihood`: no gold label exists. It stays a heuristic and is never presented as calibrated (Section 7.6).

### 7.5 Evaluation protocol (reduced)

No random splits (AGENTS.md). Every transform is fitted on training rows only, then applied to held-out rows. The code is a port of `phase7_eval.py` from the notebooks into `libs/ml/aeropulse_ml/evaluation.py`.

| Split | Definition | Purpose |
| --- | --- | --- |
| Purged rolling-origin | Expanding window, folds (setting: 5), purge = max horizon, embargo after (notebook setting: 24 h purge, 48 h embargo) | Time generalisation |
| Leave-region-out | Train on two regions, test on the third (only where the third has ground truth) | The transfer claim |
| Season check | Hold out the region's main pollution season where history covers it | Regime shift; reported as "not available" where history is too short |
| Calibration slice | Between train and test; used only for calibration and threshold choice | The threshold is never chosen on test |

Metrics per region and horizon: MAE, RMSE, skill vs each baseline, extreme-regime recall, P10–P90 coverage; for hazard PR-AUC, ROC-AUC, Brier, expected calibration error, false-alert share.

Existing evidence, so the team knows where it starts (these are results, from the named files):

| Evidence | Figure | File |
| --- | --- | --- |
| 24 h PM2.5, India, 5-fold purged rolling-origin | Mean R² 0.226; RMSE 27.34 vs persistence 30.51; all gates passed: false | `AeroPulse_ML_Notebooks/pm25_estimator/artifacts/pm25/phase7/tuning/tuning_report.json` |
| 24 h hazard, India | PR-AUC 0.523, ROC-AUC 0.829; false-alarm share 65% | `.../phase7/peak_hazard/peak_hazard_report.json` |
| Hazard rolling-origin stability | PR-AUC 0.575 ± 0.165 | `AeroPulse_ML_Notebooks/anomaly_detector/artifacts/anomaly/phase9_rolling/phase9_report.json` |

The forecast did not pass every gate in the notebooks. The hackathon gains forecast weather and transport features, which the notebooks listed as missing. Whether that is enough is decided by the gate, not by this document.

### 7.6 Source likelihood (probabilistic intelligence layer, honestly labelled)

Classes come from the region's hazard profiles, so "crop residue burning" can only appear in `in-north`, and "peat and forest fire" only where `transboundary_haze` is enabled.

```python
class SourceLikelihoodV2(BaseModel):          # "source_likelihood.v2"
    region_id: str
    grid_id: str
    valid_at: datetime
    method_version: str                        # e.g. "evidence-weights-1.0"
    provenance_class: Literal["heuristic"]
    calibrated: Literal[False]                 # no gold set exists
    ranking: list[SourceScore]                 # sorted, scores in [0, 1], do not sum to 1
    evidence: list[EvidenceItem]               # each with source_id, value, unit, observed_at

class SourceScore(BaseModel):
    source_class: str                          # from hazard profiles
    score: float
    contributing_signals: list[str]
```

- Score per class = logistic of a weighted sum of normalised signals listed in its hazard profile. Weights live in `config/hazard_profiles/*.yaml` with a version, so a reviewer can read why a class ranks first.
- Signals: transport-weighted upwind FRP, fire count along the back-trajectory, S5P aerosol index anomaly, NO2 / CO where available (stretch), seasonal prior, wind speed and humidity (dust), population density and time of day (urban).
- **UI and agent rule:** show a ranked list with "heuristic score" and the evidence. Do **not** show percentages that sum to 100%. Percentages need calibration against a gold set, and none exists. This follows the same logic as "0.80 hazard is a rank until marked calibrated".
- A weakly supervised model can be trained and evaluated in shadow (as `hgb-source-*` is today) but is not served.

### 7.7 Serving and promotion (hackathon version)

```yaml
# config/model_serving.yaml — reviewed in git; the only place that says what is served
- family: pm25_forecast
  region_id: in-north
  model_version: lgbm-forecast-<timestamp>
  gate_report_uri: gs://<project>-aeropulse-models/reports/<run>/gate.json
  calibrated: false
- family: pm25_hazard_24h
  region_id: sg-singapore
  model_version: lgbm-hazard-<timestamp>
  gate_report_uri: gs://<project>-aeropulse-models/reports/<run>/gate.json
  calibrated: true
```

- At startup the loader reads each listed gate report and **refuses** an entry whose report says the region failed, or whose `ml_feature_version` differs from the current spec.
- No entry for a (family, region) ⇒ rules answer with `degraded=true` and `degraded_reason` (for example "no model passed the gate for sg-singapore" or "no ground truth in this region").
- Inference runs in process inside the cycle job. The notebook hazard bundle measured 3.4 MB with a warm median of 0.21 ms per prediction (`peak_hazard_report.json`, `deployment.*`), so a Vertex endpoint is not needed.
- Shadow scoring runs after the served answer exists, for every family, and writes to `aeropulse_predictions.shadow`.
- `apps/api/aeropulse_api/hazard_store.py` reads served hazard from the snapshot; the carry-forward rule stays only as the degraded fallback (fixes Global LLD 1.3 item 6).

### 7.8 Training job

- One container built from this repo (`infrastructure/docker/Dockerfile.ml`). Entry point `aeropulse-ml train --family F --dataset bq://... --regions in-north,sg-singapore,au-nsw`. The same code runs locally against Parquet.
- Runs on a Vertex AI custom training job (CPU; the dataset is about 1.7 M rows for India plus whatever Singapore and NSW add) or locally. Either way it writes the artifact, gate report, dataset fingerprint, feature version, and git commit to the models bucket and one row per metric to `aeropulse_eval.reports`.
- Promotion is a pull request that edits `config/model_serving.yaml`. The training job never writes that file.

### 7.9 ML Evaluation page

A dedicated page that renders `aeropulse_eval.reports`. It never holds numbers of its own.

| Panel | Content | When data is missing |
| --- | --- | --- |
| Forecast skill | Per region and horizon: model RMSE vs persistence, CAMS, climatology; skill; P10–P90 coverage | "—" with reason, for example "no ground truth in au-nsw" |
| Hazard | PR-AUC, ROC-AUC, Brier, calibration error, false-alert share; reliability curve | "—" with reason |
| Transfer | Leave-region-out results | "—" "only one region has ground truth" |
| Anomaly | Agreement with hazard label | "—" with reason |
| Source likelihood | Method version, weights, "no gold set, not calibrated" | Always shows this label |
| Citizen AI observation | Gemini agreement on the evaluation photo set (Section 9.8) | "—" "evaluation set not built" |
| Served now | Which model or rule answers each family in each region, and why | Never empty: at least the rule is listed |

Layout example (placeholders only; real values come from the reports):

```text
PM2.5 forecast · 24 h · sg-singapore      model lgbm-forecast-<ts>   gate: <pass|fail>
  Persistence       RMSE —
  CAMS forecast     RMSE —
  AeroPulse         RMSE —     skill vs best baseline —
```

---

## 8. Plume intelligence (the hero feature)

Deterministic physics, no language model. New package `libs/intelligence/aeropulse_intelligence/plume/`, model version `lagrangian-ens-1.0`. It replaces `wind-advection-0.1` (the constant-wind, 40-step, roughly 37 km straight line in `forecast.py` lines 105–116) for footprints. The old function stays as the degraded fallback and as the baseline the new model must beat.

### 8.1 What it answers

- **Forward:** "Smoke starts here. Where will it be in 1, 3, 6, 12, 24, 48 hours, with what probability? Which places does it reach, when, and how many people live there?"
- **Backward:** "PM2.5 rose here. Where did the air come from over the last 6–48 hours, and which fires lie along that path?" This feeds source likelihood, transport-weighted fire features, and the graph.

It answers *where*, not *how much*. Concentration comes from the forecast model, or is shown as relative intensity.

### 8.2 Simplified computation for the hackathon

```mermaid
flowchart LR
  O["Origin: fire cluster, event, citizen report, or operator click"] --> W["Wind field: latest-issued forecast per valid hour over the source domain"]
  W --> E["Ensemble of particles, RK2 through time-varying wind"]
  E --> S["Spread: wind-error perturbation + turbulent diffusion"]
  S --> F["Footprints P50 and P90 per horizon"]
  F --> X["Intersect with WorldPop at H3 cells"]
  X --> A["Arrivals: places, probability, median ETA, population"]
```

Integration, spread, and outputs are as in the Global LLD Sections 7.3–7.5. The hackathon settings:

| Setting | Hackathon value (setting) | Why |
| --- | --- | --- |
| Particles per run | 200 | Enough for P50 / P90 shapes at demo scale; NumPy-vectorised |
| Time step | 15 min | Matches hourly wind with sub-hour interpolation |
| Horizons | Taken from the hazard profile (up to 48 h) | Transboundary and bushfire smoke travels far |
| Wind levels | 10 m and 100 m, blended by profile weights and boundary-layer height | Near-surface vs lofted smoke |
| Wind uncertainty | Per region from recent forecast-vs-observed wind error by lead time; a fixed default (setting) until 7 days of pairs exist, flagged degraded | No guessed spread once data exists |
| Diffusion | Pasquill–Gifford class from wind and radiation / cloud; `K_h` per class from a cited source | Standard, explainable |
| Wet removal | Weight decay with precipitation | Cheap, visible effect |
| Runs per cycle | Top fire clusters by FRP plus every active event plus every corroborated citizen report, capped (setting) | Bounds cost |

Fire clusters: FIRMS hotspots grouped by H3 resolution-6 parent cell and time window (settings). This keeps a large fire season from producing thousands of plumes.

### 8.3 Population exposure

- `population_h3r8.parquet` from WorldPop (onboarding). Plume cells are resolution 8 inside the display area and coarser outside it.
- **Exposed population at horizon h** = Σ over cells (cell population × probability that the cell is inside the P90 footprint). It is labelled "estimated population potentially exposed (simulated)", with the WorldPop year and the plume version.
- Arrivals use the gazetteer: probability that particles pass within the place radius, median ETA among arriving particles, and place population.

### 8.4 Backward analysis ("where did this come from?")

- Triggered for every anomaly flag and every high hazard cell with a station, and on demand from the UI or the agent.
- Runs the same ensemble with negative time steps over observed wind (past hours) for 6–48 h (setting).
- Produces: a back-trajectory footprint, the fire clusters inside it with the particle fraction passing over each, and the S5P aerosol index along it.
- Wording is fixed: **"likely source region"** and **"consistent with transport from"** — never "caused by". The graph edge is `on_back_trajectory_of`, not `caused`.

Example sentence the agent may produce (placeholders; every value comes from a tool):

> "The strongest likely source region is about `<d>` km `<bearing>` of `<place>`, where `<n>` fire detections lie along the estimated air-mass path over the last `<h>` hours."

### 8.5 Contract

`plume.v1` from the Global LLD Section 7.6, plus three fields:

```python
direction: Literal["forward", "backward"]
exposure: list[HorizonExposure]          # horizon_hours, population_p90, population_source, population_year
source_candidates: list[SourceCandidate] # backward only: fire_cluster_id, particle_fraction, distance_km, bearing_deg
```

Full plume objects are stored as `plumes/{region_id}/{plume_id}.json` in the serving bucket. The snapshot carries summaries and ids.

### 8.6 Endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/plume/{plume_id}` | Full `plume.v1` |
| `GET /api/v1/map/plume?region_id&horizon_hours&direction` | GeoJSON footprints for the map (from the snapshot) |
| `POST /api/v1/plume/what-if` | Operator what-if from a map click (OPERATOR, ANALYST, AUTHORITY, ADMIN); rate-limited, cached by rounded inputs |
| `GET /api/v1/incidents/{id}/plume` | Plumes linked to an incident |

### 8.7 How we know it is better (and the label until then)

- **Station hit rate:** for past events in each region, stations inside the P90 footprint should see a PM2.5 rise within the ETA window more often than stations outside it, compared with `wind-advection-0.1`.
- **Spread calibration:** the share of verifying stations inside P50 / P90 should be close to 50% / 90%.
- **Satellite agreement (stretch):** overlap of next-day S5P aerosol index anomaly with the 24 h footprint, where cloud-free.

Results go to `aeropulse_eval.reports` with `family = plume`. **Until they exist the UI label is "Predicted smoke transport — experimental"**, with the model version and uncertainty drawn as P50 / P90 bands.

### 8.8 Tests

A uniform wind moves the centreline speed × time with no 37 km cap; a wind that turns 90° bends it; zero spread collapses footprints to the centreline; backward then forward returns near the origin; missing forecast hours set the degraded reason; exposure is zero over an empty population raster; backward runs list only fires inside the back-trajectory footprint.

---

## 9. Citizen Smoke Intelligence

Goal: a citizen uploads a photo. Gemini describes what is visible, as a structured **AI visual observation**. AeroPulse then checks that observation against the environment (FIRMS, wind, PM2.5, satellite). Only a corroborated observation can seed a plume and join an incident. Every step is labelled.

### 9.1 Flow

```mermaid
flowchart LR
  A["POST report: signed URL"] --> B["PUT photo to private bucket"]
  B --> C["GCS notification to Pub/Sub aero.citizen.reports"]
  C --> D["Sanitize: sniff, decode, EXIF read then strip, re-encode, sha256"]
  D --> E["Geo check: EXIF vs claim vs region vs time"]
  E --> F["Gemini multimodal: AI visual observation, schema only"]
  F --> G["Corroboration: FIRMS + wind + PM2.5 + S5P + events"]
  G --> H{"Decision table"}
  H -->|corroborated| I["Seed plume, link incident, citizen watch alert"]
  H -->|partial| J["Operator queue"]
  H -->|uncorroborated| K["Stored, operators only"]
```

Service: `apps/citizen_analyzer/` (Cloud Run, push subscription). Each stage writes its result to the report document before the next starts, so a failure leaves a partial analysis with `degraded_reasons`, not nothing. Stages are idempotent on `report_id`.

### 9.2 Upload and sanitize

From the Global LLD Sections 8.2–8.3, kept as is: signed upload URL, random object keys (fixes the filename collision), size and type checks, Pillow decode with a decompression-bomb limit, EXIF extracted (GPS, `DateTimeOriginal`, `GPSImgDirection`) then stripped by re-encoding, SHA-256 dedupe. `device_accuracy_m` and capture time are sent by the form, which drops them today. The perceptual hash is a stretch.

### 9.3 Geo check (simplified geo-trust)

Deterministic; weights and thresholds in `config/citizen.yaml`.

| Component | High when |
| --- | --- |
| `in_region` | Claimed point inside an onboarded region's display area |
| `exif_claim_distance` | EXIF GPS close to the claimed point (absence is only mildly negative) |
| `device_accuracy` | Small browser-reported radius |
| `time_consistency` | EXIF time recent relative to upload |
| `not_duplicate` | No identical image already submitted |

Levels: `trusted`, `usable`, `untrusted`. `observed_at` = EXIF time when consistent, otherwise `null` with the reason. It is never silently set to server time.

### 9.4 Gemini AI visual observation

Gemini on Vertex AI, multimodal, low temperature, **no tools**, **structured output** through `response_schema`. Input: the sanitized image and the report's observation type. The environmental context is *not* given to Gemini, so its observation stays independent of the evidence it will be checked against.

```json
{
  "type": "object",
  "properties": {
    "visual_class": {"type": "string", "enum": ["smoke_plume", "haze", "flames", "dust", "fog_or_cloud", "steam", "clear", "other", "unclear"]},
    "visual_certainty": {"type": "string", "enum": ["low", "medium", "high"]},
    "smoke_colour": {"type": "string", "enum": ["white", "grey", "black", "brown", "mixed", "not_applicable"]},
    "smoke_density": {"type": "string", "enum": ["light", "moderate", "dense", "not_applicable"]},
    "likely_source_type": {"type": "string", "enum": ["agricultural_field", "vegetation_or_forest", "peat", "waste_burning", "industrial_stack", "vehicle", "building_fire", "dust_storm", "regional_haze", "unknown"]},
    "apparent_drift_in_image": {"type": "string", "enum": ["left", "right", "toward_camera", "away_from_camera", "vertical", "unclear"]},
    "possible_confusers": {"type": "array", "items": {"type": "string", "enum": ["fog", "cloud", "steam", "dust", "sunset", "none"]}},
    "image_quality": {"type": "string", "enum": ["good", "fair", "poor"]},
    "scene_summary": {"type": "string", "maxLength": 280}
  },
  "required": ["visual_class", "visual_certainty", "likely_source_type", "image_quality", "scene_summary"]
}
```

Rules:

- **No numeric fields.** A validator also rejects `scene_summary` text containing concentrations, AQI values, distances, or counts (numbers with units such as µg, AQI, ppm, km). Gemini cannot put a figure into AeroPulse.
- `visual_certainty` is Gemini's own categorical judgement. It is not calibrated and is never shown as a percentage.
- **Prompt injection:** text visible in the image is content, not instructions (stated in the system prompt). Output is schema-constrained and no tools are offered, so an injected instruction has nothing to call.
- Gemini not configured or failing ⇒ `observation = null`, `degraded_reasons += ["ai_observation_unavailable"]`. The report goes to the operator queue. It is never auto-classified by the keyword regex under a Live banner.
- UI label: **"AI visual observation — requires corroboration from environmental data."**
- The model name is a setting (`AEROPULSE_GEMINI_MODEL`); the code never hardcodes a model version.

### 9.5 Environmental corroboration (deterministic)

Each signal carries its `source_id`, time, and value. Radii, windows, and weights are settings in `config/citizen.yaml`.

| Signal | Supports the observation when |
| --- | --- |
| `fire_nearby` | FIRMS hotspot within a radius and time window of the report |
| `fire_on_bearing` | If EXIF `GPSImgDirection` exists: a hotspot inside a cone along the camera bearing (cameras point at smoke) |
| `fire_upwind` | The matched fire is upwind of the reporter under current wind |
| `on_plume_path` | The report cell lies inside the P90 footprint of an existing forward plume |
| `pm25_elevated` | Nearest ground station within a radius is above the region's expected range (anomaly model), or rising over 3 h |
| `aerosol_index_elevated` | S5P aerosol index anomaly at the cell on the latest valid day (often missing under cloud; missing is neutral) |
| `active_event` | An active pollution event covers the cell or its 1-ring neighbours |

**Corroboration score** = weighted sum of supporting signals, with weights set per `visual_class` (for example, `haze` leans on `pm25_elevated`, `aerosol_index_elevated`, and `on_plume_path`; `smoke_plume` and `flames` lean on fire signals). Levels: `corroborated`, `partial`, `uncorroborated` (thresholds are settings). Output is `provenance_class = heuristic` with the full signal table.

### 9.6 Decision table

| Visual observation | Geo-trust | Corroboration | What happens |
| --- | --- | --- | --- |
| `smoke_plume`, `flames`, `haze`, `dust` | `trusted` | `corroborated` | Seed forward plume; link to an incident; publish a **citizen watch** alert (severity capped at watch) if the P90 footprint reaches a populated place within 6 h (setting) |
| same | `trusted` / `usable` | `partial` | Operator queue; operator accept ⇒ as above |
| same | any | `uncorroborated` | Stored; operators only; no plume, no alert |
| `fog_or_cloud`, `steam`, `clear`, `other`, `unclear` | any | any | Stored; operators only; shown as "no smoke observed by AI" |
| any | `untrusted` | any | Operator queue only; never seeds anything |

Plume origin: the matched FIRMS hotspot along the camera bearing if one exists, otherwise the reporter's location with a larger initial spread (setting). The person who saw the smoke may be kilometres from its source.

### 9.7 What a citizen observation can never do

- Create or raise a **pollution event**. Events stay on the deterministic and trained path (Section 14). The incident graph *associates* a report with an event; it does not change the event.
- Change a PM2.5 value, a forecast, a hazard probability, or a source-likelihood score.
- Become an ML training label.
- Show its photo publicly. Until a privacy filter exists, images are visible only to operators and the uploader through short-lived signed URLs. The public map shows a rounded point with the visual class and corroboration level.

### 9.8 Evaluate, do not train

Gemini is not trained in this build. It is **measured**:

- Build a small evaluation set from licence-checked public smoke and fire images (for example D-Fire, FIgLib / HPWREN — confirm licences), plus hard negatives (fog, cloud, steam, dust, sunset haze) and photos the team takes.
- Report per-class precision and recall for `smoke_plume` / `haze` / `flames` against hard negatives. Compare with today's keyword classifier in `libs/intelligence/aeropulse_intelligence/cv.py` and with "always clear".
- Results go to `aeropulse_eval.reports` with `family = citizen_ai_observation` and appear on the ML Evaluation page. If the set is not built, the page says so.

### 9.9 Fallback if the Gemini-on-photos rule change is rejected

Gemini writes only a description (no `visual_class`), and an operator assigns the class in the moderation queue. Corroboration, plume seeding, and the graph work exactly the same, starting from the operator's class. The demo gains one click; the architecture does not change. A trained detector (Global LLD Section 8.6) can later replace either path behind the same `VisualObserver` interface:

```python
class VisualObserver(Protocol):
    version: str
    provenance_class: Literal["ai_observation", "predicted", "citizen"]
    def observe(self, image: Image.Image, observation_type: str) -> VisualObservation | None: ...
```

### 9.10 Endpoints

| Method and path | Roles | Purpose |
| --- | --- | --- |
| `POST /api/v1/citizen/reports` | CITIZEN, VIEWER, ADMIN | Create report; returns signed upload URL |
| `POST /api/v1/citizen/reports/{id}/media` | same | Local / dev multipart upload (kept) |
| `GET /api/v1/citizen/reports` | authenticated | List with `region_id`, `visual_class`, `corroboration` filters; `items`, `total`, `limit`, `offset` |
| `GET /api/v1/citizen/reports/{id}` | authenticated | Report with observation, geo-trust, corroboration table, plume id |
| `GET /api/v1/citizen/reports/{id}/media` | OPERATOR+, or the reporter | Short-lived signed URL to the sanitized image |
| `POST /api/v1/citizen/reports/{id}/moderation` | OPERATOR, AUTHORITY, ADMIN | Accept, reject, or set class |

Abuse controls: per-reporter and per-IP rate limits (settings); reporter identity stored as a salted hash; coordinates must fall inside an onboarded region.

### 9.11 Tests

EXIF extracted and then absent from the sanitized file; a schema-violating Gemini response is rejected; a summary containing "PM2.5 is 180 µg/m³" is rejected; Gemini unavailable leaves the report in the queue with a reason; a `haze` observation with no supporting signals is `uncorroborated` and seeds nothing; a `smoke_plume` with a FIRMS hotspot on the camera bearing seeds the plume at the hotspot; a corroborated report never changes an event's severity; an untrusted report never alerts; end-to-end with `fixtures/citizen/sample-haze-delhi.png` plus one Singapore and one NSW fixture.

---

## 10. Environmental Intelligence Graph

A **logical** graph of how fires, air, wind, plumes, places, and people relate. There is no graph database: nodes and edges are rows in BigQuery and a per-incident subgraph in the snapshot. It gives the agent something structured to reason over, and gives judges an "AI reasoning over environmental relationships" story without new infrastructure.

### 10.1 Picture

```mermaid
flowchart LR
  FC["FireCluster"] -->|detected_by| SAT["FIRMS product"]
  FC -->|located_in| CELL["Cell / Place"]
  FC -->|emits| PF["Plume forward"]
  WIND["Wind forecast run"] -->|drives| PF
  PF -->|reaches| PLACE["Place"]
  PF -->|exposes| POP["Population estimate"]
  ST["Station"] -->|observes| SPIKE["PM2.5 anomaly"]
  SPIKE -->|traced_by| PB["Plume backward"]
  PB -->|on_back_trajectory_of| FC
  CR["CitizenReport"] -->|consistent_with| PF
  CR -->|near| FC
  INC["Incident"] -->|groups| FC
  INC -->|groups| PF
  INC -->|groups| SPIKE
  INC -->|groups| CR
```

### 10.2 Schema

```python
class GraphNode(BaseModel):            # "graph_node.v1"
    node_id: str                       # e.g. "fire_cluster:sg-singapore:<id>"
    kind: Literal["region", "place", "cell", "station", "fire_cluster", "plume",
                  "anomaly", "pollution_event", "citizen_report", "incident", "wind_run"]
    region_id: str
    valid_from: datetime
    valid_to: datetime | None
    attributes: dict[str, GroundedValue]   # every value carries source_id, provenance_class, observed_at

class GraphEdge(BaseModel):            # "graph_edge.v1"
    edge_id: str
    kind: Literal["detected_by", "located_in", "emits", "drives", "reaches", "exposes",
                  "observes", "traced_by", "on_back_trajectory_of", "consistent_with",
                  "near", "groups", "upwind_of"]
    src: str
    dst: str
    producer: str                      # model_version, rule version, or source_id
    provenance_class: ProvenanceClass
    attributes: dict[str, GroundedValue]   # distance_km, bearing_deg, probability, eta_hours, particle_fraction
    cycle_time: datetime
```

- Built by `libs/intelligence/aeropulse_intelligence/graph.py` (new), deterministically, at the end of each cycle and after each citizen analysis.
- **Edges are associations, not causation.** The vocabulary has no `caused` edge on purpose.
- **Incident** = a connected component that contains at least one fire cluster or anomaly *and* a plume that reaches a populated place, or an active pollution event. Incident ids are stable across cycles when the component overlaps the previous one (setting: minimum overlap), so "AeroPulse updates the incident" is literal.
- Stored as `aeropulse_graph.nodes` and `.edges` (partitioned by `cycle_time`) and as `IncidentSummary` with its subgraph in the snapshot.

### 10.3 How the agent uses it

The tool `get_incident_graph(incident_id)` returns the subgraph. Every numeric attribute enters the `ToolLedger`, so the grounding validator treats graph numbers like any other tool number. Gemini may narrate the chain ("fires → wind → plume → city → station rise") but cannot add an edge or a figure that is not in the subgraph.

---

## 11. Ask AeroPulse agent

Ask AeroPulse remains the conversational surface. Its strongest property is kept: every figure must come from a tool result and pass `validate_answer` in `libs/copilot/aeropulse_copilot/grounding.py`. What changes is breadth: it becomes an environmental intelligence agent across regions.

### 11.1 Gemini on Vertex AI

As in the Global LLD Section 9.1: `google-genai` with `vertexai=True` on Cloud Run (service account, ADC, no key), API key only locally. The manual tool loop, `ToolLedger`, one grounding retry, and the deterministic fallback stay. `MAX_TOOL_ROUNDS` (6 in `gemini.py` today) stays a cap; the composite tool `explain_incident` keeps typical questions inside it.

### 11.2 Tools

Existing tools (`get_air_quality`, `get_wind`, `get_active_fires`, `get_hazard_outlook`, `list_active_events`, `explain_event` in `libs/copilot/aeropulse_copilot/tools.py`) gain `region_id`. `cpcb_band()` becomes `AqiStandard.band()`, and every result includes `aqi_standard` and `provenance_class`.

| Tool | Returns | Reads |
| --- | --- | --- |
| `get_region_context(region_id)` | Name, timezone, AQI standard, hazard profiles, sources configured / not configured, ground truth present, served vs degraded families | Region pack, snapshot |
| `get_current_aqi(place)` | Served PM2.5, AQI band in the region's standard, provenance, staleness | Snapshot |
| `get_pm25_trend(place, hours)` | Hourly series and change | BigQuery template |
| `get_pm25_forecast(place)` | Quantiles per horizon, model version, degraded | Snapshot |
| `get_hazard_outlook(place)` | Probability or rank, calibrated flag | Snapshot |
| `get_active_fires(place, radius_km)` | Clusters with count, FRP, distance, bearing | Snapshot |
| `get_weather(place)` | Wind now and forecast (with `issued_at`), humidity, boundary-layer height | Snapshot |
| `get_satellite_signal(place)` | S5P aerosol index, valid-pixel fraction, date | Snapshot / BigQuery |
| `get_plume(place \| incident_id \| report_id, direction)` | Footprint summary, arrivals, ETA, exposure, version, experimental flag | Plume store |
| `get_population_exposure(incident_id)` | Exposed population per horizon with source and year | Plume store |
| `get_source_likelihood(place)` | Ranking, "heuristic, uncalibrated", evidence | Snapshot |
| `get_citizen_reports(place \| incident_id)` | Visual class (labelled AI observation), corroboration level and signals, geo-trust | Citizen store |
| `list_incidents(region_id)` | Active incidents with root kind, places reached, last update | Snapshot |
| `get_incident_graph(incident_id)` | Subgraph (Section 10) | Snapshot / BigQuery |
| `explain_incident(incident_id)` | One call that bundles AQI, fires, wind, satellite, plume, exposure, source likelihood, and citizen reports for the incident | All of the above |
| `query_trends(template_id, place, start, end)` | Rows from an allow-listed, parameterised BigQuery template | BigQuery |

`query_trends` follows the Global LLD Section 9.3: reviewed SQL files in `libs/copilot/aeropulse_copilot/queries/`, query parameters only, a read-only service account on curated views, `maximum_bytes_billed`, and a row limit. Place names are resolved to cell ids by the gazetteer, never interpolated into SQL.

### 11.3 Flow for "Why is air quality getting worse in Singapore?"

```mermaid
sequenceDiagram
  participant U as User
  participant G as Gemini
  participant T as Tools
  participant V as GroundingValidator
  U->>G: Why is air quality getting worse in Singapore?
  G->>T: get_region_context sg-singapore
  G->>T: get_pm25_trend Singapore 6h
  G->>T: list_incidents, then explain_incident
  T-->>G: AQI, fires, wind, satellite, plume, exposure, source likelihood, citizen reports
  G->>V: draft answer + ledger
  V-->>G: pass, or one retry naming ungrounded figures
  G-->>U: grounded answer with citations and provenance labels
```

Answer shape (placeholders; every figure comes from the ledger):

> "PM2.5 at `<station>` has risen from `<a>` to `<b>` µg/m³ over the last `<h>` hours (measured, OpenAQ). AeroPulse found `<n>` fire detections in `<area>` along the back-trajectory of that air (FIRMS; simulated transport, experimental). The likely source ranking puts transboundary haze first (heuristic score, not calibrated). The forward plume reaches `<place>` with probability `<p>` and a median arrival of `<t>` hours, where an estimated `<pop>` people live (WorldPop `<year>`). `<k>` citizen photos nearby were classified as haze by AI and corroborated by station data."

### 11.4 Prompt and grounding rules

- `prompts/system_v2.md` replaces the corridor-specific prompt. Region facts are injected at request time from the region pack.
- Kept: numbers only from tools; an uncalibrated hazard is a rank; degraded means a baseline answered; health guidance stays general; CAMS is model output.
- New: provenance labels must be stated for simulated, heuristic, and AI-observation values; plume probabilities are footprint probabilities, not concentration forecasts; backward plumes are "likely source region", never "caused by"; citizen AI observations are "AI observations, corroborated / not corroborated".
- Validator addition: reject an answer that presents an `ai_observation`, `simulated`, or `heuristic` value with measurement wording ("measured", "recorded", "detected by station").
- `copilot_prompt_version` bumps. The eval set gains region-switch, backward-plume, and citizen-report cases for each of the three regions.

---

## 12. API and the command-centre UI

### 12.1 API changes

| Change | Detail |
| --- | --- |
| Regions | `GET /api/v1/regions`, `GET /api/v1/regions/{id}` (bbox, map view, timezone, AQI standard with bands, hazard profiles, source status, served families) |
| Snapshot-backed reads | `map`, `grid`, `events`, `risk`, `models`, `sources`, `alerts` routers read `SnapshotStore.latest(region_id)` on GCP. Locally they keep today's repository until migrated; every endpoint that cannot be served on GCP returns *not configured* with a reason rather than an empty success. |
| Incidents | `GET /api/v1/incidents?region_id` (list: `items`, `total`, `limit`, `offset`), `GET /api/v1/incidents/{id}` with subgraph |
| Plume | Section 8.6 |
| Citizen | Section 9.10 |
| ML evaluation | `GET /api/v1/ml/evaluation?region_id&family` from `aeropulse_eval.reports`; `GET /api/v1/models?region_id` shows what is served and why |
| Missing fields | `null` plus `field_status` reason |
| Region filter | `region_id` on every list and map endpoint; default from `AEROPULSE_DEFAULT_REGION` |
| CORS | Origins from settings only |

### 12.2 One map, not fifteen tabs

The UI should feel like an **environmental command centre**. The main view is one map with layer toggles and a right-hand incident panel.

| Element | Content |
| --- | --- |
| Top bar | Region selector (India, Singapore, Australia); region clock in its timezone; Demo / Live banner |
| Map layers | AQI cells (region standard), fires and fire clusters, wind (observed and forecast), forward plume P50 / P90 by horizon with a time slider, backward plume, population exposure heat, citizen reports, stations |
| Incident panel | Timeline: source → transport → impact; source likelihood with evidence; arrivals with ETA and population; citizen observations with corroboration; graph mini-view |
| Ask AeroPulse | Docked chat that can be opened from any incident with that incident pre-selected |
| Pages kept | Forecast, Evidence, Citizen Reports, Sources, plus the new **ML Evaluation** page |
| Badges | One badge per `provenance_class` (Section 2.2), the same everywhere |

Frontend rules hold: one HTTP client (`api/client.ts`), one Demo / Live branch (`services/resolve.ts`), Demo works with no API, Live never paints Demo data. Region state lives in a new `RegionContext` (URL `?region=` for shareable links). Cells are drawn with deck.gl `H3HexagonLayer`. The hardcoded corridor values in `geo.ts`, `format.ts`, `adapters.ts`, `aqi.ts`, and `AeroMap.tsx` (Global LLD 1.1) are removed.

### 12.3 Demo mode for three regions

- `frontend/web/src/data/regions/{in-north,sg-singapore,au-nsw}/` hold scripted scenarios: snapshot-shaped JSON, one plume each (forward and backward), one incident graph, one citizen report with a canned observation and corroboration.
- Demo data is generated by running the real cycle and plume code over **fixture** inputs (`fixtures/<region_id>/`), then saved. It is never typed by hand, so Demo shows what the engine would produce from those inputs. Every Demo screen carries the Demo banner.

---

## 13. Security and cost

### 13.1 Security (hackathon scope)

| Control | How |
| --- | --- |
| No credentials in code or images | `jwt_secret` has no default and the app refuses to start without it; Compose credentials come from a gitignored `.env`; region packs hold `secret_ref` names only |
| Secret Manager | OpenAQ key, FIRMS map key, JWT secret; mounted per service so each sees only what it needs |
| No key files | Cloud Run service accounts; Gemini and Earth Engine through ADC; signed URLs through IAM `signBlob`; CI deploy through Workload Identity Federation |
| Auth | HS256 JWT as today (OIDC later, per AGENTS.md); OIDC path pins algorithms; the browser token is acceptable for the demo only |
| Service accounts | `sa-cycle` (BigQuery load, buckets raw / serving, secrets, Earth Engine, publish alerts), `sa-citizen` (citizen bucket, Vertex AI user, BigQuery append, publish alerts), `sa-api` (read serving bucket, BigQuery job user on curated views, Vertex AI user, `signBlob`), `sa-train` (BigQuery read, models bucket write), `sa-push` (invoke citizen analyzer only) |
| Ingress | API and web public; citizen analyzer internal plus authenticated Pub/Sub push only |
| Citizen data | Private bucket, uniform access, public access prevention; EXIF stripped; photos operators and uploader only; reporter salted hash; coordinates rounded on public views |
| LLM safety | Schema-only photo output with no tools; numeric-claim validator; templated SQL only; grounding validator on every answer |
| SSRF | Connectors call only their providers (allow-list in `LiveHttpClient`); no user-supplied URLs are fetched |

Cloud Armor, reCAPTCHA Enterprise, the privacy filter, and the full IAM hierarchy are deferred (Section 16).

### 13.2 Cost guards

No price figures are stated here; check them against current Google Cloud pricing for the chosen region before the budget is set.

| Service | Guard |
| --- | --- |
| Cloud Run services | `min-instances=0`; `max-instances` per service (setting) |
| Cloud Run Jobs | One per region per cycle; job timeout below the schedule interval; parallelism 1 |
| BigQuery | Partitioned and clustered tables; batch loads, not streaming; `maximum_bytes_billed` on every query; the map reads snapshots, not BigQuery |
| Gemini | Per-user and per-IP rate limits; tool-round cap; one call per photo; model choice is a setting (a lower-cost model tier for photo observation if its evaluation holds up) |
| Earth Engine | Daily, bbox-limited reductions; WorldPop once at onboarding; confirm the project is registered for Earth Engine use under the right terms |
| Pub/Sub | Two topics; message retention short (setting) |
| Cloud Storage | Lifecycle deletion on raw and incoming photos |
| Training | One CPU custom job per run; no always-on endpoints |
| Whole project | Billing budget with alerts at fractions of the hackathon budget (settings); a kill switch that pauses Cloud Scheduler |

---

## 14. Proposed AGENTS.md amendments

[AGENTS.md](../AGENTS.md) and [CLAUDE.md](../CLAUDE.md) are edited only after the team agrees. These supersede the Global LLD Section 12 for the hackathon.

| Current rule | Proposed rule | Why |
| --- | --- | --- |
| "Air-quality labels are CPCB (India), never US EPA." | "Air-quality labels follow the official standard named in the region pack (`aqi_standard`). India uses CPCB, Singapore uses NEA, NSW uses the NSW categories. Never label one country's values with another country's scale, and never hardcode bands outside `config/aqi_standards/`." | Singapore and NSW must show their own scales; the spirit is kept. |
| "No language model on detection, anomaly, likelihood, or forecast. Ask AeroPulse is the only LLM surface." | "No language model on detection, anomaly, likelihood, forecast, plume, or pollution events. LLM surfaces are Ask AeroPulse and the citizen-photo **AI visual observation**, which is schema-constrained, contains no figures, is labelled 'requires corroboration', and can only act through deterministic environmental corroboration. It never creates or changes a pollution event, prediction, or label." | Allows Gemini-first photo analysis while keeping every scientific result deterministic or trained. |
| (new) | "Every served value carries a `provenance_class`. Simulated, heuristic, and AI-observation values are never presented as measured." | Makes the measured / predicted / AI-generated separation mechanical. |
| (new) | "Region-specific values (bboxes, sites, place names, seasons, thresholds, timezones, hazard profiles) live in region packs. Code that hardcodes a place is a bug." | Keeps "no application code changes" true. |
| (new) | "A model is served in a region only if `config/model_serving.yaml` lists it and its gate report for that region passed. A region without reference stations serves rules marked degraded." | Replaces the live-gate machinery for the hackathon without lowering the bar. |
| (new) | "Source likelihood is a heuristic until a gold set exists. Show a ranking with evidence, never percentages." | Same honesty as "hazard is a rank until calibrated". |

CLAUDE.md's "Do not put a language model on the event path" stays true: the citizen AI observation feeds a separate citizen-watch track and the graph's associations, never the event engine.

---

## 15. 17-day plan and agent workstreams

### 15.1 Day 1 contract freeze (what lets agents work in parallel)

On day 1 the following are written, reviewed, and merged before any workstream builds on them. After that, a change to any of them needs a short note to every workstream.

- `RegionPack`, `HazardProfile`, `AqiStandard` models and the three pack files (with "confirm" values).
- `MeteoForecast`, `provenance_class`, `region_id` on existing contracts.
- `RegionSnapshot`, `plume.v1` (with `direction`, `exposure`, `source_candidates`), `SourceLikelihoodV2`, `VisualObservation`, `CitizenAnalysis`, `GraphNode`, `GraphEdge`, `IncidentSummary`.
- Fixture snapshots for all three regions, generated from these contracts, so frontend and agent work can start on day 2 without the backend.

### 15.2 Workstreams

| Agent | Owns | Depends on | Key files |
| --- | --- | --- | --- |
| **1 · Data platform** | Region packs, onboarding, plugin connectors, cycle job, BigQuery, buckets, snapshots, Terraform, Scheduler | Contracts | `libs/regions/*`, `apps/cycle/*` (new), `connectors/*`, `infrastructure/gcp/*` |
| **2 · ML** | Features 3.0.0, four families, evaluation, gate reports, `model_serving.yaml` loader, training job | Contracts; BigQuery tables by day 4 (Parquet before) | `libs/ml/*`, `libs/contracts/.../feature_spec.py` |
| **3 · Plume** | Wind field, ensemble, spread, footprints, exposure, arrivals, backward runs, fire clusters, plume evaluation | `MeteoForecast`; population parquet | `libs/intelligence/aeropulse_intelligence/plume/*` |
| **4 · Citizen AI** | Upload, sanitize, geo check, Gemini observation, corroboration, decision table, Pub/Sub, evaluation set | Contracts; plume API by day 9 | `apps/citizen_analyzer/*`, `libs/vision/*` |
| **5 · Agent and graph** | Graph builder, incidents, tools, prompt v2, grounding additions, eval set | Snapshot fixtures; graph contracts | `libs/intelligence/.../graph.py`, `libs/copilot/*` |
| **6 · Frontend** | Region selector, command-centre map, incident panel, ML Evaluation page, citizen upload, Demo data for three regions | Snapshot fixtures | `frontend/web/src/*` |
| **7 · QA and architecture** | Contract tests, leak checks, the "no hardcoded region" test, security review, cost guards, demo rehearsals | Everything | `tests/*` |

### 15.3 Schedule

| Days | Data platform | ML | Plume | Citizen AI | Agent and graph | Frontend | Milestone |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1–2 | Contracts, packs, Section 5.2 fixes, GCP project, buckets, BigQuery datasets, Cloud Run skeleton | Port `evaluation.py`; import India dataset | Wind field sampling on fixtures | Upload and sanitize | Graph contracts; tool stubs on fixtures | `RegionContext`, selector, fixture-driven map | **Skeleton running on GCP; three regions selectable in Demo** |
| 3–4 | Plugins with pack bboxes; cycle job; Earth Engine S5P and WorldPop; Scheduler; snapshot writer; **OpenAQ coverage check for SG and NSW** | Features 3.0.0; baselines; dataset builder from BigQuery | RK2 ensemble, footprints | Gemini observation with schema and validator | Graph builder over snapshots | AQI by region standard; layers | **Live data for all three regions; day-4 latency check (Section 6.5)** |
| 5–7 | Hardening, source health, backfill runs | Forecast, hazard, anomaly, source likelihood; gate reports per region | Spread calibration from wind errors; exposure; arrivals | Corroboration and decision table | Incidents; stable incident ids | ML Evaluation page from real reports | **Gate reports exist for every family and region; served list decided** |
| 8–9 | Plume storage and endpoints | Transport-weighted fire features from back-trajectories | Backward runs; fire clusters; evaluation vs `wind-advection-0.1` | Plume seeding from reports | Plume and exposure tools | Plume time slider, backward view | **Forward and backward plumes on the live map** |
| 10–11 | Pub/Sub topics, DLQ, push auth | Shadow scoring for all families | Performance under per-cycle cap | End-to-end Pub/Sub path; evaluation set; moderation | Citizen tool | Upload form, report detail, citizen layer | **Photo → AI observation → corroboration → plume, live** |
| 12–13 | Alerts topic and webhook | Model card text for the evaluation page | Tuning | Alert for citizen watch | Full agent with 16 tools; prompt v2; grounding additions; eval set | Docked agent with incident context | **Agent answers the demo questions grounded, in all three regions** |
| 14–15 | Cost guards, budgets, kill switch | — | — | — | — | Command-centre polish; badges; "—" reasons; accessibility pass | **One map that tells the whole story** |
| 16 | Demo hardening: full rehearsal Live and Demo; regenerate Demo data from fixtures; record a Live run as a backup video | | | | | | **Rehearsed demo** |
| 17 | Submission: architecture, slides, video, demo script, README, ML evaluation, GCP architecture, cost summary, limitations, roadmap | | | | | | **Submitted** |

### 15.4 Demo hardening rules (day 16)

- Rehearse the Section 1.3 narrative end to end in Live for at least one region and in Demo for all three.
- **Fallback means switching to Demo mode with the banner visible.** Never swap fixture data into a Live screen. If a Live source fails, the UI shows it *not configured* or stale with a reason.
- Each critical step has a named Demo equivalent: anomaly, backward plume, source likelihood, forward plume, exposure, citizen observation and corroboration, incident update, agent answer.
- Keep the Live recording from a successful rehearsal as the backup if the venue network fails.

### 15.5 Standard checks at the end of each milestone

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/unit tests/contract -q
uv run aeropulse-ml parity
```

### 15.6 Exit criteria for the submission

1. Three regions selectable, each with its own map, timezone, AQI standard, and hazard profiles from packs only; the "no hardcoded region" test passes.
2. Live OpenAQ, FIRMS, and Open-Meteo for all three; Earth Engine S5P aerosol index and WorldPop for all three; any missing source shows *not configured* with a reason.
3. Gate reports for forecast, hazard, and anomaly in every region with ground truth, shown on the ML Evaluation page as they are: served where they pass, "in validation" with reasons where they do not.
4. Forward and backward plumes with P50 / P90, arrivals, and exposure, labelled experimental with the evaluation status.
5. Citizen photo → AI observation → corroboration → plume, end to end on GCP, with labels.
6. Agent answers the demo questions with every figure grounded, in all three regions.
7. Demo mode works with no API for all three regions.

---

## 16. Production evolution (deferred, not forgotten)

The [Global LLD](LLD_AeroPulse_Global.md) is the production target. Each deferred item has a trigger, so it is added when there is evidence it is needed, not before.

| Deferred | Global LLD section | Trigger to build |
| --- | --- | --- |
| Cloud SQL + PostGIS serving store (or Firestore for documents) | 5.1 | Day-4 latency check fails, or operator writes outgrow per-document storage |
| Full Pub/Sub topology, push worker, separate detector, DLQs per topic | 4.5, 2.4 | Sub-minute freshness required, or cycle duration approaches its interval |
| Memorystore | 2.3 | Repeated BigQuery reads across many API instances |
| Nowcast with residual kriging for cells without a station | 6.4 | Coverage of station-less cells becomes a user need |
| Peak model | 6.4 | Hazard model served and stable |
| Vertex Pipelines, Model Registry, Experiments | 6.8 | More than one retrain per week |
| Live gate, canary, automatic demotion, retrain triggers | 6.7, 6.10 | First production deployment with users relying on served models |
| Trained smoke detector (AutoML or ONNX) | 8.6 | A moderated, licence-checked photo set exists, and Gemini's measured precision is not enough |
| SafeSearch, face and plate blurring | 8.4 | Before any citizen photo is shown publicly |
| Cloud Armor, reCAPTCHA Enterprise | 8.12, 11.3 | Public citizen submission at scale |
| Additional regions and regional plugins (AirNow, EEA, PurpleAir) | 4.2 | A pack is requested; each must arrive with no code change |
| Remaining Earth Engine products (MAIAC AOD, ERA5-Land, Dynamic World, SRTM) | 4.3 | An ablation shows a gain |
| Two environments, full Terraform module set | 11.7 | After the hackathon |
| OIDC, licensed population data, exporting traces, load tests | AGENTS.md "Later" | As listed there |

---

## 17. Risks and open questions

| Risk or question | Impact | Mitigation | Decide by |
| --- | --- | --- | --- |
| **OpenAQ coverage in Singapore and NSW** is unmeasured | No ground truth ⇒ no validated model and no anomaly baseline there | Measure on day 3. If thin, build the optional `sg_nea` / `au_nsw` regional plugin (confirm API terms). If still none, the region runs rules marked degraded and the UI says so. | Day 3 |
| Singapore and NSW **AQI tables** not yet copied | Wrong labels | Copy from official sources with `source_url`; review by two people | Day 3 |
| **Gemini rule change** not agreed | Citizen flow needs an operator click | Section 9.9 fallback; same architecture | Day 1 |
| **Earth Engine access** and terms for the project | No satellite or population layers | Register the project early; fixture replays mark the layer *not configured* in Live if access fails | Day 2 |
| **Large source domain** for Singapore makes FIRMS and wind requests heavy | Slow cycles, cost | Coarse wind sites, site cap, fire clustering, per-cycle plume cap (all settings) | Day 4 |
| **Snapshot latency or size** | Slow map | Split snapshots per layer; then the Section 16 trigger | Day 4 |
| **Short history** outside India | Leave-region-out and season checks may be "not available" | Report "not available" honestly; never fill with India numbers | Day 7 |
| **Plume not yet beating `wind-advection-0.1`** | Weak claim | Keep the "experimental" label and show the comparison as it is | Day 9 |
| **Gemini quota or latency** at demo time | Agent or photo step stalls | Rate limits, cached demo answers in Demo mode only, recorded backup | Day 16 |
| **Agent work spread across seven parallel agents** | Contract drift | Day-1 freeze, QA agent owns contract tests, daily integration on `main` | Daily |
