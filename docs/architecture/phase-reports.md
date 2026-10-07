# Migration phase reports

One section per phase of [migration-plan.md](migration-plan.md). The source of truth is
[LLD_AeroPulse_APAC.md](../LLD_AeroPulse_APAC.md).

Acceptance checks for every phase: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run pyright`, `uv run pytest tests/unit tests/contract -q`, `uv run aeropulse-ml parity`.

---

## Phase 1 — Audit and plan

**Completed.** Read the codebase against the LLD and wrote the four planning documents.

- **Files added:** `docs/architecture/current-state-audit.md`, `lld-gap-analysis.md`,
  `target-architecture.md`, `migration-plan.md`.
- **Code reused/replaced:** none (documents only).
- **Decisions:** extend in place (keep `connector_sdk`, add only the LLD-named packages);
  all four day-1 sign-offs and the Section 14 AGENTS.md amendments approved.
- **Tests:** baseline suite green before any change.
- **Next:** Phase 2.

---

## Phase 2 — Contracts, Region Packs, security fixes

**Completed.** Every canonical record can carry `region_id`, `grid_id` and a
`provenance_class`; the snapshot, plume, graph, source-health and citizen v2 contracts
exist; geography lives in validated Region Packs instead of code.

**Files added**

- Contracts: `provenance.py`, `meteo_forecast.py`, `likelihood.py`, `plume.py`, `graph.py`,
  `source_health.py`, `snapshot.py` under `libs/contracts/aeropulse_contracts/`.
- `libs/regions/` (new package `aeropulse-regions`): `models.py`, `loader.py`,
  `validator.py`, `registry.py`, `sites.py`, `cli.py` (`aeropulse-region validate|init`).
- `config/regions/{in-north,sg-singapore,au-nsw}/region.yaml`,
  `config/hazard_profiles/*.yaml`, `config/aqi_standards/*.yaml`,
  `config/model_serving.yaml` (empty `entries`), `config/citizen.yaml`.
- `tests/fixtures/regions/zz-synthetic/region.yaml` (fourth region, test-only).
- Tests: `tests/unit/test_region_packs.py`, `tests/contract/test_apac_contracts.py`.

**Files changed**

- Contracts `observation.py`, `fire.py`, `meteo.py`, `raster.py`, `citizen.py`,
  `__init__.py`: optional `region_id`/`grid_id`, `Provenance.provenance_class`,
  `CanonicalRecord` union, citizen v2 documents. v1 payloads still validate.
- `libs/common`: typed errors (`RegionPackError`, `RegionNotFoundError`, `StorageError`,
  `SnapshotNotFoundError`, `ModelServingError`, `LeakageError`); settings for platform,
  default region, config/data dirs, GCP and Earth Engine projects.
- `libs/auth/aeropulse_auth/jwt.py`: OIDC algorithms pinned (`RS256` by default; `none`
  and `HS*` refused), `exp`/`sub` required, cached JWKS client, `except jwt.PyJWTError`
  instead of a blanket catch.
- `infrastructure/docker/compose.yaml`, `.env.example`, `infrastructure/docker/.env.example`:
  the committed JWT and default secret removed; compose refuses to start without
  `AEROPULSE_JWT_SECRET`.
- `AGENTS.md`: Section 14 amendments; `aeropulse-region validate` after pack edits.
- `pyproject.toml`, `pyrightconfig.json`, `ruff.toml` (format excludes Markdown).

**Architecture decisions**

- Packs use `extra="forbid"`, H3 resolution is fixed at 8, `region_id` must match its
  directory, the source domain must contain the display area, and secret refs are names
  only (`AEROPULSE_*`, `env:NAME`, `projects/<p>/secrets/<name>`).
- Ground-truth and model-derived source lists may not overlap; Open-Meteo is
  model-derived in every region.
- Only CPCB is a confirmed AQI standard. Singapore NEA and NSW are marked unconfirmed
  with no bands, so the UI shows "—" with the reason rather than an invented band. The
  CPCB YAML is tested equal to the existing `CPCB_PM25_BANDS` and hazard threshold.
- Bushfire seasonality is unconfirmed (`seasonal_prior: null`). Plume release weights are
  settings to confirm, not measurements.
- Wind sites are placed deterministically: half the budget on the display area at
  resolution 5, the rest by farthest-point sampling over the source domain.
- Each pack source names its own replay `fixture`. Singapore and NSW have none, so
  replay there is "not configured" instead of replaying Indian data.

**Tests:** 503 → 540 passing. Added pack validation (containment, overlap, secret refs,
timezone, unknown fields, missing hazard/AQI, directory mismatch), CPCB band parity,
wind-site determinism, contract round-trips, and auth hardening (symmetric algorithm
rejected for OIDC, missing `exp` rejected, weak secret refused outside development).

**Failures fixed:** the previous OIDC test asserted the header-chosen algorithm (the
vulnerable behaviour) and now asserts the pinned one; early wind-site coarsening used
only 22 of 60 sites and was replaced by farthest-point sampling.

**Known limitations / deviations**

- The LLD says `jwt_secret` has no default. The development default is kept so local
  tests run, but settings refuse it (or anything under 32 bytes) outside
  development/test.
- `DEFAULT_BBOX`/`DEFAULT_SITES` remain in connectors for the legacy runner; removal and
  the grep test are Phase 14.

**Next:** Phase 3.

---

## Phase 3 — Plug-and-play connectors

**Completed.** Sources are discovered through the `aeropulse.connectors` entry point, take
their geography from a `ConnectorContext` built from a pack, and all run through one
`IngestPipeline`.

**Files added**

- `libs/connector_sdk/aeropulse_connector_sdk/plugin.py`: `ConnectorContext` (region,
  display/source bboxes, domain, mode, window, watermark, params, secret ref, fixture,
  sites, run id, resolver), `ConnectorResult`, `ConnectorPlugin` protocol, `BasePlugin`.
- `registry.py`: `PluginRegistry.discover()`, `available_source_ids()`,
  `UnknownSourceError`.
- `ingest.py`: `IngestPipeline` — configured? → fetch → archive raw → normalize per
  record → domain filter → stamp `region_id`, H3 `grid_id`, `provenance_class`,
  `dedup_key` → dedup → `SourceHealth`.
- `credentials.py`: `resolve_secret` for `AEROPULSE_*`, `env:` and Secret Manager refs.
- `legacy.py`: `LegacyConnectorAdapter` (replay-only wrapper for pre-plugin connectors).
- Plugins: `connectors/{openaq,firms,openmeteo}/.../plugin.py`, `connectors/cpcb/.../plugin.py`
  (legacy adapter).
- `connectors/earthengine/` (new): Sentinel-5P aerosol index reduced over H3 cells, plus
  `population.py` (WorldPop per H3 cell for onboarding). `earthengine-api` is an optional
  `live` extra.
- `libs/regions/aeropulse_regions/context.py`: `build_context(pack, entry, ...)` and
  `provenance_for(pack, source_id)` — the only place pack geography reaches a connector.
- Tests: `tests/contract/test_connector_plugins.py` (32 tests).

**Files changed**

- OpenAQ, FIRMS and Open-Meteo connectors accept explicit `live`, key and window
  arguments from the context. An explicit mode skips the global `connector_mode` gate in
  `LiveHttpClient`; leaving it unset keeps the old behaviour.
- Open-Meteo emits `meteo_forecast.v1` rows (wind at 10 m and 100 m, cloud cover, CAMS
  PM2.5) when the pack sets `keep_forecast_hours`.
- `aeropulse-region validate` checks pack sources against installed plugins.
- Connector `pyproject.toml` files register entry points; the root workspace adds
  `connectors/earthengine`.

**Code reused:** the existing connectors' fetch/normalize logic, `LiveHttpClient`, retry
and fixture loaders; CPCB runs unchanged behind the legacy adapter.

**Architecture decisions**

- `configuration_issue(context) -> str | None` instead of `is_configured -> bool`, so
  "not configured" always carries a reason. Updated in `target-architecture.md`.
- Region-level provenance overrides the plugin default: ground-truth sources are
  `measured`, model-derived sources `model_derived`.
- Forecast leak rule at the source: live forecasts use the fetch time as `issued_at`; a
  replay fixture must declare `issued_at` or no forecast is emitted, and a forecast issued
  after the cycle time is dropped.
- A fetch failure records only the exception type, never its message, because messages
  can contain credential-bearing URLs.
- Quality control is not in ingest; it moves to the shared preprocessing pipeline
  (Phase 4) so ingest and evaluation cannot disagree.
- No Earth Engine fixture is shipped, so no aerosol numbers are invented; replay without
  one is "not configured".

**Tests:** 540 → 572 passing. Entry-point discovery; every pack source has a plugin;
replay in in-north for OpenAQ, FIRMS, Open-Meteo and CPCB; Singapore and NSW replay is
not configured (no Indian data borrowed); live without a key is not configured; forecast
`issued_at <= t < valid_at`; domain filter, source-domain widening, dedup, provenance
override, per-record rejection, degraded state, isolated fetch failure without message
leak, raw archive key, watermark; Earth Engine configuration and replay mapping; secret
resolution.

**Known limitations**

- The legacy runner (`apps/connector`) still uses connector defaults; it switches to
  packs in Phase 8/14.
- Live Earth Engine and Secret Manager paths are not exercised in CI (no credentials).

**Next:** Phase 4 — shared preprocessing pipeline.

---

## Phase 4 — Shared preprocessing

**Completed.** One step list, used by the cycle (with `as_of` = cycle time) and by
training (with `as_of=None`, the per-row cut-off happening in the feature pipeline).

**Files added**

- `libs/ml/aeropulse_ml/preprocessing/batch.py`: `RecordBatch` (canonical records by
  kind, immutable), `PreprocessContext` (`region_id`, `as_of`, ground-truth and
  model-derived source sets; `for_region(pack, as_of=)`), `StepReport`, `PreprocessReport`.
- `steps.py`: `RegionFilter`, `AsOfCutoff`, `QualityControl`, `Deduplicate`,
  `LatestForecastIssue`, `StationsOutrankModel`, plus `label_observations`, `known_at`,
  `identity`.
- `pipelines.py`: `default_steps()`, `PreprocessingPipeline`, `PREPROCESSING_VERSION =
  "preprocessing-1.0.0"`.
- Tests: `tests/unit/test_preprocessing.py` (16), two ingest→preprocessing tests in
  `tests/contract/test_connector_plugins.py`.

**Files changed**

- `libs/connector_sdk/aeropulse_connector_sdk/ingest.py`: in replay mode, raw records are
  rebased to `fetched_at = context.now`.
- `libs/ml/pyproject.toml`: depends on `aeropulse-regions`.

**Code reused:** `aeropulse_connector_sdk.quality.evaluate_observation` (the worker's QC
rules, unchanged) and `aeropulse_common.hashing.dedup_key`.

**Architecture decisions**

- A batch holds typed canonical records, not a DataFrame: the existing feature builder
  consumes records, and keeping contracts past normalize is an AGENTS.md rule.
- Leak rules, by when a record became knowable: observations by `observed_at`,
  forecasts by `issued_at` (a forecast valid later is kept), rasters by
  `processing_time` (a daily product exists only after it is processed).
- `LatestForecastIssue` is a no-op in training: choosing the latest issue over the whole
  history would hand an early row a forecast issued after it.
- Stations outrank model-derived values per (H3 cell, hour, parameter); elsewhere CAMS
  values stay, labelled `model_derived`.
- Labels come only from the pack's ground-truth sources with `measured` provenance;
  CAMS is never a label, and a region with `ground_truth: none` has none.
- In a region run, records without a `region_id` are dropped rather than assumed local.

**Failures found and fixed:** running in-north replay end to end showed 110 Open-Meteo
aerosol rasters dropped as "processed after as_of". Connectors stamped the wall clock as
`fetched_at` in replay; the ingest pipeline now uses the replayed cycle time. A
regression test covers it.

**Tests:** 572 → 590 passing; ruff, format and pyright clean.

**Known limitations**

- The legacy worker still runs its own QC call; it is retired when the cycle replaces it
  (Phase 8).
- `sensor` quality (flatline/stuck detection) is still a neutral prior, as before.

**Next:** Phase 5 — `ml-features-3.0.0` and the single `FeaturePipeline`.

**Addendum (made during Phase 5):** station-over-CAMS precedence moved out of the shared
steps. In the shared path it removed the CAMS *feature* at station cells, and because it
keyed on floor hours a 12:30 station reading could remove a 12:00 CAMS value that serving
would still see, which broke parity. `StationsOutrankModel` is now opt-in
(`PreprocessingPipeline.for_display()`), keyed by hour-ending bucket, and used only for
what a cell displays. Preprocessing version is `preprocessing-1.1.0`.

## Phase 5 — `ml-features-3.0.0` and the single FeaturePipeline

**Completed**

- New transferable family sets `PM25_FORECAST` (46 features) and `HAZARD_24H`
  (`pm25_hazard_24h`, 40 features) in `FAMILY_FEATURE_SETS`; version
  `ml-features-3.0.0`. Legacy sets are unchanged so the current trainers keep running
  until Phase 6 replaces them.
- `FeaturePipeline` + `FeatureContext`: one entry point for training (`as_of=None`) and
  serving (`as_of=t`), built on the Phase 4 preprocessing.
- Region features from the pack: local-time encodings, `hazard_*` flags, seasonal flags
  from hazard profiles, `region_threshold_ugm3` from the AQI standard.
- Hazard label from the region's AQI averaging window; NaN when the standard is
  unconfirmed or the 24 h window is incomplete.
- Transport-weighted FRP from a back trajectory (new `aeropulse_intelligence.plume`
  geometry/trajectory module, reused by Phase 9).
- Family parity in `aeropulse-ml parity`; parity and `aeropulse-region validate` added
  to CI.
- `docs/ml/feature-pipeline.md`.

**Files added:** `libs/ml/aeropulse_ml/features/{tables,pipeline,parity}.py`,
`libs/ml/aeropulse_ml/testing.py`,
`libs/intelligence/aeropulse_intelligence/plume/{__init__,geo,trajectory}.py`,
`tests/unit/test_feature_pipeline_v3.py`, `docs/ml/feature-pipeline.md`.

**Files changed:** `libs/contracts/aeropulse_contracts/feature_spec.py`,
`libs/ml/aeropulse_ml/features/__init__.py`, `libs/ml/aeropulse_ml/cli.py`,
`libs/ml/aeropulse_ml/preprocessing/{steps,pipelines}.py`,
`libs/regions/aeropulse_regions/models.py` (`averaging_min_hours`),
`config/aqi_standards/cpcb_in.yaml`, `libs/intelligence/pyproject.toml` (numpy),
`.github/workflows/ci.yml`, `tests/unit/test_feature_spec.py` (version pin).

**Reused:** `DERIVED_FROM` leak declarations and the import-time leak assertion (now
applied to both registries); the legacy grid parity check stays as the first half of
`aeropulse-ml parity`.

**Architecture decisions**

- Family sets carry no coordinates, cell ids or region ids; an import-time check refuses
  any set that does, or whose derivation reaches a target or a future value.
- Hour-ending buckets everywhere a station or CAMS value is bucketed.
- CAMS stays a feature at station cells; it is never a label.
- Weather/forecast features come from the nearest pack wind site within 50 km, else NaN.
- Feature-definition constants live in the spec next to the names; changing one is a
  version bump.
- CPCB `averaging_min_hours: 16` is recorded with a note to confirm against the published
  NAQI technical note.

**Tests:** 590 → 616 passing (24 new pipeline tests plus contract updates), including:
corrupting the future leaves past rows identical; parity catches a lag that peeks one hour
ahead; CAMS injected at a station cell does not change labels; an unconfirmed SG standard
yields no hazard label. `aeropulse-ml parity`: 110 legacy grid-hours and 6 region/family
pairs, no divergence. Ruff, format and pyright clean.

**Failures found and fixed:** the precedence/parity bug above; a pandas key-dtype merge
failure when a region has no wind site (early return).

**Known limitations**

- The replay fixtures are single snapshots, so history-dependent parity runs on
  synthetic data (`aeropulse_ml.testing`, labelled test-only).
- Legacy feature builders and `_STUBBLE_MONTHS` remain until the Phase 6 trainers and
  the Phase 8 cycle replace their callers.

**Next:** Phase 6 — `ModelPlugin` and the four families, evaluation splits, baselines,
`DatasetSource`, and the train CLI with gate reports.

## Phase 6 — Model plugins, evaluation, baselines, datasets, train CLI

**Completed**

- `ModelPlugin` protocol and four families behind one registry
  (`aeropulse_ml.models.registry.PLUGINS`): `pm25_forecast` (P10/P50/P90 quantile
  models, quantiles sorted so they never cross), `pm25_hazard_24h` (classifier, isotonic
  calibration and operating threshold chosen on a separate calibration slice), `anomaly`
  (hour-of-week quantile tables with coarser fallbacks; uses the served forecast P90 when
  present), and `source_likelihood` (deterministic evidence weights from each hazard
  profile, never trained, never promoted).
- Evaluation strategies (`aeropulse_ml.evaluation.strategies`): purged rolling origin
  (purge = longest label horizon), leave-region-out, season check in each region's local
  months with purge and a 48 h embargo, and a calibration slice carved between fit and
  test with its own purge. A strategy that cannot run says why (`Unavailable` with a
  reason); it never silently passes.
- Metrics (`evaluation.metrics`): RMSE/MAE/bias per horizon, interval coverage, extreme
  recall, PR-AUC/ROC-AUC, Brier, expected calibration error, alert precision/recall/F1,
  false-alert rate, and an operating threshold chosen under a false-alert ceiling.
- Honest baselines per family (`baselines.families`): persistence, CAMS forecast and an
  hour-of-week climatology fitted on training rows only (forecast); current PM2.5,
  already-above-threshold and CAMS 24 h max (hazard); an absolute-threshold rule
  (anomaly). Gates require skill against each comparable baseline.
- Gate thresholds in one module (`aeropulse_ml.gates`), imported by the legacy trainer and
  the new plugins.
- `DatasetSource` with fixture replay (through `ingest_region`), local Parquet, BigQuery
  (parameterised queries, identifier validation, client loaded only in that adapter) and
  a synthetic source for tests. `open_dataset(uri)` picks one from a URI.
- `GateReport` contract (`gate_report.v1`) with dataset lineage (URI, kind, fingerprint,
  rows, regions, window, preprocessing version), per-region results per strategy, the
  artifact SHA-256, code commit and the servable flag. `EvalMetricRow` for the metrics
  table the ML evaluation page will read.
- Training runner `train_family(...)` and `aeropulse-ml train --family ... --dataset ...
  --regions ... --out ... --folds ...`. It writes `<out>/<family>-<ts>/model.joblib`,
  `gate.json` and `metrics.jsonl`, prints a JSON summary on stdout and a promotion
  snippet on stderr. It never writes `config/model_serving.yaml`.
- Saved models are hash-checked before unpickling (`load_model(path, expected_sha256=)`).
- Hazard profiles gained a `likelihood:` block (`evidence-weights-1.0`); the region
  validator refuses weights that name signals the profile does not list.
- `aeropulse_intelligence.source_evidence`: 13 deterministic signals with stated
  saturation constants and a ranked `SourceLikelihoodV2`. Unknown inputs contribute
  nothing and are reported with `value=None`.

**Files added:** `libs/ml/aeropulse_ml/{gates.py}`,
`libs/ml/aeropulse_ml/evaluation/{__init__,metrics,strategies}.py`,
`libs/ml/aeropulse_ml/baselines/{__init__,families}.py`,
`libs/ml/aeropulse_ml/features/local_time.py`,
`libs/ml/aeropulse_ml/datasets/{__init__,base,records,parquet,fixture,synthetic,bigquery}.py`,
`libs/ml/aeropulse_ml/models/{__init__,base,artifacts,forecast,hazard,anomaly,source_likelihood,registry}.py`,
`libs/ml/aeropulse_ml/training/{__init__,runner}.py`,
`libs/contracts/aeropulse_contracts/gate_report.py`,
`libs/intelligence/aeropulse_intelligence/source_evidence.py`,
`libs/regions/aeropulse_regions/ingest.py`,
`tests/unit/test_ml_evaluation_v3.py`, `tests/unit/test_ml_plugins.py`.

**Files moved (git mv, content unchanged):** `aeropulse_ml/evaluation.py` →
`evaluation/holdouts.py`; `aeropulse_ml/baselines.py` → `baselines/records.py`. Both
packages re-export the old names, so existing imports keep working.

**Files changed:** `libs/ml/aeropulse_ml/{cli,train}.py`, `libs/ml/pyproject.toml`
(pyarrow), `libs/intelligence/pyproject.toml` (aeropulse-regions),
`libs/common/aeropulse_common/{errors,__init__}.py` (`DatasetError`, `TrainingError`),
`libs/contracts/aeropulse_contracts/__init__.py`,
`libs/regions/aeropulse_regions/{models,__init__}.py` (`EvidenceWeights`,
`SEASONAL_PRIOR_SIGNAL`), `config/hazard_profiles/*.yaml`,
`libs/observability/aeropulse_observability/logging.py` (`stream=`), `uv.lock`.

**Reused:** the Phase 5 `FeaturePipeline` (one build per region, `labels=True`), the
Phase 3 connector registry and ingest pipeline (fixture dataset), the legacy holdout and
baseline modules (kept, re-exported), and the existing gate constants (moved, not
changed).

**Architecture decisions**

- **LightGBM is not installed; the families use scikit-learn HistGradientBoosting**
  (quantile loss for the forecast). The algorithm is recorded in every gate report.
  Swapping to LightGBM later is a plugin change and a model-version bump.
- Synthetic datasets are never servable, whatever the metrics. Source likelihood is a
  heuristic and its gate always fails with "never promoted".
- A region with no ground truth, or an unconfirmed AQI standard (no hazard threshold,
  so no hazard label), gets a stated reason instead of a metric.
- A feature that is entirely missing in a fold is filled with a constant for fitting and
  listed in `missing_in_training`; it is not silently dropped.
- Hazard "calibrated" requires a calibrated model, every fold calibrated, and mean ECE
  ≤ 0.05. Otherwise the score stays a rank.
- `crop_residue_burning` signal renamed `fire_frp_on_cropland_in_season` →
  `fire_frp_in_season`: no cropland mask exists, so the old name claimed more than the
  signal measures.
- Log lines go through a stream proxy that resolves `sys.stdout`/`sys.stderr` on every
  write, so the train CLI can move logs to stderr and keep stdout as clean JSON.

**Tests:** 616 → 657 passing (41 new), including: purge removes rows whose labels
overlap the test window; the calibration slice sits between fit and test; season check
uses local months and refuses missing coverage; climatology ignores test labels; forecast
quantiles never cross; hazard refuses a single class; anomaly falls back to coarser bins;
every profile signal is implemented; BigQuery rejects injected identifiers; the runner
writes report, artifact and metric rows and leaves `model_serving.yaml` byte-identical;
fold models never see their test rows; saved models round-trip only with the right hash.
Ruff, format, pyright clean; `aeropulse-ml parity` and `aeropulse-region validate` pass.

**Smoke run (synthetic, 288 h, three regions):** the forecast fails its gates (negative
skill vs persistence, coverage below 0.70); hazard and anomaly have labels only in
in-north; source likelihood is descriptive only; nothing is servable. That is the
expected honest result on synthetic data; no gate was lowered.

**Failures found and fixed:** HistGradientBoosting crashed on an all-NaN column in a fold
(now filled and reported); runner logs on stdout broke the CLI JSON (stream proxy); the
proxy first captured a stream object that test capture later closed (now resolved per
write); `DatasetSource` declared writable attributes that sources expose as read-only
(protocol now uses properties).

**Known limitations**

- `s5p_aerosol_index_anomaly` compares against fixed levels, not a per-cell climatology.
- `population_density` is unknown unless that column is present (no licensed population
  data in this build).
- The fixture dataset is a single replay snapshot, so real fixture training has very few
  labelled rows; meaningful gates need BigQuery or Parquet history.
- The legacy `train.py` trainers still exist for their current callers; Phase 7/8 move
  serving onto the plugins.

**Next:** Phase 7 — `model_serving.yaml` loader and `ModelResolver` that checks the gate
report, feature version, artifact presence and SHA-256 before serving, with the rule as
the degraded fallback.

## Phase 7 — Serving gates: `model_serving.yaml`, `ModelResolver`, post-processing

**Completed**

- `aeropulse_ml.serving.config`: strict `model_serving.v1` loader (`ServingEntry`,
  `ServingConfig`). Unknown keys, unknown families, invalid YAML and two entries for the
  same (family, region) are errors. A missing file means nothing is served.
- `aeropulse_ml.serving.resolver.ModelResolver`: checks every entry once, at startup,
  and refuses it (logged, with the reason) unless all of these hold:
  - the region exists and the family is a trained one (source likelihood is refused);
  - the gate report reads, and names the same family and model version;
  - its `ml_feature_version` and feature names match the current spec;
  - it was not built on synthetic data, it is servable, and this region passed;
  - an entry claiming `calibrated` has a report that agrees;
  - the artifact exists, its SHA-256 matches the pinned value before unpickling, and
    the loaded model names the same family, version and features.
- No entry, or a refused entry, means the rule answers with `degraded=true` and a
  reason: "no ground truth in this region", "AQI standard unconfirmed: no hazard
  threshold for this region", "no model passed the gate for <region>", or
  "model <version> refused: <why>". Source likelihood is the evidence-weights heuristic
  by design: `degraded=false`, `calibrated=false`, version from the hazard profiles.
- `served_models(region)` lists every family, so the "Served now" panel is never empty.
- Deterministic rules (`serving.rules`), returning the same columns as the plugins:
  `persistence-forecast-1.0` (P50 = latest value; no interval claimed),
  `persistence-hazard-1.0` (ramp to the region threshold; a rank), and
  `absolute-threshold-1.0` (anomaly at or above the region threshold).
- `aeropulse_ml.postprocess`: one path from model or rule output to `CellForecast`,
  `HazardState`, `AnomalyFlag` and `SourceLikelihoodV2`. No negative concentrations,
  no crossed quantiles, missing values stay `None`, and every record carries version,
  degraded flag, reason and `provenance_class`. Hazard is `calibrated` only when the
  served entry is.
- `serving.serve`: `serve_forecasts`, `serve_hazard`, `serve_anomalies` and
  `serve_source_likelihood`. If a served model fails at run time, the rule answers that
  cycle and the returned `Served` says "model <v> failed at serving: ...". The anomaly
  model uses the earlier cycles' model forecast P90 for the same hour (shortest lead)
  when one exists; degraded forecasts are never used for this.
- `aeropulse-ml serving [--strict]`: prints what answers each family in each region and
  any refusals. It exits 1 when the file is invalid, and with `--strict` when any entry
  is refused. Added to CI.
- `artifacts.LocalArtifactReader`: plain paths and `file://`; relative URIs resolve
  from the repo root (the parent of `config/`). Other schemes are refused with
  "no reader configured", so the storage adapter in Phase 8 supplies the `gs://`
  reader behind the same `ArtifactReader` protocol.

**Files added:** `libs/ml/aeropulse_ml/serving/{__init__,config,artifacts,resolver,rules,serve}.py`,
`libs/ml/aeropulse_ml/postprocess.py`, `tests/unit/test_ml_serving.py`.

**Files changed:** `libs/ml/aeropulse_ml/cli.py` (`serving`),
`libs/ml/aeropulse_ml/models/{forecast,hazard,anomaly,source_likelihood}.py` (`family`
typed as `ModelFamily`), `libs/ml/aeropulse_ml/datasets/base.py` (read-only protocol
properties), `libs/ml/pyproject.toml` (pyyaml, which it now imports directly),
`config/model_serving.yaml` (header lists every check), `.github/workflows/ci.yml`,
`uv.lock`.

**Reused:** the `GateReport` and `load_model(expected_sha256=)` from Phase 6, the plugin
registry, the Phase 6 hazard profiles' evidence weights (via
`aeropulse_intelligence.source_evidence`), and the existing snapshot contracts.

**Replaced (not yet removed):** the legacy `ModelRegistry.champion()` path and
`apps/api/aeropulse_api/hazard_store.py` still serve the old `/models` and hazard views.
They are removed in Phase 12, once the API reads served records from the snapshot.

**Architecture decisions**

- Checks run at startup, not per request; lookups are then O(1).
- A refused entry degrades that one (family, region) pair; it does not stop the process.
  A malformed file is an error, because it is reviewed in git and CI checks it.
- Calibration is claimed only when the entry, the report and the region's gate all agree.
- The hazard rule's ramp floor (`HAZARD_RAMP_FLOOR_FRACTION = 0.25`) is a stated
  setting derived from the legacy 30/121 ramp. Its output is a rank, not a probability.
- An anomaly flag's `score` is how far the value is past the expected high, in units of
  the upper spread, capped at 1. It is a severity, not a probability.

**Tests:** 657 → 696 passing (39 new). They cover:
- the repo file serves only rules, with reasons;
- invalid files and duplicate pairs are rejected;
- a passing entry serves only its own region;
- each refusal reason is reported: failed gate, missing region result, feature version,
  feature names, not servable, family/version mismatch, no pinned hash, hash mismatch,
  synthetic data, missing file, `gs://` without a reader, false calibration claim,
  unknown region, heuristic family;
- a tampered artifact is refused before unpickling;
- rule outputs, post-processing order/clipping/None, and calibrated only when served;
- the run-time fallback, the prior forecast P90 for anomaly, heuristic source records;
- the CLI's exit codes.

Ruff, format and pyright are clean; `aeropulse-ml parity`, `aeropulse-region validate`
and `aeropulse-ml serving --strict` pass.

**Failures found and fixed:** a test assumed the urban class name; it now reads the
classes from the catalog.

**Known limitations**

- Shadow scoring of challengers is not wired yet; it runs in the Phase 8 cycle after the
  served answer exists.
- `gs://` artifacts need the Phase 8 storage reader.
- No model has passed a gate on `ml-features-3.0.0`, so every trained family is served
  by its rule today. That is the honest state, not a placeholder.

**Next:** Phase 8 — `libs/storage` adapters and factory, `apps/cycle` orchestrator and
stages using `ingest_region`, `FeaturePipeline`, `ModelResolver` and `serving.serve`;
rule fixes; idempotent snapshot writes; in-north golden test.

---

## Phase 8 — Storage adapters, the region cycle, rule fixes, golden test

**Completed**

- `libs/storage` (LLD 3.5): one factory, `build_storage(settings)`, picks every adapter
  from `AEROPULSE_PLATFORM`.
  - `ObjectStore`: `FilesystemObjectStore` (dev, tests, CI), `MinioObjectStore`
    (Compose), `GcsObjectStore`. `put` raises on failure.
    `if_generation_match` follows Cloud Storage (`0` = must not exist). Keys are
    validated (no `..`, no absolute paths). V4 signed upload URLs carry
    `x-goog-content-length-range`.
  - `AnalyticsStore`: `ParquetAnalyticsStore` and `BigQueryAnalyticsStore`. `query`
    takes a template id and parameters only, never free SQL. Each template states its
    BigQuery SQL and its local equivalent side by side. BigQuery loads are batch jobs
    with deterministic job ids. Queries are parameterised and capped by
    `maximum_bytes_billed`.
  - `ObjectSnapshotStore`: the versioned snapshot object is written first, and
    `latest.json` moves only after that succeeds. It only moves forward, only for
    `live`, and with a generation precondition (retried on a concurrent writer).
  - `ObjectRawArchiver` (the ingest `RawArchiver`) and `ObjectArtifactReader` (`gs://` /
    `s3://` model artifacts; the resolver still checks the SHA-256 before unpickling).
- `apps/cycle` (LLD 3.4): `CycleRunner.run(region, cycle_time, mode)` and
  `aeropulse-cycle --region R|all --mode live|backfill|replay`. The stages are:
  1. `ingest_region`, resuming live sources from the stored watermarks;
  2. raw archive;
  3. raw rows loaded as `(region_id, known_at, record)`;
  4. a 72 h history window read back through the templates;
  5. `PreprocessingPipeline` at the cycle time;
  6. deterministic detection, seeded with the previous snapshot's open events;
  7. both feature frames through `FeaturePipeline`;
  8. `ModelResolver` plus `serving.serve` for all four families;
  9. map layers: cells with region-standard AQI bands, fire clusters, wind;
  10. the snapshot;
  11. prediction, source-health and cycle rows;
  12. alerts (live only).
- Rule fixes (LLD 5.2), all in `libs/intelligence`:
  - `baseline-idw-0.2`: the PM2.5 estimate interpolates ground stations only, using
    observations from the same UTC hour.
  - The CAMS value for an event forecast is located to the cell and hour: a raster for
    the cell, then a raster covering the cell centre, then a model-derived point in the
    same cell-hour. Previously it was the last value anywhere.
  - `process_snapshot` takes `history_by_grid` and `model_derived_sources`.
- Golden test (`tests/golden/test_in_north_events.py`): a replay cycle on the in-north
  fixtures produces exactly the four events the old worker path did (same cells,
  severities, statuses). The intended differences are listed in the test's docstring;
  none changes an event on these fixtures.

**Files added:** `libs/storage/{pyproject.toml, aeropulse_storage/{__init__,errors,objects,analytics,snapshots,archive,artifacts,factory}.py}`,
`apps/cycle/{pyproject.toml, aeropulse_cycle/{__init__,cycle,detection,views,main}.py}`,
`tests/golden/{in_north_events.json,test_in_north_events.py}`,
`tests/unit/{test_storage,test_cycle}.py`.

**Files changed:** `libs/intelligence/aeropulse_intelligence/{estimator,detect}.py`
(the rule fixes), `libs/ml/aeropulse_ml/datasets/parquet.py` (also reads the cycle's
analytics layout, so local training uses the history the cycle wrote),
`libs/common/aeropulse_common/settings.py` (`local_object_store`, `bigquery_max_bytes`;
`gcs_bucket` is now a bucket-name prefix), `tests/unit/test_baselines_registry.py`
(reads `ESTIMATOR_VERSION`), `pyproject.toml` (workspace members, `tests/golden` in
testpaths), `pyrightconfig.json`, `.github/workflows/ci.yml` (`tests/golden`),
`.env.example` (setting names only, no values), `.gitignore` (`var/`), `uv.lock`.

**Reused:** `ingest_region` and `IngestPipeline` (Phase 3); `PreprocessingPipeline`,
including the display variant (Phase 4); `FeaturePipeline` and both family feature sets
(Phase 5); `datasets.records.encode/decode` and the BigQuery raw table names (Phase 6);
`ModelResolver` and `serving.serve` (Phase 7); `process_snapshot`, `EventStore` and the
event rules, unchanged in behaviour; the `RegionSnapshot` contract (Phase 2).

**Replaced (not yet removed):** the long-lived worker (`apps/worker`) still runs the
Kafka path. The cycle does not import it. It is retired once the API reads snapshots
(Phase 12) and Compose runs the cycle (Phase 14).

**Architecture decisions**

- **Replay never reaches Live.** A `replay` cycle reads recorded fixtures. It writes no
  raw history and no analytics rows. Its snapshot (`mode: backfill`; every source's
  health says `replay`) lives under `replay-snapshots/`, so it cannot overwrite a real
  snapshot or move the live pointer.
- **Backfill has its own snapshot keys** (`snapshots/{region}/backfill/{t}.json`). The
  live pointer names a live object; a backfill of the same hour overwrote it until a
  test caught it. Backfill never raises alerts; they are counted as suppressed.
- **Raw batch ids come from record identities**, the same identity the dedup step uses,
  not from content. A re-fetch stamps a new `observation_id` and `received_at` on the
  same measurement. So an identical re-run rewrites its own batch, and a partial re-run
  adds a batch that dedup collapses on read. An empty load never deletes a batch.
  Derived rows (predictions, health, cycles) are a run log keyed by content and carry
  `generated_at`; readers take the newest.
- **The live cycle's `now` is the wall clock; its `as_of` is the cycle hour.** Records
  observed after the hour wait for the next cycle, which the watermark overlap
  re-fetches.
- **AQI bands use the standard's own averaging.** CPCB is a 24 h mean of at least 16
  hourly values. Otherwise the band is `null` with a `field_status` reason saying how
  many values exist. Unconfirmed standards (`sg_nea`, `au_nsw_aqc`) show their own
  reason.
- **Detection skips stale cells:** a cell whose newest PM2.5 is over 3 h old is not
  evaluated, so history never re-opens a day-old event. Display uses the same 3 h rule.
- **Credentials:** MinIO keys come only from `SecretStr` settings; Google Cloud uses
  Application Default Credentials. No credential value appears in code, YAML or
  `.env.example`; the codeguard hardcoded-credentials rule was applied to every new
  file. Failure logs record exception types, never messages that could carry a URL.

**Tests:** 696 → 738 passing (42 new; `tests/golden` now runs in CI).

Storage:
- generations and preconditions on the filesystem and fake MinIO/GCS clients;
- key validation; signed-URL size cap;
- analytics idempotence, templates-only queries, the half-open window, watermarks;
- BigQuery identifier checks;
- snapshot pointer rules: forward only, live only, not after a failed write, retried
  on a race, replay prefix, backfill isolation;
- corrupt snapshots fail loudly;
- artifact fetch; factory per platform.

Cycle:
- replay isolation;
- a live cycle writes history, snapshot, pointer and alerts;
- every family reports what answered and why, and hazard is never calibrated;
- idempotent re-runs;
- the next cycle uses watermarks, history and carried events; closed events are not
  carried;
- backfill neither moves the pointer nor alerts; an older live cycle does not move a
  newer pointer;
- unknown modes are refused; one failing region does not stop the others;
- training reads the cycle's history; the CLI summary.

Golden: the event baseline, and model-only cells get no station estimate.

Ruff, format and pyright are clean. `aeropulse-ml parity`, `aeropulse-region validate`
and `aeropulse-ml serving --strict` pass.

**Failures found and fixed:** the backfill/live key collision and the content-hash raw
batch ids described above; a test that counted hidden metadata files; pyright
narrowing in four places.

**Known limitations**

- Shadow scoring is not wired: `model_serving.yaml` has no challenger entries yet, so
  there is nothing to shadow. The hook is the point after `_serve`.
- Event ids and `created_at` still come from the engine's `new_ulid()` and the wall
  clock, so a re-run gives the same events with new ids. Stable ids arrive with
  incidents in Phase 10.
- Evidence items are not stored in the snapshot, so a carried event's `evidence_ids`
  restart from the evidence of the current cycle.
- Plumes, incidents and citizen watches are empty, with a `field_status` reason each;
  Phases 9–11 fill them.
- The BigQuery tables need schemas before the first load; Terraform creates them in
  Phase 14. The MinIO precondition is check-then-write (safe with one writer per
  region, which the cycle guarantees); Cloud Storage enforces it server-side.

**Next:** Phase 9 — the Lagrangian ensemble plume package (forward, backward, exposure,
arrivals) with the LLD 8.8 tests, run as a cycle stage.

---

## Phase 9 — Lagrangian ensemble plume (`lagrangian-ens-1.0`)

**Completed**

- `aeropulse_intelligence.plume` gains the ensemble model next to the Phase 5
  trajectory helpers, which still feed `transport_weighted_frp`. Deterministic NumPy;
  no language model.
  - `wind.py` builds a time-varying `WindField` over the region's weather sites:
    inverse distance in space, linear in time.
    - `forecast_wind` takes, for each site and valid hour, the newest run issued by
      the cycle time. It blends 10 m and 100 m by the hazard profile's
      `release_level_weights`.
    - Site-hours no forecast covers are filled from observed hours up to the cycle
      time (Global LLD 7.2).
    - `observed_wind` drives backward runs.
    - Gaps become degraded reasons instead of guesses: `persisted_wind_after_<hour>`,
      `persisted_wind_before_<hour>`, `wind_missing_hours_<n>`,
      `no_100m_wind_10m_used`, `observed_wind_10m_only`.
  - `stability.py` sets turbulent spread from published tables:
    - Pasquill stability class from 10 m wind, solar elevation and cloud, as
      tabulated by Turner (1970). Unknown cloud or heavy overcast gives neutral D.
    - Briggs (1973) rural σ_y. Each step adds σ_y(x+dx)² − σ_y(x)² of variance, which
      is 2·K_h·dt.
  - `uncertainty.py` measures wind-forecast error per lead bucket from
    forecast-versus-observed pairs. It needs at least 7 days of pairs, per LLD 8.2.
    Until then the spread is zero and every forward plume carries
    `wind_uncertainty_unmeasured`.
  - `ensemble.py` runs 200 particles at a 15 min step, both settings from LLD 8.2:
    - RK2 midpoint steps through the time-varying field.
    - Each particle's wind error follows an AR(1) speed factor and direction offset.
    - Diffusion uses the Briggs variance above.
    - Wet removal is weight-only, forward only, using HYSPLIT's default below-cloud
      scavenging coefficient.
    - Particles leaving the source domain stop counting and are reported.
  - `outputs.py` turns a run into results:
    - P50 and P90 footprints are the smallest cell sets holding that share of the
      weight. Cells are resolution 8 inside the display area and 6 outside it.
    - The centreline is the median particle position.
    - `PopulationIndex` handles mixed-resolution population cells. A fine cell under
      a coarse ancestor takes a 1/7^Δres area share and is counted once.
    - Place arrivals give a probability and a median first-arrival time.
    - Backward source candidates are fire clusters inside the swept back-trajectory
      footprint: the res-6 cells holding 90% of particle passes. Each carries its
      particle fraction, distance and bearing.
  - `engine.py` provides `simulate()`, which returns a `plume.v1`:
    - `model_version` is `lagrangian-ens-1.0`.
    - `provenance_class` is `simulated` and `experimental` is true.
    - Degraded reasons are collected from every input.
    - The run's settings are recorded on the plume.
    - Plume ids are deterministic, and the random stream is seeded from the id.
- `libs/storage` gains `ObjectPlumeStore` in the serving bucket:
  - Live plumes go to `plumes/{region}/{plume_id}.json` and backfill plumes to
    `plumes/{region}/backfill/`.
  - Replays go to `replay-plumes/`.
  - `Storage.plumes` and `Storage.replay_plumes` expose them.
- `apps/cycle` gains a plume stage (`plumes.py`) between serving and the snapshot:
  - The transport profile is the region's first hazard with plume defaults:
    crop_residue_burning for in-north, transboundary_haze for sg-singapore,
    bushfire_smoke for au-nsw.
  - Forward runs: the top 5 fire clusters by FRP plus open events (5 at most).
    Backward runs: anomaly flags (5 at most), over 6, 12 and 24 h. All caps are
    settings.
  - Full plumes are written to the plume store; `snapshot.plumes` carries the
    summaries.
  - The old "not in this cycle yet" status is gone. `plumes.exposure` and
    `plumes.arrivals` instead name the missing onboarding file
    (`population_h3r8.parquet`, `gazetteer.parquet`). When the files exist they are
    read from the region directory.
  - Fire clusters now group at H3 resolution 6, as LLD 8.2 states; they were at 5.
  - The CLI summary and the `cycle.finished` log carry the plume count.

**Files added:** `libs/intelligence/aeropulse_intelligence/plume/{wind,stability,uncertainty,ensemble,outputs,engine}.py`,
`libs/storage/aeropulse_storage/plumes.py`, `apps/cycle/aeropulse_cycle/plumes.py`,
`tests/unit/test_plume.py`, `tests/unit/test_cycle_plumes.py`.

**Files changed:** `libs/intelligence/aeropulse_intelligence/plume/__init__.py` (exports),
`libs/storage/aeropulse_storage/{__init__,factory}.py`,
`apps/cycle/aeropulse_cycle/{cycle,views,main}.py`.

**Reused:**
- The `plume.v1` contract and `PlumeSummary.from_plume` (Phase 2).
- Hazard profile `plume_defaults` (Phase 2).
- `plume/geo.py` (Phase 5).
- `geometry.haversine_km` and `geometry.bearing_deg`.
- The storage `ObjectStore` and the factory (Phase 8).

`wind-advection-0.1` in `forecast.py` is unchanged. It still draws event forecast
paths and remains the baseline the ensemble must beat (LLD 8.7).

**Architecture decisions**

- **No invented spread.** Turbulence comes from cited tables. Wind-forecast spread is
  measured or zero, never guessed, and zero spread is flagged degraded. The only
  numbers that are not cited are labelled settings: particle count, time step,
  run caps, the AR(1) correlation time, the IDW floor, and the default place radius
  when the gazetteer has none.
- **Plume ids are keyed by what is simulated:** region, cycle, direction, origin kind,
  location and initial spread, not `ref_id`. Event ids are not yet stable (a Phase 8
  limitation), so keying by `ref_id` would leave a new orphan object on every re-run.
  With this key a re-run overwrites its own plume.
- **The backward footprint is the swept area, not a single horizon.** "Fires inside
  the back-trajectory footprint" is about where the air passed over, which a snapshot
  at 6, 12 or 24 h misses.
- **Missing onboarding data is a `field_status`, not a degraded transport.** The
  footprint is still valid without WorldPop. Exposure is left empty with a reason
  rather than shown as zero.

**Tests:** 738 → 765 passing (27 new).

LLD 8.8:
- uniform wind moves speed × time with no 37 km cap (432 km over 12 h);
- a 90° wind turn bends the centreline;
- zero spread collapses P50 and P90 to the centreline cell;
- backward then forward returns within 1 km (no spread) or 15 km (with spread);
- missing forecast hours, including interior gaps, set degraded reasons;
- exposure is zero over an empty population raster and absent when none is built;
- backward runs list only fires inside the back-trajectory.

Beyond 8.8:
- exposure with a coarse-ancestor share;
- arrivals with probability and ETA;
- rain removes weight;
- measured uncertainty widens the P90;
- domain exits are reported;
- determinism;
- spot checks of the Pasquill table and solar elevation;
- the 7-day pair rule;
- the observed-wind fallback.

Cycle:
- replay plumes never reach the live plume store;
- forward plumes on forecast-free fixtures persist observed wind and say so;
- stable re-runs;
- onboarding files fill exposure and arrivals (with `min_population` applied);
- "nothing to seed" is stated.

Ruff, format and pyright are clean. `aeropulse-ml parity`, `aeropulse-region validate`
and `aeropulse-ml serving --strict` exit 0.

**Failures found and fixed:**
- The first source-candidate footprint used per-horizon positions, which miss fires
  the air passed between horizons. It now uses the swept area.
- Plume ids and event-plume order depended on random event ids. Ids are now keyed
  by the physics and events are ordered by cell.
- The in-north replay fixtures have no forecast hours, so forward runs were skipped
  until the Global LLD 7.2 observed-wind fallback was added.
- Pyright: typed gazetteer rows, `Literal` level keys and a float64 time axis.

**Known limitations**

- Briggs σ_y is an open-country fit for tens of kilometres. Beyond that, real spread
  is dominated by wind-forecast error, which stays zero (and is flagged) until 7 days
  of forecast-versus-observed pairs exist. The cycle reads 72 h of history, so live
  plumes are degraded until a longer error window is read from `raw.*`.
- The boundary-layer-height shift toward 100 m wind (Global LLD 7.2) is not applied;
  the profile weights alone set the blend.
- Observed wind is 10 m only, so every backward plume carries
  `observed_wind_10m_only`.
- No population or gazetteer files exist for any region yet (onboarding needs
  WorldPop and GeoNames access), so exposure and arrivals are empty with reasons.
- The LLD 8.7 evaluation (station hit rate, spread calibration) is not run. The plume
  stays "experimental" and `wind-advection-0.1` is not replaced for event forecasts.
- Citizen-report and operator what-if origins are supported by the contract and the
  engine but not triggered yet (Phases 11 and 12). Backward runs for high-hazard
  station cells wait for a calibrated hazard threshold.

**Next:** Phase 10 — the graph builder and stable incidents as a cycle stage, with
plumes as `on_back_trajectory_of` and reach edges.

## Phase 10 — Environmental Intelligence Graph and stable incidents (`eig-1.0`)

**Completed**

- **Stable event ids (the Phase 8 promise).**
  - `EventStore` gains `clock` and `ids` (`(prefix, key) -> id`). The defaults are the
    wall clock and ULIDs, so the API, worker, demo seed and existing tests are unchanged.
  - The engine stamps events with `store.clock()`. Event ids are keyed by
    `<cell>|open` or `<cell>|rejected`, evidence ids by `<cell>|<evidence type>`, and
    alert ids by the event id. `alert_from_event` takes optional `now` and `alert_id`.
  - The cycle's `seed_store(previous, region_id=, cycle_time=)` injects the cycle time
    and `cycle_ids()`: `<prefix>_` plus the first 24 hex characters of
    sha256(region | cycle time | prefix | key). A re-run now reproduces the same
    events, evidence and alerts.
- **A re-run no longer reads its own output as the previous cycle.** Live mode used the
  latest pointer. On a re-run of hour `t` that pointer is `t` itself, so open events
  were seeded from the run being replaced. `CycleRunner._previous` now takes the
  pointer only when it is older than `t`, and otherwise reads the snapshot for
  `t − 1 h` (live first, then backfill).
- **`aeropulse_intelligence.graph`** builds the graph deterministically.
  - Node ids:
    - `fire_cluster:<rid>:<cluster>`, `anomaly:<rid>:<cell>:<time>`,
      `pollution_event:<rid>:<event>`, `plume:<rid>:<plume>`;
    - `cell:<r6>`, `station:<source>:<cell>`;
    - `place:<rid>:<place>`, `wind_run:<rid>:<issued time | observed:cycle>`,
      `region:<rid>`, `incident:<rid>:<incident>`.
  - Edges (all from the LLD 10.1 vocabulary):
    - fire, anomaly and event `located_in` their resolution-6 cell;
    - fire or event `emits` its forward plume;
    - wind run `drives` plume;
    - plume `reaches` place, with probability, ETA and gazetteer population;
    - plume `exposes` region, with P90 population, horizon and source;
    - station `observes` anomaly (only where the cell's value is a measured station);
    - anomaly `traced_by` backward plume;
    - backward plume `on_back_trajectory_of` fire, with particle fraction, distance
      and bearing;
    - incident `groups` member.
  - Every attribute is a `GroundedValue` with a source id and provenance class:
    - plume values are `simulated` under the model version;
    - fire values are `measured` under the FIRMS source ids;
    - an anomaly's observed PM2.5 is `measured` under the station source when the cell
      is a station, and otherwise takes the flag's class;
    - event fields are `heuristic` under the engine versions;
    - gazetteer names and populations are `model_derived` reference data.
  - Edge ids hash (region, cycle, kind, src, dst).
- **Incidents (LLD 10.2 rule).**
  - An incident is a connected component that holds a fire cluster or anomaly *and* a
    forward plume with a `reaches` edge, or that holds an event in CONFIRMED,
    FORECASTING, ACTIVE or DECLINING (a setting).
  - Context nodes (region, place, wind run) do not join components.
  - Incident ids carry over through a greedy one-to-one match on shared stable nodes
    (fire cluster, event, cell, station). The match takes the largest overlap first,
    requires at least 1 shared node (a setting), and only within the same region.
    `first_seen` carries over too.
  - A new id is `inc_` plus a hash of (region, cycle, root node ids).
  - `root_kind` priority: fire cluster, anomaly, event, citizen report.
  - Each summary carries its members, the context nodes they touch, and every edge
    touching a member.
- **Cycle stage.**
  - After plumes, the cycle builds the graph from the fires, anomalies, events,
    full plumes and display cells. `find_incidents` runs against the previous
    snapshot's incidents and fills `snapshot.incidents`.
  - The "incident graph is not in this cycle yet" status is gone.
  - Live and backfill load `graph.nodes` and `graph.edges` (with `cycle_time` and
    `record` JSON) under content-derived batch ids. Replay writes no graph rows.
  - The `cycle.finished` log carries the incident count.
  - On the in-north fixtures: 27 nodes, 32 edges and 1 incident. Its root is the
    anomaly that shares a cell with the ACTIVE event; it reaches no place, because no
    gazetteer exists yet. The incident keeps its id into the next hour.

**Files added:** `libs/intelligence/aeropulse_intelligence/graph.py`,
`tests/unit/test_graph.py`.

**Files changed:** `libs/intelligence/aeropulse_intelligence/{engine,alerts,detect}.py`,
`apps/cycle/aeropulse_cycle/{cycle,detection}.py`, `tests/unit/test_cycle.py`.

**Reused:**
- The `graph_node.v1`, `graph_edge.v1` and `incident.v1` contracts, and
  `snapshot.incidents` (Phase 2).
- The `graph.*` analytics tables and `batch_id` (Phase 8).
- Plume arrivals, exposure and source candidates (Phase 9).

`lineage.py` (the per-event evidence graph used by `/events/{id}/graph`) is
unchanged. It is a different, event-local view that the API still serves until
Phase 12.

**Architecture decisions**

- **Co-location is a shared H3 resolution-6 cell, not a radius.** That is the
  fire-cluster resolution (LLD 8.2), so no distance threshold is invented. A fire and
  an anomaly 30 km apart are joined only by a plume edge.
- **Places do not join components.** Otherwise every fire heading for Delhi would
  merge into one incident. The shared place still shows in each incident's subgraph.
- **A FIRMS product is not a node.** `NodeKind` has no product kind, so the LLD
  `detected_by → FIRMS product` link is carried as the fire's `source_id` on every
  attribute. Population is likewise an edge attribute, not a node.
- **Incident ids follow stable nodes only.** Plume and anomaly ids change every cycle
  by design; cells, fire-cluster parents and carried events do not.
- **Deterministic ids everywhere in the cycle path** (events, evidence, alerts, plumes,
  edges and incidents), so "re-run is idempotent" holds for the content, not just the
  row counts.

**Tests:** 765 → 775 passing (10 new, plus a stronger idempotence test).
- Graph:
  - edges stay inside the vocabulary, with no `caused`;
  - every value carries a source id and provenance class;
  - plume edges are `simulated`;
  - station-observed PM2.5 is `measured`;
  - the graph is deterministic;
  - a fire whose plume reaches a place is an incident (with place ids and its
    context subgraph);
  - unreached plumes and resolved or detected events are not incidents;
  - an active event alone is an incident;
  - a back trajectory joins anomaly and fire;
  - two fires reaching one city stay two incidents;
  - ids survive the next cycle on overlap, and a new component gets a new id;
  - a previous incident is inherited by one component only and never across regions.
- Cycle:
  - a live re-run reproduces event ids, `created_at` and alert ids;
  - graph rows are loaded;
  - the incidents status is gone;
  - incident ids hold across a re-run, and carry into the next hour with `first_seen`
    kept.

Ruff, format and pyright are clean. `aeropulse-ml parity`, `aeropulse-region validate`
and `aeropulse-ml serving --strict` exit 0.

**Failures found and fixed:**
- The re-run of a live hour read its own snapshot as "previous" (described above).
- Pyright: a `None`-narrowed exposure value, and a test event missing fields whose
  defaults are declared positionally.

**Known limitations**

- Citizen-report nodes and the `consistent_with` / `near` edges wait for Phase 11.
  `upwind_of` is in the vocabulary but not produced.
- Incidents reach no places on any region until gazetteer files are onboarded
  (Phase 9 limitation).
- The graph is rebuilt per cycle, not after each citizen analysis (LLD 10.2); that
  trigger comes with the citizen analyzer.
- `aeropulse_graph.*` rows are a per-cycle log. Readers take the newest cycle; there is
  no compaction yet.
- Event ids are stable per re-run of a cycle. Two different cycles that open an event in
  the same cell still get different ids, as intended.

**Next:** Phase 11 — `libs/vision` (sanitize, geo-check, Gemini observer), deterministic
corroboration, and `apps/citizen_analyzer`, with citizen nodes joining the graph.

## Phase 11 — Citizen Smoke Intelligence (LLD APAC 9)

**Completed**

- `libs/vision`, the photo side only:
  - `sanitize`: checks type by magic bytes, size, pixel limit (decompression bomb) and
    animation. It reads GPS, capture time and camera bearing from EXIF, then re-encodes
    to JPEG so the stored copy has no metadata. A naive EXIF time is resolved in the
    pack's timezone, never assumed UTC.
  - `geo_trust`: a weighted score from region membership, EXIF-to-claim distance,
    device accuracy, time consistency and duplicate hash. A claim outside the region
    is untrusted whatever the score. `observed_at` is set only from a consistent EXIF
    time, never from server time.
  - `GeminiObserver`: `google-genai` with structured output (`response_json_schema`),
    no tools and temperature 0.1. It uses an API key or Vertex AI (ADC).
  - The validator rejects any response outside the categorical schema, and any
    `scene_summary` with a figure (digits, number words, units). A failure gives
    `ai_observation_unavailable` or `ai_observation_invalid` and no observation;
    nothing falls back to a keyword guess.
  - `evaluation`: per-class precision and recall, with `None` where undefined. Every
    item must state its licence. Rows use the `aeropulse_eval.reports` shape.
- `aeropulse_intelligence.corroboration`, deterministic:
  - Seven signals: fire nearby, fire on the camera bearing, fire upwind, on a plume's
    P90 path, station PM2.5 elevated or rising, aerosol index, active event.
  - Radii, windows and per-class weights come from `config/citizen.yaml`. A signal
    that cannot be checked is neutral (`supports=None`). The result is `heuristic`.
  - It applies the LLD 9.6 decision table.
  - The plume origin is the matched hotspot when the bearing supports it, otherwise
    the reporter, with a wider starting spread.
- `apps/citizen_analyzer` (`aeropulse-citizen analyze | eval | serve`):
  - The stages run sanitize → geo-trust → observe → corroborate → decide.
  - Each stage writes `reports/{id}.json` under a generation precondition before the
    next stage starts. A finished report is not analysed again.
  - `seed_plume` runs a forward plume through the shared `RegionTransport`, links the
    current incident (by matched fire or the report's cell), writes the report's own
    subgraph rows, and raises a citizen-watch alert. The alert fires only if a
    populated place is reached within `watch_reach_hours`.
  - Moderation covers accept, reject and set class.
  - The Pub/Sub push endpoint parses the Cloud Storage `objectId`. A failure returns
    500, so the message is retried and then dead-lettered.
- Cycle: a citizen stage reads `citizen.reports` over `seed_window_hours`, keeps the
  latest row per report, and carries the seeded ones (capped):
  - plume origins;
  - `snapshot.citizen_watches` (rounded point, class, corroboration, plume id);
  - graph nodes.

  The "citizen corroboration is not in this cycle yet" status is gone. Replay carries
  no citizen reports, and says so.
- Graph: `citizen_report` nodes, with these edges:
  - `located_in`;
  - `consistent_with` (seeded by the report, or the report inside a plume's P90);
  - `near` (the matched fire).

  A report joins the fire's incident but never qualifies one by itself.

**Files added:**
- Vision library:
  - `libs/vision/` (`sanitize`, `geotrust`, `observer`, `gemini`, `evaluation`);
  - `prompts/observer_v1.md`.
- Citizen analyzer app:
  - `apps/citizen_analyzer/` (`analyzer`, `main`, `push`).
- Intelligence and cycle:
  - `libs/intelligence/aeropulse_intelligence/{corroboration.py,plume/region.py}`;
  - `apps/cycle/aeropulse_cycle/citizen.py`.
- Storage, ML and regions:
  - `libs/storage/aeropulse_storage/citizen.py`;
  - `libs/ml/aeropulse_ml/datasets/history.py`;
  - `libs/regions/aeropulse_regions/citizen.py`.
- Tests:
  - `tests/unit/{test_vision,test_corroboration,test_citizen_analyzer}.py`;
  - `tests/unit/replayed_registry.py`.

**Files changed:**
- Intelligence and cycle:
  - `libs/intelligence/aeropulse_intelligence/graph.py`;
  - `libs/intelligence/pyproject.toml` (pandas and pyarrow, for `plume/region.py`);
  - `apps/cycle/aeropulse_cycle/{cycle,plumes}.py`.
- Contracts:
  - `libs/contracts/aeropulse_contracts/alert.py`: `report_id`, and exactly one subject.
  - `snapshot.py`: `CitizenWatchSummary.matched_fire_id`, `observed_at`.
  - `gate_report.py`: `EvalFamily` adds `citizen_ai_observation`.
- Storage:
  - `libs/storage/aeropulse_storage/{analytics,factory,__init__}.py`:
    `citizen.reports.window` and `Storage.citizen`.
- Regions and config:
  - `libs/regions/aeropulse_regions/{__init__,cli}.py` (validate prints the citizen
    settings);
  - `config/citizen.yaml` (upwind cone, seed window, per-cycle cap).
- Workspace:
  - root `pyproject.toml` and `uv.lock` (two new workspace members).
- Tests:
  - `tests/unit/{test_cycle,test_graph}.py`.

**Files removed:** none.

**Reused:**
- The Phase 2 citizen contracts: `VisualObservation`, `GeoTrust`, `Corroboration`,
  `CitizenAnalysis`, `CitizenReportDocument`.
- The Phase 9 plume engine, with its region setup lifted out of the cycle into
  `RegionTransport` so the analyzer and the cycle share it.
- From Phase 10, `build_graph` for the analyzer's own subgraph.
- From Phase 8:
  - generation preconditions on the object store;
  - the analytics templates;
  - `batch_id`.
- The legacy keyword classifier (`aeropulse_intelligence.cv`), kept as an evaluation
  baseline only.

**Replaced:** the cycle's private plume-region helpers (now `RegionTransport`). The
cycle's raw-history read is now the shared `read_raw_window`. The legacy API citizen
router is untouched until Phase 12.

**Architecture decisions**

- **Layering.**
  - Vision handles pixels and the observer only.
  - Corroboration, origins and summaries live in intelligence, so the cycle and the
    analyzer share them without one app importing another.
  - Vision computes distances with `h3.great_circle_distance` rather than importing
    intelligence.
- **The model sees only the sanitized copy and the citizen's observation type,
  limited to known words.** The notes never reach a prompt.
- **A report acts only through `seed_plume`.** It cannot create or change an event,
  prediction or label. The test checks this: after a corroborated report, the live
  snapshot is unchanged.
- **Operator accept reuses corroboration.** Accepting a partial or corroborated report
  seeds a plume. Accepting an untrusted one never does.
- **The alert names its subject.** `Alert` carries exactly one of `event_id` or
  `report_id`, so a citizen watch can never be mistaken for an event alert.
- **The public row is privacy-safe.** `citizen.reports` holds rounded coordinates and
  no reporter hash. Exact points stay in the private report document.
- **The cycle re-seeds from the analytics log, then reads the private document**
  for the exact origin, capped at `max_plumes_per_cycle`. Overflow is stated in
  `field_status`.

**Credentials (codeguard):** the Gemini key is read only from the `SecretStr` setting
`AEROPULSE_GEMINI_API_KEY`. On Google Cloud it uses Application Default Credentials.
No key appears in code, config or logs. The one test that builds a keyed observer
passes an obvious placeholder string, which is never sent anywhere. No certificates or
new cryptography were added; image hashes use SHA-256.

**Tests:** 775 → 830 passing (55 new).
- Vision:
  - EXIF is read, then absent from the stored copy;
  - the committed Delhi PNG has no facts;
  - bad uploads, size and pixel limits are rejected;
  - capture time is taken in the pack's timezone;
  - geo-trust levels cover out of region, capture after upload, duplicates and age;
  - schema violations are rejected;
  - "PM2.5 is 180 µg/m³" and other figures are rejected;
  - observation types are limited;
  - with a fake client, the Gemini adapter uses structured output and no tools, and
    a failure or bad output leaves no observation;
  - evaluation metrics never invent a precision, and licences are required.
- Corroboration:
  - haze with no signals is uncorroborated and stored for operators only;
  - unknown signals are neutral;
  - smoke with a fire on the bearing seeds at the hotspot;
  - with no bearing, the plume starts at the reporter with spread;
  - a fire behind the camera or outside the window does not count;
  - the full decision table holds;
  - an untrusted report never seeds;
  - stored analyses rebuild the origin and the public summary.
- Analyzer, end to end on a real fixture cycle with a stub observer:
  - a Punjab EXIF JPEG is trusted, corroborated and seeds a plume at the fixture
    hotspot, writes privacy-safe rows and citizen graph edges, leaves the snapshot
    unchanged, and is idempotent;
  - the next cycle carries the watch and its plume;
  - the Delhi PNG uses upload time and lands in the operator queue (partial: only
    PM2.5 is elevated);
  - a Singapore JPEG with no live snapshot is queued;
  - a NSW out-of-region claim is untrusted, and acceptance does not change that;
  - Gemini unavailable queues the report, then the operator's class seeds it;
  - reject;
  - a bad upload or missing media is stored for operators only;
  - a duplicate photo loses trust;
  - a citizen-watch alert names the report and the places reached within the window;
  - alerts have exactly one subject;
  - concurrent document updates retry and keep both changes;
  - the push endpoint handles analysed, ignored, unknown and 500;
  - the observer is chosen from settings;
  - eval compares against the keyword classifier and "always clear";
  - citizen settings are validated.
- Graph: a corroborated report joins the fire and the plume it agrees with, inside the
  fire's incident.

Ruff, format and pyright are clean. `aeropulse-ml parity`, `aeropulse-region validate`
and `aeropulse-ml serving --strict` exit 0.

**Failures found and fixed:**
- Pyright, three cases:
  - the observer Protocol's attributes were invariant, and are now read-only
    properties;
  - `weights_for` had a narrow key type;
  - the update-retry loop raised `PreconditionFailedError` without its arguments; it
    now re-raises the last one.
- EXIF time was first treated as UTC; it is now resolved in the pack's timezone.
- Two test expectations were wrong, and the code was right:
  - a duplicate with no EXIF scores 0.51, which is "usable", not untrusted;
  - `ops.alerts` also holds the cycle's own event alerts.

**Known limitations**

- Gemini is not called live in this build's tests (fake client and stub observer). The
  evaluation set is not built, so there are no observer metrics yet. The ML Evaluation
  page must say so.
- The aerosol-index signal is always neutral. The Earth Engine S5P reading is not yet
  passed to the analyzer's environment.
- Citizen-watch alerts need gazetteer arrivals, and no region has a gazetteer yet
  (Phase 9 limitation). The test exercises the alert with explicit arrivals.
- The incident link uses the latest cycle's incidents. A report's own graph rows are
  written immediately, and it joins a cycle incident on the next run.
- Report creation, signed upload URLs, rate limits, the salted reporter hash and the
  moderation endpoint are Phase 12 API work. The legacy `/citizen` router still runs.
- No retention policy is set yet for `incoming/` originals. The bearing is re-read from
  the original on moderation.
- The Cloud Storage notification, Pub/Sub push subscription and dead-letter topic are
  Terraform work (Phase 14).

**Next:** Phase 12 — the API:
- `regions`, `incidents`, `plume`, `ml-eval` and citizen v2 routers. The citizen v2
  routers cover create with a signed URL, rate limits, the salted reporter hash, and
  moderation through `CitizenAnalyzer.moderate`.
- Snapshot-backed services.
- Removing the layering violations.
- Copilot v2 tools, prompt and grounding.

## Phase 12 — The API over snapshots, and Ask AeroPulse v2 (LLD APAC 11, 12)

**Completed**

- **One platform object per process** (`aeropulse_api.platform.ApiPlatform`): it holds
  settings, the region catalog, `Storage`, the citizen settings and a clock. Routes take
  it through `get_platform`, so tests swap in a platform over a temp directory.
  `region_id_param` validates `?region_id=` against the catalog (unknown → 404).
  `page()` gives every list `items`, `total`, `limit`, `offset`.
- **New routers:**
  - `regions`: `GET /regions` and `GET /regions/{id}`. Each gives the pack, AQI
    standard (with status and averaging), hazards, sources, the latest snapshot's cycle,
    served models, and a `field_status` when there is no snapshot.
  - `incidents`: list, detail (nodes, edges, root kind) and `/{id}/plume`.
  - `plume`: `GET /plume/{id}` and `GET /map/plume` (GeoJSON footprint, by default the
    latest horizon that has P90 cells). `POST /plume/what-if` is operator-only, runs
    inside the region, is cached and is never stored. Every plume is labelled
    `simulated` and experimental.
  - `ml/evaluation`: gate reports from `eval.reports.region`. It shows only stored
    reports, never a computed or default figure.
  - `models`: `GET /models` lists the families served per region from the snapshot,
    matching `model_serving.yaml`. `GET /models/registry` keeps the old baselines and
    challengers list.
- **Snapshot-backed map and events** (`snapshot_readers`):
  - `SnapshotMapReader` and `SnapshotEventReader` read only the snapshot. Each body
    carries `data_source` (cycle id and time).
  - On a region with no snapshot, `NotConfiguredMapReader` and
    `NotConfiguredEventReader` return zero records with `not_configured`.
  - `/map/hazard`, `/map/industry` and `/risk/areas` follow the same rule. The in-north
    legacy fixture readers serve only in replay mode, and are labelled `fixtures`.
- **Citizen v2** (`routers/citizen.py`, `citizen_client.py`):
  - Create returns an upload instruction. On GCP that is a signed `PUT` URL with a
    TTL; locally it is a multipart `POST`.
  - Upload sniffs the type by magic bytes, stores the original under `incoming/`, and
    pushes to the citizen analyzer if `AEROPULSE_CITIZEN_ANALYZER_URL` is set.
    Otherwise the report stays `queued`, with a `field_status` reason.
  - Rate limits come from `config/citizen.yaml`, per reporter and per IP.
  - The reporter is stored only as an HMAC-SHA256 of the token subject, salted by
    `AEROPULSE_CITIZEN_REPORTER_SALT`. Outside dev environments a missing salt is a
    503, never an unsalted hash.
  - The public list and detail views have rounded coordinates and no notes. Operators
    see the exact point and the photo.
  - Moderation is proxied to `CitizenAnalyzer.moderate`. With no analyzer it returns
    503.
  - The keyword `cv_class` from notes is gone from the API.
- **Layering:**
  - The API no longer imports `aeropulse_ml.cli` for drift. `DRIFT_SIGNALS`,
    `DriftReader` and `TimescaleDriftReader` moved to `aeropulse_ml.drift_store`; the
    API module re-exports them.
  - The API imports neither `aeropulse_cycle` nor `aeropulse_citizen_analyzer`; it
    talks to the analyzer over HTTP.
- **Ask AeroPulse v2** (`libs/copilot`):
  - `context.py`: `ToolContext` gains `regions` (a `RegionData` protocol) and
    `region_id`. The API implements `RegionData` as `PlatformRegionData`: a snapshot
    cache per request, plumes, places, the PM2.5 series from `raw.air_quality.window`,
    and citizen rows.
  - `region_tools.py` adds 16 tools:
    - region context, current AQI, PM2.5 trend and forecast, weather and the
      satellite signal;
    - plume, population exposure, source likelihood and citizen reports;
    - incidents (list, graph and `explain_incident`) and `query_trends`.
  - `locate()` resolves a place to a region (gazetteer, then the in-north legacy
    places, then region names), or returns `unknown_location` listing the covered
    regions.
  - For a place, a ground station within range outranks a closer CAMS cell, in both
    the current value and the trend.
  - Bands come only from the cycle (`cell.aqi_band`). When an averaging window is not
    met (CPCB needs a 24 h mean of at least 16 hours), the tool returns no band, with
    the cycle's reason. The tools never band an hourly value.
  - The legacy tools (`get_air_quality`, `get_wind`, `get_active_fires`,
    `get_hazard_outlook`, `list_active_events`, `explain_event`) take `region_id`.
    They answer from the snapshot when one exists, and from the legacy readers only
    for in-north with none. Other regions get `not_configured`.
  - Prompt `system_v2.md` is now the default. It sets provenance wording, says a
    backward plume is not proof, forbids working out a band, and includes a Singapore
    worked example. `region_facts(ctx)` adds region and standard names to the prompt,
    never a figure.
  - Grounding also rejects a value from a `simulated`, `heuristic` or `ai_observation`
    result written as "measured", "recorded" or "detected by station"
    (`mislabelled_values`). A value that also appears in a measured result is
    allowed.
- **Copilot routes** take `region_id` and `incident_id`. A question about another
  region sets the legacy readers to none, so in-north data cannot answer it.

**Files added:**
- API:
  - `apps/api/aeropulse_api/{platform,snapshot_readers,citizen_client,copilot_regions}.py`;
  - `apps/api/aeropulse_api/routers/{regions,incidents,plume,ml_eval}.py`.
- ML: `libs/ml/aeropulse_ml/drift_store.py`.
- Copilot:
  - `libs/copilot/aeropulse_copilot/{context,region_tools}.py`;
  - `prompts/system_v2.md`.
- Tests:
  - `tests/unit/{test_api_regions,test_api_citizen,test_copilot_regions}.py`;
  - `tests/unit/{region_cycle,conftest}.py`: one real in-north cycle shared by those
    three test files.

**Files changed:**
- API:
  - `apps/api/aeropulse_api/{app,copilot_service,drift_store,event_store,map_store}.py`;
  - `routers/{citizen,copilot,events,map,models,risk}.py`;
  - `apps/api/pyproject.toml`.
- Copilot:
  - `libs/copilot/aeropulse_copilot/{tools,grounding,service,gemini,__init__}.py`;
  - `libs/copilot/pyproject.toml`.
- ML: `libs/ml/aeropulse_ml/cli.py`.
- Settings: `libs/common/aeropulse_common/settings.py` (analyzer URL, reporter salt,
  prompt `v2`).
- Tests:
  - `tests/conftest.py`: autouse API state isolation (data dir, settings, platform,
    what-if cache and rate limits);
  - `tests/unit/test_api.py`: the models test uses `/models/registry`; the citizen
    tests use v2 shapes; the OpenAPI test lists the new routes.

**Files removed:** none. The legacy readers remain because they still serve in-north
in replay mode.

**Reused:**
- The Phase 8 `Storage` and analytics templates.
- The Phase 9 plume engine through the region's transport, for what-if.
- The Phase 10 incidents.
- The Phase 11 analyzer (`create_app`, `moderate`).
- `aeropulse_vision.sanitize.sniff` for the upload check.
- The legacy tool readers, for in-north with no snapshot.

**Replaced:**
- The API citizen router (v1 keyword classification).
- `/models`, which now lists what is served; the old body is at `/models/registry`.
- The copilot's default prompt (v1 → v2).

**Architecture decisions**

- **A region with no snapshot answers `not_configured` everywhere.** This covers map,
  events, hazard, industry, risk, incidents, plume, models and copilot. The in-north
  fixtures never appear under another region's name, and never under Live outside
  replay.
- **`query_trends` uses the storage allow-list**, not a `queries/` directory of SQL.
  The copilot picks a template id (`pm25_hourly`) and parameters. Windows are capped at
  7 days and rows at 500, and the analytics adapter's `max_bytes` still applies.
- **The copilot does no banding of its own.** The averaging rule lives in the cycle,
  so the tools and the prompt can only repeat the cycle's band or its reason.
- **What-if is never stored.** It is operator-only and cached in memory per input. A
  test checks that `storage.plumes.get` stays empty.
- **The citizen API stays thin.** Every look at the photo happens in the analyzer,
  and the API cannot change an event, prediction or label.

**Credentials (codeguard):**
- No credentials were added to code, config or tests.
- The reporter salt and the Gemini key are `SecretStr` settings read from the
  environment. Outside dev, a missing salt fails closed (503).
- The dev-only salt is random per process (`secrets.token_bytes`), not a constant.
- Signed upload URLs come from the storage adapter's service identity (ADC) with a
  TTL from config.
- No certificates were added. Hashing uses HMAC-SHA256 and SHA-256 only.

**Tests:** 830 → 858 passing.
- Routes over a real cycle:
  - regions list and detail;
  - incidents and their plumes;
  - plume map and document labels;
  - what-if: not stored, cached, 403 for a viewer, 422 outside the region;
  - map and events `data_source`, and Singapore `not_configured` (including risk);
  - `/models` matches `model_serving.yaml`;
  - ML evaluation shows stored reports only;
  - the registry makes no writes;
  - CORS.
- Citizen v2:
  - the full flow through an in-process analyzer, with no private fields in the
    public view;
  - the moderation proxy;
  - no analyzer: `queued` with a reason, and moderation 503;
  - validation, 403 and 400 cases;
  - a missing production salt gives 503.
- Copilot:
  - the tool list matches the declarations;
  - the Delhi answer is a ground station with no band and the cycle's reason;
  - the region median has no band;
  - Singapore and Sydney are `not_configured`, and unknown places are refused;
  - the trend is station-first;
  - `query_trends` refuses an unknown template or a 30-day window;
  - weather states missing humidity, and the satellite signal is unavailable;
  - `explain_incident` labels plumes as simulated and likelihood as an uncalibrated
    ranking, and its back trajectory says "not proof";
  - `region_facts` carries no figures;
  - a simulated 0.42 or a heuristic 0.71 written as "measured" fails grounding;
    simulated wording passes.

Ruff, format and pyright are clean. `aeropulse-ml parity`, `aeropulse-region validate`
and `aeropulse-ml serving --strict` exit 0.

**Failures found and fixed:**
- `uv sync` failed until `prompts/system_v2.md` existed (the package includes it).
- The first tools banded hourly values that the cycle had deliberately left unbanded.
  The tools now use only the cycle's band.
- `/map/plume` was empty because particles leave the domain by 24 h. The default is now
  the last horizon with P90 cells.
- Delhi resolved to a CAMS cell (37.3 µg/m³) 3.5 km closer than a CPCB station
  (142.3). The station now wins within the place radius.
- A test clock put the analyzer 2 minutes after the API's list window. The test now
  pushes 30 seconds after upload.
- Three legacy `test_api.py` tests asserted v1 shapes (`/models` body, keyword
  `cv_class`), and were updated to v2.

**Known limitations**

- `get_satellite_signal` is always `unavailable`: no Earth Engine reading reaches the
  snapshot yet.
- Plume arrivals need a gazetteer, and none is built, so `get_plume` returns no
  arrivals. `get_population_exposure` passes through each plume's exposure and its
  `field_status` (Phase 9: no licensed population raster).
- In-north hazard rules still run in the API's legacy hazard path when there is no
  snapshot. The snapshot path uses the cycle's `hazard`.
- Two layering items remain:
  - `connectors/*` runner code imports `aeropulse_worker.db`;
  - the API `sources` router imports `aeropulse_connector_app.registry`.

  Phase 14's architecture test lists both as known exceptions, to be removed when the
  worker is retired.
- Rate limits are per process and in memory. Several Cloud Run instances each keep
  their own window.
- Gemini is not called live in tests; a fake client is used.

**Next:** Phase 13 — the frontend:
- `RegionContext` with `?region=`, and AQI and region config from the API;
- removing hardcoded geography; an H3 layer;
- provenance badges, the incident panel and the ML evaluation page;
- Demo data generated per region;
- adapting to `/models`, `/models/registry`, citizen v2 and `data_source`.

## Phase 13 — The frontend over regions (LLD APAC 13)

**Completed**

- **One region in the URL** (`context/RegionContext.tsx`). The region comes from
  `?region=`, then the session, then `VITE_DEFAULT_REGION`, then the catalog default.
  The region detail (pack, AQI standard, hazards, sources, served models, snapshot
  `field_status`) comes from `GET /regions/{id}`, never from frontend constants.
  Changing region drops `?incident=`. `useRegionLink` keeps `?region=` on every
  link.
- **One HTTP client, one Demo/Live branch.**
  - `api/client.ts` is the only `fetch`. `ApiError.reason` now carries the API's
    `detail`.
  - `api/transport.ts` defines a `Transport` with two implementations: HTTP (Live)
    and the recording (Demo).
  - `services/resolve.ts` is the only place that chooses between them. It records a
    failed Live call for the banner and never substitutes Demo data.
  - `api/regions.ts` has one function per route, and `api/regionTypes.ts` holds the
    wire types.
- **Demo is a recording of the real API**
  (`scripts/generate_demo_recording.py`, `frontend/web/src/data/regions/`).
  - The generator runs the in-north cycle on the replay fixtures, starts the API
    in-process, and records every route the UI calls for each region. That includes
    the copilot answers for the suggested questions, with and without the incident
    selected.
  - Singapore and NSW have no replay fixtures, so their recordings hold what the API
    says without a snapshot: `not_configured`, with reasons.
  - Output is byte-stable. Ids are substituted where the API mints them, and the
    clock is fixed. `--check` fails when the recording is stale.
  - A request that is not in the recording is a 404 that reads "not in the Demo
    recording — switch to Live". Uploads in Demo are a 405.
- **Pages:**
  - Command centre: KPI counts from the API; the map; the layer panel; the selection
    card; and an incident list, or the incident panel when `?incident=` is set.
  - Events (list and detail).
  - Forecast: P50 per cell. P10/P90 show "—" because quantiles are not built. Hazard
    is labelled "rank" until calibrated.
  - Evidence: the incident graph, with provenance on every node and edge.
  - Ask AeroPulse.
  - Citizen reports: list, detail, upload.
  - Sources: pack and connector cards. `secret_ref` is shown as a name only.
  - Models: served versions and stored evaluation runs.
- **Map** (`components/map/RegionMap.tsx`):
  - deck.gl owns the camera, and MapLibre is a passive basemap with an offline
    fallback style.
  - Layers:
    - the region bbox;
    - H3 r8 PM2.5 cells (grey when the API has no value);
    - plume P50/P90 cells per horizon, brighter for the selected incident;
    - wind arrows, FIRMS clusters and citizen reports.
  - The cell colour is a neutral µg/m³ display ramp, labelled "not an AQI band".
    AQI bands appear only per cell, from the API, and only when the standard is
    confirmed. Otherwise the panel shows the pack's "unconfirmed" reason.
  - Selecting an incident centres the map on its cells.
- **Shared components:**
  - `ProvenanceBadge`: one badge per class, with its meaning as a tooltip.
  - `Missing` / `Value`: "—" with a reason.
  - `Banners`: Live failure, not configured, query error.
  - `IncidentGraph`, `LikelihoodRanking` ("a ranking, not probabilities"),
    `IncidentPanel`.
- **Time:** every timestamp is shown in the region's zone (`useRegionClock`). In
  Demo the clock is frozen at the recording time and labelled "recorded …".
- **Ask AeroPulse page** (`pages/Copilot.tsx`):
  - It is scoped to the region and, if one is selected, the incident. Changing
    either starts a new conversation.
  - Suggested questions come from the recording in Demo. Live uses the same text, so
    both modes ask the same questions.
  - Each answer shows: Gemini or "Evidence lookup — no language model"; the tools
    called; the grounding verdict with the number of figures checked; the degraded
    reason; citations; and limitations.
- **Copilot fixes found while building the page:**
  - The no-LLM path now uses the region tools by intent (`deterministic.py`), so
    Demo answers are real tool answers rather than legacy event retrieval.
  - A topic in the question (fires, events, air) beats the "(Selected incident: …)"
    marker the API appends.
  - Region-wide questions matched the region name before the legacy place lookup
    (previously they resolved to Delhi).
  - `numbers_checked` was always 0 in responses: the router never passed it and the
    no-LLM path never validated. Both paths now run `validate_answer` and report the
    real count. A region answer that fails is logged as an error and shown as
    "figures not verified".

**Files added (frontend/web/src):**
- `api/{transport,regions,regionTypes}.ts`;
- `context/RegionContext.tsx`;
- `hooks/{useRegionQuery,useRegionClock,useRegionLink,useRegionEvents}.ts`;
- `components/common/{ProvenanceBadge,Missing,Banners}.tsx`;
- `components/map/{RegionMap,MapLayerPanel,SelectionCard}.tsx`;
- `components/incident/{IncidentGraph,LikelihoodRanking,IncidentPanel}.tsx`;
- `components/citizen/CitizenUploadForm.tsx`;
- `pages/{CommandCentre,Events,Models}.tsx`;
- `utils/{concentration,incident}.ts`;
- `data/regions/{index.ts,catalog.json,<region>/recording.json}`.

**Other files added:**
- `scripts/generate_demo_recording.py`;
- `libs/copilot/aeropulse_copilot/deterministic.py`;
- `tests/golden/test_demo_recording.py`;
- `tests/unit/test_copilot_deterministic.py`.

**Files changed:**
- Frontend:
  - `api/client.ts`, `app/router.tsx`, `config/env.ts`;
  - `context/{AppContext,DataModeContext}.tsx`;
  - `services/{resolve,dataMode}.ts`, `utils/format.ts`;
  - `components/layout/{TopBar,Sidebar,CommandPalette,NotificationDrawer,FooterStatus,AppShell,DataModeToggle}.tsx`;
  - `components/map/basemapStyle.ts`, `components/common/Badge.tsx`;
  - `pages/{Copilot,Forecast,Evidence,CitizenReports,Sources}.tsx`;
  - `package.json` (+`@deck.gl/geo-layers`, +`h3-js`) and `package-lock.json`.
- Backend:
  - `libs/copilot/aeropulse_copilot/{service,region_tools}.py`;
  - `apps/api/aeropulse_api/{copilot_service,routers/copilot}.py`;
  - `libs/connector_sdk/aeropulse_connector_sdk/legacy.py` (stamps `context.now`).
- `.gitignore`: the `data/` and `models/` rules hid two source trees. One was the new
  Demo recording; the other was the Phase 6 `libs/ml/aeropulse_ml/models/` plugin
  package, which a fresh clone would therefore have lacked. Both are now negated.

**Files removed:** 86 files of the corridor UI. None was imported once the new pages
were in, which was checked by import reachability from `main.tsx`.
- Pages: `Overview`, `LiveMap`, `Risk`, `EventDetail`.
- Map: `AeroMap` and its 20 helpers.
- `components/{events,evidence,charts}/*`.
- `DemoOverlay`, `JudgeTourDriver`, `SceneToggle`, `ViewLevelToggle`, and
  `ViewLevelContext`.
- The `data/mock*.ts` files and `geography.json`, with
  `scripts/build-geography.mjs`.
- `demo/*` (scripted tours).
- Ten `services/*Service.ts` files.
- `api/{adapters,live,contracts,index}.ts` and `types/index.ts`.
- `utils/{aqi,geo,heroEvent,seededRandom}.ts`.
- `hooks/{useHeroEventId,useAnimationClock,useReducedMotion}.ts`.

**Reused:**
- `DataModeContext`, with its health probe and Live blockers.
- `client.ts`'s token and URL handling.
- The layout shell, `Card`, `StatusBadge` and the Tailwind theme.

**Replaced:**
- The scripted Punjab → Delhi Demo, which was hand-written mock data, by a recording
  of the real API.
- The frontend AQI table (`utils/aqi.ts`) by the pack's standard served by the API.
- The hardcoded corridor geography by the pack's bbox and map view.

**Architecture decisions**

- **Demo = recorded API responses, keyed exactly as Live requests them.** Demo and
  Live therefore run the same page code through the same `Transport` interface. No
  frontend number is invented, and "not configured" looks the same in both modes.
- **The recording is source, not a build artefact.** It is committed, stable, and
  checked with `--check` (a golden test runs it), so Demo works with no API and no
  Python.
- **The colour ramp is not a band.** Cells are coloured on a fixed µg/m³ ramp that
  the legend calls a display ramp. Bands come only from the API and only for
  confirmed standards. This means the UI never applies CPCB to Singapore or NSW.
- **The map focuses on the incident.** At region zoom a 1 km cell is below a pixel,
  so selecting an incident centres on the mean of its cells at zoom 10.5.

**Credentials (codeguard):**
- No secrets were added to the frontend, the generator or the recording.
- The Live token is read from `VITE_API_TOKEN` at build time, as before.
- The generator first drops `.env` and every exported `AEROPULSE_*` variable, so it
  never reads a real key, and Gemini is replaced by a canned observer labelled
  `ai_observation`. It signs its in-process requests with a token minted at run time
  from the settings' declared dev default. No token is written into the recording
  (no `eyJ…` string appears in it); only the persona (subject and roles) is recorded.
- `Sources` shows a connector's `secret_ref` as a reference name and never resolves
  it.
- No certificates or crypto were added.

**Tests:** 858 → 876 passing (unit, contract, golden).
- Golden, the Demo recording:
  - `--check` passes;
  - the catalog matches the recorded regions;
  - Singapore and NSW are `not_configured` and never mention in-north;
  - in-north has the incident and copilot tool calls.
- Deterministic copilot:
  - each intent calls its tool and passes grounding;
  - a topic beats the selected-incident marker;
  - a band shows as "—" with the standard's reason;
  - Singapore is `not_configured`;
  - with no region it falls back to legacy retrieval;
  - the service reports `numbers_checked > 0`.
- Frontend:
  - `npx tsc -b` (forced) is clean, and `npx vite build` succeeds.
  - `npx oxlint src` has 0 errors. The warnings are `only-export-components` on
    context/hook modules, plus the existing health-probe `set-state-in-effect` in
    `DataModeContext`.
  - A browser check of Demo with the API unreachable rendered all eight pages with no
    errors except the expected `/health` probe. That covered the in-north incident
    view, the map focus, recorded copilot answers with and without an incident, and
    Singapore's not-configured states.

Ruff, format and pyright are clean. `aeropulse-ml parity`, `aeropulse-region validate`,
`aeropulse-ml serving --strict` and `generate_demo_recording.py --check` exit 0.

**Failures found and fixed:**
- Every previous Demo copilot answer came from the legacy event retrieval. Answers
  now come from the region tools.
- The "(Selected incident: …)" marker made every question explain the incident.
- `numbers_checked` was always 0 (see above).
- The auto-scroll effect returned the Promise that newer Chromium's `scrollIntoView`
  gives back, and React treated it as a cleanup function, crashing the page on
  unmount.
- `aria-live` passed to `CardBody` was silently dropped, because TypeScript does not
  check hyphenated JSX attributes on components.
- Not-configured KPIs showed "0". They now show "—" with the reason.
- The `.gitignore` gaps described above.

**Known limitations**

- Demo can only answer recorded questions. Free text in Demo says so and points to
  Live.
- The default basemap is CARTO tiles. Offline it falls back to a plain graticule
  style.
- The bundle is 2.7 MB (deck.gl + MapLibre + h3) with no code splitting yet.
- Places reached and population exposure show "—" with the Phase 9 reasons (no
  gazetteer, no licensed population raster).
- Singapore and NSW Demo recordings have no cycle until replay fixtures exist for
  them.

**Next:** Phase 14 — hardening:
- architecture tests: app isolation, Gemini imports only in the copilot and vision,
  and no source file hidden by `.gitignore`;
- a synthetic fourth region end to end;
- `Dockerfile.ml`, compose services and minimal GCP Terraform;
- ML/ops docs and a README append.

---

## Phase 14 — Hardening: architecture tests, a fourth region, containers, Google Cloud

**Completed**

- **Architecture tests** (`tests/unit/test_architecture.py`, 9 tests). Each was checked
  by planting a violation and seeing it fail. They cover:
  - apps do not import each other, except an exact list that fails when it goes stale;
  - only the copilot and vision Gemini adapters import a language model;
  - the event path (contracts, cycle, geospatial, intelligence, ml, regions, storage,
    connectors) imports no copilot, vision or LLM SDK, and a subprocess confirms that
    importing the cycle loads none;
  - no broad exception is silently swallowed;
  - the frontend has one HTTP client and one Demo/Live branch;
  - `config/` holds secret references only;
  - no source file is hidden by `.gitignore`.
- **A fourth region by configuration only** (`tests/unit/test_fourth_region.py`).
  `zz-synthetic` is onboarded with:
  - `aeropulse-region init`;
  - an unconfirmed AQI standard YAML;
  - a `fixture:` path per source, using the in-north captures moved 60° south into
    the open Indian Ocean.

  The real cycle and the real API then serve it:
  - it validates beside the three real packs;
  - its cells and events lie inside its own bbox;
  - every gated model is a degraded rule with a reason;
  - no AQI band is invented;
  - `/regions` lists it and its grid serves;
  - the copilot answers with `get_current_aqi`, grounded with numbers checked;
  - no output mentions in-north;
  - au-nsw stays `not_configured`.
- **Containers.**
  - `infrastructure/docker/Dockerfile.ml` (non-root, frozen sync, entry point
    `aeropulse-ml train`).
  - `UV_EXTRAS` build argument on both Python images.
  - `var/aeropulse` is pre-created, so a named volume is writable by uid 10001.
  - `frontend/web/Dockerfile.prod` plus `nginx.conf`: a static build for Cloud Run.
    Vite's dev server rejects unknown hosts.
- **Compose.**
  - `cycle`: one replay cycle per region at 2026-09-08 06:00 UTC, then exit.
  - `citizen-analyzer`: backend network only, no host port.
  - A shared `aeropulse-data` volume.
  - The API gets `AEROPULSE_DATA_DIR` and `AEROPULSE_CITIZEN_ANALYZER_URL`.
- **Minimal GCP Terraform** (`infrastructure/gcp/`):
  - four private buckets with uniform access, enforced public-access prevention and
    lifecycle rules;
  - six BigQuery datasets;
  - Secret Manager secret containers only;
  - five service accounts (LLD 13.1), with grants on the bucket, dataset, topic or
    secret wherever possible;
  - `aero.citizen.reports`, `aero.alerts` and `aero.citizen.reports.dlq`;
  - the GCS `incoming/` notification;
  - an OIDC push subscription as `sa-push`, with 5 delivery attempts before the
    dead-letter topic;
  - Cloud Run `api`, `web` and `citizen-analyzer` with min instances 0;
  - one Cloud Run Job per region with parallelism 1, and one Scheduler entry each
    with a pause switch;
  - an optional training job that mounts the models bucket.
- **Docs.**
  - New: `docs/ml/training-and-promotion.md` and `docs/ops/runbook.md`.
  - `docs/DEPLOYMENT.md` Phase 3 replaced: it described mock services and
    `VITE_USE_MOCKS`, which no longer exist.
  - README: one section appended at the end; nothing above it changed.

**Files changed / added / removed**

- Added:
  - `tests/unit/test_architecture.py`, `test_fourth_region.py`, `test_copilot_vertex.py`,
    `test_storage_gcs_signing.py`;
  - `infrastructure/docker/Dockerfile.ml`;
  - `infrastructure/gcp/*.tf` and `.terraform.lock.hcl`;
  - `frontend/web/Dockerfile.prod` and `frontend/web/nginx.conf`;
  - `docs/ml/training-and-promotion.md` and `docs/ops/runbook.md`.
- Changed:
  - `infrastructure/docker/Dockerfile` and `compose.yaml`;
  - `.github/workflows/ci.yml`, `.gitignore`, `frontend/web/.dockerignore`;
  - `pyproject.toml` (a `gcp` extra) and `uv.lock`;
  - `apps/api/aeropulse_api/citizen_client.py` and `copilot_service.py`;
  - `libs/copilot/aeropulse_copilot/gemini.py`;
  - `libs/storage/aeropulse_storage/objects.py`;
  - `libs/ml/aeropulse_ml/models/anomaly.py`; `base.py` and `forecast.py` were
    formatted only;
  - `tests/unit/test_api_citizen.py` and `test_ml_plugins.py`;
  - `docs/DEPLOYMENT.md` and `README.md` (append only).
- Removed: nothing.

**Existing code reused / replaced**

- The fourth-region test reuses `region_cycle` (`T0`, `client_for`, `auth`),
  `replayed_registry` and the real `aeropulse-region` CLI.
- The Compose services reuse the main image and the existing CLIs.
- The copilot's Vertex path mirrors the vision observer's.

**Architecture decisions**

- **Images opt in to Google Cloud clients.** A root `gcp` extra pulls in:
  - `aeropulse-storage[gcp]`;
  - `aeropulse-connector-sdk[gcp]`;
  - `aeropulse-connector-earthengine[live]`;
  - `google-auth[requests]`.

  Before this, nothing requested those extras, so no image could run with
  `AEROPULSE_PLATFORM=gcp`. Local installs stay lean.
- **The API's identity rides beside the operator's.** The analyzer's Cloud Run service
  is IAM-protected, and `Authorization` already carries the operator's JWT. On GCP the
  API therefore adds a Google ID token in `X-Serverless-Authorization`, which Cloud Run
  checks first and passes through `Authorization` untouched. Missing credentials raise
  `AnalyzerUnavailableError` (503), not a 500.
- **Key-less signed URLs.** Cloud Run credentials carry a token but no private key, so
  `GcsObjectStore` passes the runtime identity's email and token to
  `generate_signed_url`. The client then signs through IAM `signBlob`. A key file still
  signs locally.
- **The copilot uses Vertex AI on GCP** (LLD 10), through the service account; an API
  key is ignored there. Locally only a key enables Gemini.
- **Only token-verifying services run as `production`.** That setting makes the JWT
  secret mandatory. The API and the analyzer receive it; the cycle job does not.
- **The analyzer's ingress is "all", with no public invoker.** Only `sa-push` and
  `sa-api` hold `run.invoker`. Internal-only ingress would also need VPC egress on the
  API, which is deferred.

**Credentials (codeguard).** The rule applies because this phase writes deployment
configuration, the place where credentials are most often hardcoded:

- **Terraform** holds no secret values. It creates Secret Manager containers, and
  values are added out of band (`gcloud secrets versions add`), so they never enter
  state. Cloud Run reads them as `secret_key_ref` env vars, scoped per service:
  - cycle: the OpenAQ and FIRMS keys;
  - API: the JWT secret and the reporter salt;
  - analyzer: the JWT secret.
- **No key files anywhere.** Identity comes from ADC: signed URLs via `signBlob`, the
  Vertex AI client, ID tokens, and Scheduler's OAuth token.
- **Compose** gained no literal secrets: the analyzer's
  `${AEROPULSE_JWT_SECRET:?}` and Gemini key follow the API's pattern. **Flagged,
  pre-existing:** the local-only dev credentials (MinIO `aeropulse`/`aeropulse_secret`,
  Postgres `aeropulse`/`aeropulse`). They bind to 127.0.0.1 and must never be reused
  outside a laptop.
- **CI** checks Compose interpolation with a random per-run
  `AEROPULSE_JWT_SECRET="$(openssl rand -hex 32)"`, not a literal. That job had been
  failing since the Phase 2 `:?` requirement.
- **Frontend.** `frontend/web/.dockerignore` now excludes `.env*` except
  `.env.example`. A git-ignored `frontend/web/.env.local` exists and would otherwise
  have been copied into image build contexts. `Dockerfile.prod` bakes no API token:
  a token in a public bundle is a published credential.
- **Tests** use obvious placeholders (`local-only-placeholder`, `id-for:…`), never
  real keys or `eyJ…` strings.
- **Certificates:** none added or loaded. TLS terminates at Google's front ends.
  `nginx.conf` serves plain HTTP inside the container, as Cloud Run expects.
- **Crypto:** none added. The Terraform binary used for validation was checked against
  HashiCorp's published SHA-256 sums.

**Tests added / executed:** 876 → 897 (unit, contract, golden: 21 new), plus 1 in
`tests/load`, so 898 in the CI command.

- New:
  - architecture, 9;
  - fourth region, 4;
  - copilot Vertex, 3;
  - GCS signing, 2;
  - analyzer identity and missing-identity, 2;
  - anomaly empty frame, 1.
- Ruff, format and pyright are clean.
- `aeropulse-region validate`, `aeropulse-ml parity`, `aeropulse-ml serving --strict`
  and `generate_demo_recording.py --check` exit 0.
- `npx tsc -b --force` is clean, and `npx oxlint` has 0 errors.
- `docker compose config` passes. Replaying the Compose cycle command locally gave:
  - in-north: 6 cells, 4 events, 8 plumes;
  - Singapore and NSW: every source `not_configured`, 0 cells.
- `aeropulse-ml train --family all --dataset fixture --regions in-north` (the
  training image's default) exits 0, and every family is honestly unpromoted.
- `terraform fmt -check` and `terraform validate` pass with google provider 6.50.0.

**Failures found and fixed**

- **Anomaly training crashed on an empty frame** (pandas length mismatch) instead of
  raising `TrainingError`. The image's default command hit it on the fixtures, which
  have no 24 h labels.
- **No image could run on GCP**, because the GCP client extras were never installed.
- **Signed upload URLs would have failed on Cloud Run** ("you need a private key").
- **The copilot had no Vertex path**, so on Cloud Run with no key it would have
  silently answered without Gemini.
- **The CI `compose` job** failed on the required JWT secret.
- **Hidden files.** `.gitignore`'s `models/` rule had hidden `aeropulse_ml/models/`
  from ruff (Phase 13 fixed that), and three of its files were unformatted.
- **Leak paths.** `frontend/web/.dockerignore` let `.env.local` into builds, and the
  nginx security headers would have been dropped by per-location `add_header`.

**Known limitations**

- The Terraform is validated, not applied, and the nginx config was not run (no Docker
  daemon here).
- Nothing publishes to `aero.alerts` yet; alerts are written to `ops.alerts`.
- The cloud web serves Demo, and Live is "not configured" until sign-in (OIDC) exists.
- The cycle job's environment label stays the default, because `production` would
  require a JWT secret it does not use. A follow-up should move the JWT strength
  check to the processes that verify tokens.
- No billing budget is in Terraform. Earth Engine needs project registration first.
- Shadow scoring for the four families is not run by the cycle yet.

**Next:** none. All 14 phases of the migration plan are complete.
