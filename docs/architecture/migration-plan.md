# Migration plan

Incremental migration from the current build ([current-state-audit.md](current-state-audit.md)) to the APAC target ([target-architecture.md](target-architecture.md)). No big-bang rewrite: each component follows

```text
old implementation -> new implementation -> golden/integration test -> compare -> switch caller -> remove old code
```

Old code is removed only when no callers remain, no test depends on it, and the replacement's behaviour is covered by a test.

Every phase starts with `git status` / `git diff`, never resets or cleans, and ends with:

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/unit tests/contract -q
uv run aeropulse-ml parity        # from Phase 5
```

## Phases

| # | Phase | Main outputs | Old code kept until |
| --- | --- | --- | --- |
| 1 | Audit | `docs/architecture/*` | — |
| 2 | Contracts and Region Packs | `ProvenanceClass`, `region_id`, `MeteoForecast`, `RegionSnapshot`, plume/graph/citizen/likelihood contracts; `libs/regions`; `config/regions`, `hazard_profiles`, `aqi_standards`, `model_serving.yaml`, `citizen.yaml`; JWT fail-closed; AGENTS.md amendments | Old contracts keep their fields (additions only) |
| 3 | Connector plugins | `ConnectorPlugin`, `ConnectorContext`, entry-point registry, `IngestPipeline`, legacy adapter; OpenAQ/FIRMS/Open-Meteo context-driven; Earth Engine plugin | Legacy registry until the connector app runs on discovery |
| 4 | Shared preprocessing | `preprocessing/` steps and pipelines | Worker QC path until the cycle replaces it |
| 5 | Feature pipeline | `ml-features-3.0.0`, `FeaturePipeline`, parity rewrite in CI | Old feature sets until trainers move |
| 6 | Model plugins | Four families, evaluation strategies, baselines, `DatasetSource`, `train` CLI with gate reports | `train.py` trainers until the CLI switches |
| 7 | Serving gates | `model_serving.yaml` loader, `ModelResolver`, post-processing | Registry `/models` view until Phase 12 |
| 8 | Cycle and storage | `libs/storage`, `apps/cycle`, rule fixes, snapshot writer, golden test | Worker until the API reads snapshots |
| 9 | Plume | `plume/` ensemble | `wind-advection-0.1` stays as fallback and baseline |
| 10 | Graph | `graph/` builder and incidents | Lineage graph for `/events/{id}/graph` |
| 11 | Citizen AI | `libs/vision`, corroboration, `apps/citizen_analyzer` | Keyword classifier as evaluation baseline |
| 12 | API | Region, incident, plume, ML-evaluation, citizen v2 routers; snapshot services; layering fixes; copilot v2 | Timescale readers behind the `legacy` Compose profile |
| 13 | Frontend | Region context, API-driven AQI, H3 layer, badges, incident panel, ML evaluation page, generated Demo data | Corridor mocks until generated Demo data replaces them |
| 14 | Hardening | Architecture tests, synthetic fourth region, Dockerfile.ml, Compose services, GCP Terraform, ML and ops docs | — |

## Golden comparison for `in-north`

Before the cycle replaces the worker as the producer of events, `tests/golden/test_in_north_events.py` runs the replay fixtures through both the old `process_snapshot` path and the cycle's scoring stage and compares event cells, severities, and types. Intentional differences (the Section 5.2 bug fixes) are listed in the test with the reason, not silently accepted.

## External dependencies that do not block code

- Live keys (OpenAQ, FIRMS) and network: without them a source reports *not configured* with zero records.
- Earth Engine project registration: until then the plugin replays fixtures and reports *not configured* in Live.
- Official NEA and NSW AQI tables: until pasted with a `source_url`, those standards are `unconfirmed` and show "—".
- Real training data: gate outcomes come only from real runs.
