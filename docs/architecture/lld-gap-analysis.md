# LLD gap analysis: current code vs the APAC LLD

Compares the code described in [current-state-audit.md](current-state-audit.md) with [LLD_AeroPulse_APAC.md](../LLD_AeroPulse_APAC.md). The sign-off decisions in LLD Section 0.2 were approved on 2026-10-04 (Gemini on citizen photos, no serving database, AQI per region, three regions), together with the Section 14 rule amendments.

Categories: **KEEP** (already correct), **ADAPT** (reuse with refactoring), **REPLACE** (conflicts with the target), **NEW** (does not exist), **DEFER** (deferred by LLD Section 16).

## 1. Requirements table

| LLD requirement | Current implementation | Gap | Required change | Category | Priority | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| Region Packs with `extra="forbid"` validation (4.1-4.2) | None; corridor in ~25 places | Everything | `libs/regions`, `config/regions/*`, validator rules | NEW | P0 | High: every later phase depends on it |
| `source_domain` larger than display area (4.2) | None | No domain concept | `Domain.DISPLAY` / `Domain.SOURCE` in `ConnectorContext` | NEW | P0 | Medium |
| Hazard profiles (4.3) | `_STUBBLE_MONTHS` constant | Not configurable | `config/hazard_profiles/*.yaml`, `HazardProfile` model | NEW | P0 | Low |
| AQI standards as data (4.4) | CPCB bands in copilot (correct) and frontend (wrong) | Duplicated, one copy wrong | `config/aqi_standards/*.yaml`, `AqiStandard.band()`, served to UI | REPLACE | P0 | Medium: SG and NSW tables need official sources |
| No hardcoded region test (4.6) | None | — | `tests/architecture/test_no_region_hardcoding.py` | NEW | P0 | Low |
| Golden test for `in-north` (4.6) | Contract "golden" parse tests only | No cycle-level golden | Golden events from replay fixtures | NEW | P1 | Medium |
| Synthetic fourth pack (4.6) | None | — | `tests/fixtures/regions/` pack and end-to-end cycle test | NEW | P1 | Low |
| `aeropulse-region init` (4.5) | None | — | CLI: validate, skeleton, station discovery when keys exist | NEW | P2 | Low |
| Connector plugins with entry points (5.1) | `DataConnector` ABC + static registry | No discovery, no context | `ConnectorPlugin`, `ConnectorContext`, `aeropulse.connectors` entry points, legacy adapter | ADAPT | P0 | Medium |
| OpenAQ bbox from pack (5.1) | Hardcoded bbox | — | Context-driven bbox, archive raw | ADAPT | P0 | Low |
| FIRMS from source domain, NOAA-20 + SNPP (5.1) | One product, hardcoded bbox | — | Products from params | ADAPT | P0 | Low |
| Open-Meteo keeps forecast hours as `meteo_forecast` (5.1, 5.2) | Future hours dropped | No `issued_at` | `MeteoForecast` contract, sites from pack | ADAPT | P0 | Medium |
| Earth Engine S5P AI + WorldPop (5.1) | None | — | `connectors/earthengine` with fixture replay; not configured without ADC | NEW | P1 | High: project registration |
| IDW scoring hour and ground truth only (5.2) | Mixes hours and CAMS | Bug | Filter in `detect.py` / estimator | ADAPT | P0 | Low |
| Pass `history_by_grid` (5.2) | Not passed | Bug | Cycle loads history window | ADAPT | P0 | Low |
| CAMS blend located to the cell (5.2) | Last raster anywhere | Bug | `grid_id` on raster, cell lookup | ADAPT | P1 | Low |
| Citizen linking regardless of severity (5.2) | Inverted rule | Bug | Analyzer-driven association | REPLACE | P1 | Low |
| `jwt_secret` fails closed, OIDC algs pinned (5.2) | Default secret, `alg` from header | Security | Settings validator; pinned algorithms; require `exp` | ADAPT | P0 | Low |
| Gate Demo constants in `EventDetectMap.tsx` (5.2) | Demo wind shown in Live | Bug | Region-driven, Demo-gated | ADAPT | P1 | Low |
| Cadence per source with watermarks (5.3) | Scheduler intervals, cursor watermarks | Not per region | Due-check inside the cycle | ADAPT | P1 | Low |
| Two Pub/Sub topics + DLQ (5.4) | Redpanda, 4 observation topics | Too many topics | Citizen and alerts only; local queue adapter | REPLACE | P2 | Low |
| Backfill through the same connectors (5.5) | `replay_all` from API | Ignores window | `aeropulse-cycle --mode backfill` | ADAPT | P2 | Low |
| BigQuery history tables (6.1) | Timescale | Different store | `AnalyticsStore` (Parquet locally, BigQuery on GCP) | REPLACE | P1 | Medium |
| Cloud Storage buckets (6.2) | MinIO helper, soft-fail | No interface | `ObjectStore` (LocalFS, MinIO, GCS); `put` raises | REPLACE | P0 | Low |
| `RegionSnapshot` serving contract (6.3) | None | — | Contract, `SnapshotStore`, versioned then `latest.json` | NEW | P0 | Medium |
| Citizen report document store (6.4) | In-memory | Lost on restart | `reports/{id}.json` with generation preconditions | NEW | P1 | Low |
| Four ML families, one pooled model each (7.1-7.2) | Six families, per-family trainers in one 1337-line file | Wrong families, no plugin | `ModelPlugin` + four family packages | ADAPT | P1 | Medium |
| `ml-features-3.0.0` (7.3) | `ml-features-2.0.0` | No forecast weather, CAMS t+h, transport FRP, S5P, region flags | Extend `feature_spec.py`, bump version | ADAPT | P0 | Medium |
| `issued_at <= t` leak rule (7.3) | No `issued_at` | Leak | Preprocessing + feature builder enforcement, parity check | NEW | P0 | Medium |
| Labels from ground truth only (7.4) | CAMS as label | Leak of model output into label | `GroundTruthFilter` from pack | REPLACE | P0 | Low |
| Purged rolling-origin, leave-region-out, season, calibration slice (7.5) | 80/20 cut, one held-out cell, last month | Weak, unpurged | `evaluation/` splits ported from `phase7_eval.py` | REPLACE | P1 | Low |
| Baselines first-class (7.1) | Persistence only, partly | Missing CAMS and climatology | `baselines/` module | ADAPT | P1 | Low |
| Source likelihood v2, heuristic, uncalibrated (7.6) | `score_sources` fixed priors | Not profile driven | Hazard-profile weights, `SourceLikelihoodV2` | REPLACE | P1 | Low |
| `config/model_serving.yaml` is the only serving switch (7.7) | Registry state machine | Different mechanism | Loader + `ModelResolver` verifying gate, version, artifact | REPLACE | P0 | Medium |
| Training job writes artifact, gate, fingerprint, commit (7.8) | Local joblib + `index.json` | No gate report, no commit | `aeropulse-ml train --family --dataset --regions` | ADAPT | P1 | Low |
| ML evaluation page from real reports (7.9) | Models page | — | `GET /api/v1/ml/evaluation`, UI page | NEW | P2 | Low |
| Lagrangian ensemble plume (8) | `wind-advection-0.1` | Straight line, 37 km cap | `plume/` package; old function kept as fallback and baseline | REPLACE | P1 | Medium |
| Population exposure from WorldPop (8.3) | Five fixture points | — | `population_h3r8.parquet` per pack | NEW | P2 | Medium: needs Earth Engine |
| Backward plume and source candidates (8.4) | None | — | `plume/backward.py` | NEW | P1 | Medium |
| Citizen photo: sanitize, geo check, Gemini observation, corroboration, decision table (9) | Keyword regex | Image never read | `libs/vision`, corroboration, `apps/citizen_analyzer` | REPLACE | P1 | Medium |
| Environmental Intelligence Graph + incidents (10) | Per-event lineage | No cross-entity graph | `graph/` builder, stable incidents | NEW | P1 | Low |
| Agent with 16 tools, prompt v2, provenance wording check (11) | 6 tools, corridor prompt | Not region aware | `region_id` on tools, new tools, templated queries | ADAPT | P2 | Medium |
| Regions endpoints, snapshot-backed reads (12.1) | Readers over Timescale; fixture fallback in Live | Live shows fixtures | Snapshot services; not configured with reason | REPLACE | P1 | Medium |
| One map, region selector, badges (12.2) | Corridor UI | Hardcoded geo | `RegionContext`, API-driven config | ADAPT | P2 | Medium |
| Demo for three regions generated from fixtures (12.3) | Hand-written mocks for India | — | `scripts/generate_demo_data.py` | NEW | P2 | Low |
| Security controls (13.1) | Committed token, default secret | — | Remove token; secrets from env/Secret Manager | ADAPT | P0 | Low |
| Cost guards (13.2) | None | — | Terraform settings, `max_bytes` on queries | NEW | P3 | Low |
| AGENTS.md amendments (14) | Old rules | — | Apply Section 14 text | ADAPT | P0 | Low |
| Cloud SQL / PostGIS, Memorystore, full Pub/Sub, Vertex Pipelines, canary, trained smoke detector, privacy filter, peak model, nowcast kriging, OIDC | Partly present locally (Timescale, Redis) | — | Not built; existing local pieces leave the default profile | DEFER | — | — |

