# Training, gates and promotion

A model reaches users only through a reviewed edit to `config/model_serving.yaml`.
Training writes artifacts and gate reports; it never writes that file and never
promotes. Until an entry exists and survives the resolver's checks, the family's
deterministic rule answers with `degraded=true` and a `degraded_reason`.

Feature rules (one pipeline for training and serving, version bumps, parity) are in
[feature-pipeline.md](feature-pipeline.md).

## The four families

| Family | Model | Rule served when no model passes | Label |
|---|---|---|---|
| `pm25_forecast` | quantile forecast (P10/P50/P90) per horizon | `persistence-forecast-1.0` | station PM2.5 at `t + h` (measured only; CAMS is a feature, never a label) |
| `pm25_hazard_24h` | hazard classifier, ranked until calibrated | `persistence-hazard-1.0` | running mean over the region's averaging window crosses `region_threshold_ugm3` within 24 h |
| `anomaly` | hour-of-week quantile table per station; the served forecast's P90 when one exists | `absolute-threshold-1.0` | none trained on; gated against the hazard label |
| `source_likelihood` | heuristic evidence weights | the same heuristic | none: no gold label set, so it is never promoted as a model |

A region whose AQI standard is unconfirmed has no hazard threshold, so its hazard
label is never computed and its hazard rule says so.

## Running a training job

```bash
# Local, from the committed fixtures (gates are expected to refuse: too little history)
uv run aeropulse-ml train --family all --dataset fixture --regions in-north --out models/runs

# One family, pooled over regions, from BigQuery
uv run aeropulse-ml train --family pm25_forecast \
  --dataset bq://<project>/aeropulse --regions in-north,sg-singapore --out models/runs

# The same in a container
docker build -f infrastructure/docker/Dockerfile.ml -t aeropulse-ml .
docker run --rm -v "$PWD/models:/app/models" aeropulse-ml \
  --family pm25_forecast --dataset fixture --regions in-north
```

`--dataset` accepts `bq://project[/dataset]`, `parquet://path`, `fixture[://path]` and
`synthetic://`. Synthetic data trains for tests only: the resolver refuses any entry
whose gate report says it was trained on synthetic data.

On Google Cloud the `aeropulse-train` Cloud Run Job (created when `ml_image` is set in
`infrastructure/gcp`) runs the same image with the models bucket mounted at
`/app/models`, as `sa-train`.

Each run writes `models/runs/<family>-<UTC time>/` with the artifact and `gate.json`.
The CLI prints a summary per family: `servable`, `servable_reason`, and per region
`passed`, `calibrated`, `labelled_rows` and `failures`.

## Evaluation: no random splits

Every trained family is evaluated three ways (`aeropulse_ml.evaluation.strategies`):

| Strategy | What it answers |
|---|---|
| `purged_rolling_origin` | Does it beat the baselines on later, unseen time? Folds are purged by the label horizon so no training row overlaps a test label. |
| `leave_region_out` | Does a pooled model transfer to a region it never saw? |
| `season_check` | Does it hold in the region's hazard season (months from the pack's hazard profiles)? |

Preprocessing and calibration are fitted on the training rows of each fold, then
applied to its held-out rows.

## Gates

A gate is not lowered to let a model pass. Thresholds live in
`libs/ml/aeropulse_ml/gates.py` and the family plugins.

| Family | Must pass (per region) |
|---|---|
| `pm25_forecast` | ≥ 3 evaluated rolling folds per horizon; RMSE skill > 0 against every baseline (`persistence`, `cams_forecast`, `climatology_hour_of_week`); P10–P90 coverage ≥ 0.70; leave-region-out skill vs persistence > 0 |
| `pm25_hazard_24h` | ≥ 3 evaluated folds; PR-AUC margin ≥ 0.05 over every baseline (`current_pm25`, `already_above_threshold`, `cams_max_24h`); false-alert rate on quiet hours ≤ 0.10 |
| `anomaly` | ≥ 3 evaluated folds; detection F1 against the hazard label ≥ 0.30; F1 margin > 0 over `absolute_threshold_rule` |
| `source_likelihood` | never promoted |

A hazard score is a rank until the gate report marks the region calibrated. The UI
shows `0.80` as a rank, not a probability, unless `calibrated: true` is served.

## Promotion is a pull request

1. Train, then read `gate.json`. If the region failed, stop: fix data or features, not
   the gate.
2. Copy the promotion snippet the run printed for the regions that passed (it is
   generated from the gate report; never typed by hand) into `config/model_serving.yaml`:

   ```yaml
   entries:
     - family: pm25_forecast
       region_id: in-north
       model_version: <from gate.json>
       artifact_uri: gs://<prefix>-models/runs/<run>/model.joblib
       gate_report_uri: gs://<prefix>-models/runs/<run>/gate.json
       calibrated: false
   ```

3. Run `uv run aeropulse-ml serving --strict`. It exits 1 if any entry would be refused.
4. Open the pull request with the gate report linked. CI runs the same check.

At startup the resolver refuses an entry, and the rule keeps answering, when any of
these hold:

- the region failed its gate, or the report has no result for it;
- the report's family, model version, feature version or feature names differ from the
  entry or from the current feature spec;
- the data was synthetic, or the report is not servable;
- the artifact is missing, or its SHA-256 differs from the one the report pins;
- the entry claims `calibrated: true` and the report does not;
- the family is `source_likelihood`.

Every served prediction carries its model version and `degraded`; hazard also carries
`calibrated`.

## Rolling back

Delete or revert the entry in `config/model_serving.yaml` and deploy. The family falls
back to its rule with `degraded=true`. Artifacts stay in the models bucket (versioned).

## Shadow scoring

Not yet run by the cycle for these families; the `predictions.shadow` table is
reserved for it. When added, it runs only after the operator-facing answer exists and
never changes what is served.
