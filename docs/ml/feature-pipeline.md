# Feature pipeline (`ml-features-3.0.0`)

One code path builds every model row, for training and for serving. If you change a
feature, you change it here, bump the version, and both sides move together.

```text
canonical records ──► PreprocessingPipeline ──► FeatureTables ──► FeaturePipeline.compute ──► rows
(RecordBatch)         (as_of cut, QC, dedup)     (stations, CAMS,   (one row per region, cell, t)
                                                  weather, forecasts,
                                                  fires, rasters)
```

| Piece | Where |
|---|---|
| Feature names, sets, constants, leak declarations | `libs/contracts/aeropulse_contracts/feature_spec.py` |
| Preprocessing steps | `libs/ml/aeropulse_ml/preprocessing/` |
| Tables and computation | `libs/ml/aeropulse_ml/features/tables.py`, `features/pipeline.py` |
| Train/serve parity check | `libs/ml/aeropulse_ml/features/parity.py`, `aeropulse-ml parity` |
| Back-trajectory and puff weights | `libs/intelligence/aeropulse_intelligence/plume/trajectory.py` |
| Synthetic test history | `libs/ml/aeropulse_ml/testing.py` (tests only) |

## Training vs serving

```python
ctx = FeatureContext.for_region(catalog, "in-north", as_of=None)   # training
ctx = FeatureContext.for_region(catalog, "in-north", as_of=cycle)  # serving
rows = FeaturePipeline(PM25_FORECAST).build(batch, ctx, labels=training)
```

- **Training** (`as_of=None`) keeps the full history. Every row at time `t` reads only
  data knowable at `t`; the pipeline enforces this per row.
- **Serving** (`as_of=t`) cuts the batch first (`AsOfCutoff`), keeps the latest forecast
  issue, and returns rows at `t` only.
- **Parity**: a training row at `t` must equal the serving row built from data cut at `t`.
  `aeropulse-ml parity` checks this for the legacy set and for every region × family on
  synthetic multi-day history. It runs in CI. A null on one side only is a mismatch.

## Time rules

- Station and CAMS values are bucketed **hour-ending**: a reading at 12:30 belongs to the
  13:00 bucket, so a bucket is only used once it is complete.
- Knowable time: point records by `observed_at`, forecasts by `issued_at`, rasters by
  `processing_time`.
- Rolling windows use `shift(1)`: `pm25_roll_6h` at `t` covers `t−6h … t−1h`.
- Forecast features at horizon `h` use the latest issue at or before `t` for `valid_at =
  t + h`.

## Labels

- `pm25_target`: the station PM2.5 bucket at `t + h`. Only pack ground-truth sources
  with `measured` provenance can be labels. **CAMS is never a label**; it is a feature.
- `hazard_24h_target`: 1 if the running mean over the region's averaging window
  (`aqi_standard.averaging`, min hours `averaging_min_hours`) crosses
  `region_threshold_ugm3` anywhere in `t+1h … t+24h`. NaN when:
  - the region's AQI standard is unconfirmed (no threshold — the label is not guessed),
  - `t + 24h` is past the last station bucket (the window is incomplete).

## Feature sets

Both sets are **transferable**: no latitude, longitude, cell id, or region id. A model
trained on one region can be scored on another; region identity enters only through
region features from the pack.

| Group | `pm25_forecast` (46) | `pm25_hazard_24h` (40) |
|---|---|---|
| History | `pm25`, lags 1/3/6/24 h, roll mean/max 6/24 h | same |
| Local time (pack timezone) | sin/cos hour, day of week, month | same |
| Region / hazard | `is_stubble_season`, `is_haze_season`, `hazard_*` flags, `region_threshold_ugm3` | same |
| Weather now (nearest site ≤ 50 km) | wind u/v, BLH, temperature, humidity, precipitation | same |
| Forecast | `horizon_hours`, `fc_*` at `t+h` (10 m and 100 m wind, BLH, T, RH, precip) | 24 h mean wind speed, min BLH, precip sum |
| CAMS (model-derived) | `cams_pm25_now`, `cams_pm25_at_h` | `cams_pm25_now`, `cams_pm25_max_24h` |
| Fire | counts in 25/50 km over 24 h, FRP in 50 km, `transport_weighted_frp` | same |
| Satellite (S5P aerosol index, ≤ 48 h old) | `s5p_aerosol_index`, `s5p_valid_fraction` | same |

Seasonal flags come from the pack's hazard profiles (for example in-north's crop-residue
months), not from code.

### Transport-weighted FRP

For each row, a 24 h back trajectory is integrated hourly from the cell centre using the
observed 10 m wind at the nearest site. Each fire seen in the last 24 h adds
`FRP × exp(−d² / 2σ²)`, where `d` is the distance from the fire to the trajectory point at
the fire's age and `σ = 2 km + 0.25 × distance travelled`. This is the ensemble-mean limit
of the plume engine's puff model, not a calibrated dispersion estimate. Unknown wind gives
weight 0, not a guess.

## Changing a feature

1. Edit names or constants in `feature_spec.py` (`FIRE_RINGS_KM`, `NEAREST_SITE_MAX_KM`,
   `SATELLITE_MAX_AGE_HOURS`, `TRANSPORT_*`, …). A constant change alters meaning, so it
   is a feature change too.
2. Declare what a derived feature is computed from in `DERIVED_FROM`. Import fails if any
   closure reaches a target or a future value (`pm25@t+…`).
3. Bump `ML_FEATURE_VERSION`. Artifacts stamped with the old version are refused at
   serving rather than reinterpreted.
4. Run `uv run aeropulse-ml parity` and `uv run pytest tests/unit/test_feature_pipeline_v3.py`.

## Known limits

- The committed in-north replay fixtures are a single snapshot, so they fill only the
  current-hour and context columns. History-dependent parity runs on synthetic data.
- Features from a weather site are NaN for cells more than 50 km from every site. They
  are reported as NaN, never filled from a farther site.