## 2. Conflicts between the LLD and the code

These are not silently resolved; each records the smallest change chosen.

| Topic | LLD | Code | Decision |
| --- | --- | --- | --- |
| Model library | LightGBM quantile and classifier | sklearn `HistGradientBoosting*` because LightGBM needs a system `libomp` (`train.py:3-8`) | Default plugins use sklearn (`loss="quantile"` exists). A LightGBM plugin can register under the same family without pipeline changes. |
| Feature-name location | `libs/contracts/.../feature_spec.py` | Same | Kept there. The prompt's `libs/ml/features/` holds the pipeline, not the names. |
| Local history store | Parquet under `var/` | TimescaleDB | The cycle writes Parquet through `AnalyticsStore`. Timescale and the worker keep serving the old endpoints until Phase 12, then leave the default Compose profile. |
| Promotion | One reviewed YAML file | Six-stage registry | The resolver reads only `config/model_serving.yaml`. The old registry is read-only for `/models` until callers switch. |
| SG and NSW AQI tables | Copied from official sources with `source_url` | Not available | Shipped `status: unconfirmed` with no bands. API and UI show "—" with "AQI standard not yet confirmed". No band is typed from memory. |
| Package layout | LLD names new packages; the migration prompt proposes `libs/ingestion` etc. | `libs/connector_sdk`, `apps/connector` | Extend in place (decision 2026-10-04): plugin layer lives in `connector_sdk`. |
| Feature computation home | Not specified | `aeropulse_intelligence.features` | Kept as the one computation; `aeropulse_ml.features.FeaturePipeline` is the only entry point for training and the cycle. |
| Kafka / Redpanda | Two Pub/Sub topics; Redpanda locally | Four observation topics | The cycle does not use the observation topics. The legacy connector/worker path keeps them until retired. |

## 3. What KEEP means in practice

- `feature_spec.py` leak guard and `DERIVED_FROM`.
- `LiveHttpClient`, `Cursor`, `RateLimiter`, `CircuitBreaker`.
- `NOT_CONFIGURED` semantics.
- `process_snapshot` and the event engine as the deterministic event path (fixed, not rewritten).
- `validate_answer` grounding and the deterministic copilot fallback.
- Frontend single client and single Demo/Live branch.
- Observability stack.
