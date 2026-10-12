# Train and serve: reference

The step-by-step runbook is [train-and-serve.md](train-and-serve.md). This page
is the detail behind it: what each command does, why the limits are where they
are, how the plume works, and how Live is kept free of Demo data. The step
numbers here are not the runbook's.

It covers, in order:

1. How OpenAQ station readings become training history, from live cycles and
  from OpenAQ's hourly archive.
2. How a model is trained, evaluated and gated.
3. How a model that passed its gate is promoted and used for Live predictions.
4. How the plume engine predicts where smoke travels with the wind, and where
  that shows in the UI.
5. How to confirm that Live never shows Demo or replay data.

All commands run from the repository root. Set up two shortcuts once per
terminal (zsh or bash).

The Compose prefix is long, so give it a short name:

```bash
alias dc='docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml'
```

The API calls need your local token. This reads it from `.env` without
printing it:

```bash
export TOKEN=$(grep '^AEROPULSE_WEB_TOKEN=' infrastructure/docker/.env | cut -d= -f2-)
```



## Live OpenAQ coverage

- **Few reference monitors report live.** Most CPCB monitors reach OpenAQ
days late, which a live feed with a 6-hour staleness cutoff cannot use, so
live labels come from very few stations. Their past hours can still be loaded
for training (Step 1b). Re-check with the script in Step 0; this changes with
OpenAQ's upstream ingestion, not with anything in this repository.
- **Low-cost sensors are fresh but are not used.** The region pack sets
`monitor_only: true` on purpose: labels are treated as reference-grade truth
(see "Should low-cost sensors become labels?").
- **Live cycles do not run on their own** in Compose. The `cycle` service only
runs a replay; start the hourly loop (Step 1).
- **DNS drops** (`[Errno -2] Name or service not known` for every source) are
the laptop's network or Docker Desktop, not the connectors.

Checked on 10 Oct 2026: reference-grade (`monitor=true`) PM2.5 monitors OpenAQ lists in the
connector's box (73.8–78.5 E, 27.5–32.2 N), 152 in total:


| Last report     | Monitors                                               |
| --------------- | ------------------------------------------------------ |
| Within 6 hours  | 1 (OpenAQ location 8118, "New Delhi", provider AirNow) |
| 1 to 7 days ago | 109                                                    |
| Older           | 40                                                     |
| Never           | 2                                                      |




## The two training commands, and which one reaches the UI

`aeropulse-ml train` has two modes. Only one of them affects what Live shows.


| Command                                           | Data                                                                                  | Output                                                      | Reaches the Live UI?                                                                                                                                    |
| ------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `aeropulse-ml train --family ...`                 | Raw history the region cycle wrote (`parquet://`, `bq://`, `fixture`, `synthetic://`) | `<out>/<run_id>/model.joblib`, `gate.json`, `metrics.jsonl` | **Yes**, after a reviewed edit to `config/model_serving.yaml`. The region cycle loads it and the API serves the cycle's snapshot.                       |
| `aeropulse-ml train --model ...` (older trainers) | Open-Meteo history, CAMS values as the target                                         | `models/*.joblib` and `models/index.json`                   | **No.** The worker scores these in shadow after the served answer exists. `/grid-hazard` only reports that a champion exists and still serves the rule. |


Use `--family`. The rest of this page is about that path.

## How it fits together

1. **Live sources.** OpenAQ stations give labels and PM2.5 history.
  Open-Meteo gives wind, weather and CAMS. NASA FIRMS gives fires.
2. **Hourly cycle.** `aeropulse-cycle --mode live` fetches them once an hour
  and appends raw history to `/app/var/aeropulse/analytics/raw`.
3. **Training.** `aeropulse-ml train --family` reads that history and writes
  `model.joblib` and `gate.json` to `/app/var/aeropulse/models/runs`.
4. **Promotion.** You review the gate report, copy the run into
  `config/models/`, add it to `config/model_serving.yaml`, then rebuild the images.
5. **Serving.** The next cycle loads the promoted model, runs the plume engine
  on wind, fires and events, and writes a Live snapshot with forecasts,
   hazard and plumes.
6. **API and UI.** The API answers `/map/forecast`, `/map/hazard`, `/plumes`
  and `/models` from that snapshot. The Live UI shows them on the Command
   Centre map and the Forecast and Models pages.

Three details matter:

- **Training reads what the region cycle wrote, not Timescale.** The
`connector` → Redpanda → `worker` → Timescale path powers part of the map,
but `aeropulse-ml train` never reads it. History for training exists only
after live **cycles** have run.
- **Training never changes what is served.** A run writes files and prints a
YAML snippet. Only an edit to `config/model_serving.yaml`, which you review,
changes what Live serves.
- **The plume is not a trained model.** It is deterministic transport physics
run inside each cycle. Training and promotion do not change it.



## Step 0. Get OpenAQ records flowing

**0.1 Rebuild the images that run connectors**, so they pick up the
discovery fix. The `connector` service feeds the map; the `cycle` image runs
the same connector in-process for training history and plumes. `api` carries
the Live grid fix from the previous review.

```bash
dc build connector cycle api
dc up -d --no-deps connector api
```

**0.2 Check DNS from inside the connector**, if the network has been flaky.

```bash
docker exec aeropulse-connector-1 python -c "import socket; print(socket.gethostbyname('api.openaq.org'))"
```

An IP address is good. `Name or service not known` means Docker cannot
resolve names: reconnect the network, then restart Docker Desktop or
`dc restart connector`.

**0.3 Check the source**, about 15 minutes after the restart (OpenAQ polls
every 900 s).

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/sources \
  | python3 -c 'import json,sys; [print(s["source_id"], s["status"], s["records_per_run"], (s["error"] or "")[:80]) for s in json.load(sys.stdin)["items"] if s["source_id"] in ("openaq","openmeteo","firms")]'
```

You want `openaq HEALTHY` with a record count above zero. `401` means the key
is rejected. `HEALTHY` with `0` means no monitor in the box reported inside
the staleness window; the connector log says how many it skipped:

```bash
docker logs --since 1h aeropulse-connector-1 2>&1 | grep openaq.locations_not_reporting | tail -1
```

**0.4 See how many reference monitors OpenAQ has live right now.** This reads
the key from `.env` without printing it:

```bash
set -a; . infrastructure/docker/.env; set +a
python3 - <<'EOF'
import json, os, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone
params = {"bbox": "73.8,27.5,78.5,32.2", "parameters_id": 2, "monitor": "true", "limit": 1000}
req = urllib.request.Request(
    "https://api.openaq.org/v3/locations?" + urllib.parse.urlencode(params),
    headers={"X-API-Key": os.environ["AEROPULSE_OPENAQ_API_KEY"]},
)
now = datetime.now(timezone.utc)
ages = Counter()
for loc in json.load(urllib.request.urlopen(req, timeout=30))["results"]:
    last = (loc.get("datetimeLast") or {}).get("utc")
    if not last:
        ages["never"] += 1
        continue
    hours = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 3600
    ages["<6h" if hours < 6 else "<24h" if hours < 24 else "<7d" if hours < 168 else "older"] += 1
print(dict(ages))
EOF
```

Only the `<6h` count can produce live labels. The `<24h` and `<7d` monitors
cannot feed a live cycle, but their past hours can be loaded for training
(Step 1b).



### Should low-cost sensors become labels?

`monitor_only: true` in `config/regions/in-north/region.yaml` keeps OpenAQ to
reference-grade monitors. Setting it to `false` would add the fresh low-cost
sensors, but they would arrive under the same `openaq` source id, which the
pack lists in `ground_truth_sources`. The trainer would then treat uncorrected
low-cost readings as station truth, and gates would pass or fail against them.
Do not flip it to get more rows. If you want them, they need their own source
id and quality flag, kept out of `ground_truth_sources` until corrected. That
is a code change, not a config change.

## Step 1. Build history: one live cycle every hour

Each live cycle fetches the sources, appends the raw records to the history
tables, builds features with a 72-hour look-back, serves models or rules,
runs plumes, and writes the Live snapshot. The same loop that builds training
history also serves predictions and plumes, so leave it running:

```bash
while true; do
  dc run --rm -T cycle uv run aeropulse-cycle --region in-north --mode live
  sleep 3600
done
```

Each run prints one JSON line. Check `sources` (OpenAQ should be `healthy`)
and `rows_loaded` (`raw.air_quality` should be above zero).

Why hourly:

- In a live cycle the OpenAQ connector reads `GET /v3/locations/{id}/latest`.
Each call returns one current reading per station, so live history only
grows as fast as cycles run. A missed hour is a gap in the label and lag
columns.
- A laptop that sleeps stops the loop. Gaps are fine; the pipeline treats them
as missing, never as zero.
- To start with weeks of history instead of waiting for it, load the past
from the providers' archives once (Step 1b), then keep this loop running.

Do not use `aeropulse-cycle --mode backfill` for this. It runs a full cycle
for every hour (snapshot, plumes, predictions), each with its own 48-hour
fetch. `--mode history` below is the training-data loader.

Where the history lands (the `aeropulse-data` volume, shared by `cycle`,
`api` and `citizen-analyzer`):

```
/app/var/aeropulse/analytics/raw/air_quality/*.parquet
/app/var/aeropulse/analytics/raw/weather/*.parquet
/app/var/aeropulse/analytics/raw/meteo_forecast/*.parquet
/app/var/aeropulse/analytics/raw/fire/*.parquet
/app/var/aeropulse/analytics/raw/raster/*.parquet
```

Each row holds `region_id`, `known_at` and `record` (the canonical record as
JSON). To see how much station data you have, per station:

```bash
dc run --rm -T cycle uv run python -c "
import glob, json, pandas as pd
files = glob.glob('/app/var/aeropulse/analytics/raw/air_quality/*.parquet')
if not files:
    raise SystemExit('no raw air-quality history yet: run live cycles first')
d = pd.concat(map(pd.read_parquet, files))
r = d['record'].map(json.loads)
d['source'] = r.map(lambda x: x['source_id'])
d['station'] = r.map(lambda x: f\"{x['location']['lat']:.3f},{x['location']['lon']:.3f}\")
print(d.groupby('source').agg(rows=('station', 'size'), stations=('station', 'nunique')).to_string())
print('known_at from', d['known_at'].min(), 'to', d['known_at'].max())
"
```

Only the `openaq` rows turn into labels.

### What an OpenAQ reading becomes

1. The connector maps each fresh PM2.5 or PM10 reading to an `observation.v1`
  record: station coordinates, value in µg/m³, `observed_at`, and provenance
   `OpenAQ / <upstream provider>`, with `provenance_class: measured`.
2. The cycle stores the record in the raw history and, in the feature step,
  puts it in its 1 km H3 cell (resolution 8) for its hour. A station value
   outranks a CAMS value for the same cell-hour.
3. The feature row for that cell and hour combines the station's PM2.5 lags
  and rolling statistics, Open-Meteo weather now and forecast for the target
   hour (wind at 10 m and 100 m, boundary layer, rain), CAMS PM2.5 now and at
   the target hour, FIRMS fires within 25 and 50 km plus fire power weighted
   by a back-trajectory from the cell, the Sentinel-5P aerosol index, and
   local time, season and hazard flags. Every value uses only data known at
   that hour.
4. The label for a row at hour `t` is the station PM2.5 in the **same cell**
  at `t + h`. A row has a label only when a station reported there again at
   `t + h`.

So history grows by at most one labelled row per reporting station per hour.
With one live reference station, that is at most 24 rows a day.

### How much history is enough

These floors come from the code, not from experience:

- Each fit needs at least 60 labelled rows (`MIN_FIT_ROWS`).
- Every gate needs at least 3 evaluated folds (`MIN_EVALUATED_FOLDS`).
- Purged rolling-origin evaluation cuts the labelled time span into 6 equal
blocks (5 folds + 1). Fold *k* trains on rows earlier than
`start + k × span / 6 − 24 h`. Folds 3 to 5 have training rows only when
the labelled span is over 48 hours. Fold 1 needs more than 6 days.
- The 24-hour label of the last day is not known yet, so the labelled span is
about a day shorter than the collection span.

Below about three days of hourly cycles with OpenAQ records, a run cannot even
produce a gate verdict. Above that, whether a model beats persistence depends
on the data; nobody can say in advance how many weeks that takes. With one
station, expect the gates to fail for a long time: a single site gives little
to learn from beyond "the value now", which is exactly the persistence
baseline. The gate report tells you.

## Step 1b. Load past data from the provider archives (optional)

Live, OpenAQ gives about one fresh reference station. Its archive is much
richer: the 110 reference monitors that reported within the last week (see
the table above) all have hourly series, and CPCB values reach that archive
days after the fact. `aeropulse-cycle --mode history` reads those archives
and writes them into the same raw history tables the live cycle writes, so
`aeropulse-ml train` reads both without any change.

### Run it

Rebuild the `cycle` image once so it has the command, then load 60 days:

```bash
dc build cycle
dc run --rm cycle uv run aeropulse-cycle --region in-north --mode history --days 60
```

The window runs from midnight UTC 60 days ago to the current hour, in 5-day
chunks (`--chunk-days` changes that). Each chunk is stored before the next is
fetched and prints one JSON line as soon as it is stored, so expect about a
dozen lines over the run. If the command ends with no JSON line at all, the
container was killed, most likely for memory (20-day chunks peaked above the
old 1 GB limit). Check, per chunk:

### A year, one quarter at a time

The hazard model needs the winter: the October–November stubble burning and
the December–January inversions are where the threshold crossings are, and a
60-day window from August to October has few of them. Load from 1 October 2025
in four runs, so one failure costs a quarter, not the year. Re-running a
quarter is safe: repeated records are dropped before training.

```bash
for w in 2025-10-01T00:00Z,2026-01-01T00:00Z 2026-01-01T00:00Z,2026-04-01T00:00Z \
         2026-04-01T00:00Z,2026-07-01T00:00Z 2026-07-01T00:00Z,; do
  s=${w%,*}; e=${w#*,}
  caffeinate -i docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml \
    run --rm cycle uv run aeropulse-cycle --region in-north --mode history \
    --start="$s" ${e:+--end=$e} --chunk-days 30
done
```

`--chunk-days 30` keeps each OpenAQ sensor to one page per chunk (720 hourly
values, under the 1,000-row page), which is what sets the run time: about 13
chunks × 2 sensors × 110 or more monitors ≈ 2,900 requests at the 2.2 s
measured above, so roughly two hours. If a chunk is killed for memory (no JSON
line, exit `137`), re-run that quarter with `--chunk-days 10`; that is about
three times the requests. The last quarter overlaps the 60 days already
loaded; the overlap is dropped as duplicates.

- `sources.openaq.records` is above zero. This is the station data that
becomes labels.
- `sources.openmeteo` and `sources.firms` say `healthy`. `not_configured` for
`cpcb` (replay only) and `earthengine` (no credential) is expected.
- `rows_loaded` shows `raw.air_quality`, `raw.weather` and `raw.fire` rows.

The command exits `1` if no source returned a single record. Running it again
is safe: repeated records are dropped by the dedup step before training. Then
check the result with the per-station script in Step 1. The `openaq` row
count should now be far above what the live loop collected.

### What each source fetches in history mode

- **OpenAQ.** Every reference monitor whose reporting span overlaps the
window, with no live cap and no staleness cutoff. For each PM2.5 and PM10
sensor it pages `GET /v3/sensors/{id}/hours` over the window. An hourly mean
is stamped at the **end** of its hour, the moment it became knowable.
- **Open-Meteo.** Weather and CAMS for every wind site, with `start_date` and
`end_date`. No forecasts (see below). A chunk that starts more than 30 days
back reads weather from the historical-forecast API
(`historical-forecast-api.open-meteo.com`): same variables and units, kept
back to 2022. The forecast API only keeps about three months, and its oldest
days come back empty. CAMS comes from the air-quality API either way.
- **NASA FIRMS.** Fire detections by date, in 5-day requests (the API maximum),
for each product in the region pack. The pack lists near-real-time products
(`VIIRS_NOAA20_NRT`, `VIIRS_SNPP_NRT`), which FIRMS keeps for a few months
only. For older days the connector asks FIRMS where the standard-processing
twin (`VIIRS_NOAA20_SP`, `VIIRS_SNPP_SP`) ends and reads it up to that day,
then the NRT product after it. Each record keeps the product it came from
(`NASA FIRMS VIIRS_NOAA20_SP` as the provider). The same detection in both
products has the same id, so the seam cannot double-count.

How long it takes. A test run of the OpenAQ history path on a small box
around central Delhi (77.1–77.3 E, 28.5–28.7 N, 1–3 September 2026) made 44
requests in 97 seconds, about 2.2 s each, and returned 2,011 hourly values
from 22 stations (1,965 CPCB, 46 AirNow). For the whole region and 60 days,
estimate about 4 chunks × 2 sensors × 110 or more monitors ≈ 880 OpenAQ
requests, so roughly half an hour, plus 2 Open-Meteo requests per wind site
per chunk and a few dozen FIRMS requests.

### Limits you should know before training on it

- **No forecast features for past hours.** Open-Meteo returns past model
output without naming the run that produced it, so no `issued_at` can be
proved. History mode stores no `meteo_forecast` rows, and the `fc_*` features
(`fc_wind_u_10m`, `fc_boundary_layer_height`, and the rest) are empty for
backfilled hours. Live cycles fill them from then on. For the same reason the
plume's wind-uncertainty check (7 days of forecast-vs-observed wind pairs)
gets nothing from a history load.
- **Live serving will not see what training saw.** In the archive, CPCB
stations have complete hourly lags. Live, the same stations arrive days late,
so at serving time their lag features are usually missing. A model that
leans on station lags can pass its gate on archive data and still do worse
live. The gate report says how many station rows came from history (see
"Read the result"); weigh that before promoting.
- **How far back.** Checked on 2026-10-11:
  - OpenAQ `GET /v3/sensors/{id}/hours` returned hourly PM2.5 for 1 November 2025.
  - The Open-Meteo forecast API accepts start dates from 2026-07-10 only, and
    returns nulls for its oldest days. The historical-forecast API returned
    every weather variable for October and November 2025.
  - Open-Meteo CAMS returned October 2025.
  - FIRMS NRT products start on 2026-07-01, and the SP products run to 2026-06-30.

  OpenAQ also publishes a keyless archive on AWS
  (`s3://openaq-data-archive/records/csv.gz/locationid=<id>/year=<y>/month=<m>/`),
  one gzipped CSV per location per day. The API above already reaches a year,
  so the loader does not use it; it is the fallback if the API rate limit
  becomes the bottleneck.
- **Memory.** Training reads only what the features read: PM2.5 observations
(station and CAMS), weather, fires and rasters. CAMS PM10 and gases, and
station PM10, are skipped before decoding; the gate report's `dataset.uri`
ends in `?observations=pm25` to say so. A Parquet history longer than 31 days
is then loaded one calendar month at a time, with 72 hours before and 48 hours
after each month, so only one month of decoded records is held at once. On
the 60 days of `in-north` loaded on 10 Oct 2026, the monthly frame was identical to
a single load, row for row, for forecast and hazard. Building it peaked at
1.7 GB (hazard) and 2.1 GB (forecast) instead of 3.2 GB, and full training
runs peaked at 1.65 GB (hazard) and 2.9 GB (forecast).
- **What a year needs.** After loading, training grows with rows. Hazard and
anomaly have one row per station-hour; forecast has five, one per horizon.
A year of hazard is about as many rows as 60 days of forecast, so it fits
under the 4 GB ceiling (`AEROPULSE_CYCLE_MEM_LIMIT` in `.env`; Docker Desktop
on this laptop has about 8 GB in total). A year of forecast does not: train
forecast on a recent window with `--start` (Step 2). It already passes on 60
days. If a run ends early with no summary and exit code `137`, it was killed
for memory: shorten the window, or raise the ceiling to `6g`.
- **Archive values are not live values.** They are the provider's published
hourly means, possibly corrected after the fact. They stay
`provenance_class: measured` and are never shown on the Live map: the map
reads the live snapshot, which a history load does not write. A history load
writes no snapshot, prediction, alert or source-health row, and does not move
the live watermarks.

## Step 2. Train

Train inside the `cycle` container. It has the `aeropulse-ml` command, reads
the history volume directly, and writes the run where the cycle can load it:

```bash
dc run --rm cycle uv run aeropulse-ml train \
  --family all \
  --dataset parquet:///app/var/aeropulse/analytics \
  --regions in-north \
  --out /app/var/aeropulse/models/runs \
  --load-eval
```

- `--family all` runs `pm25_forecast`, `pm25_hazard_24h`, `anomaly` and
`source_likelihood`. Pass one family to train only that one.
- `--dataset parquet://...` reads the cycle layout: `<root>/raw/<table>/*.parquet`,
filtered to the region.
- `--out` must be inside `/app/var/aeropulse`. Anything else in a
`docker compose run` container is lost when it exits.
- `--load-eval` also writes the metric rows to the evaluation table that the
Models page reads (`/api/v1/ml/evaluation`).
- `--folds` defaults to 5. `MIN_EVALUATED_FOLDS` stays 3 whatever you pass.
- `--start` and `--end` (ISO times, UTC) limit the observation window. Without
them the run reads all history.

After a year of history (Step 1b), train one family at a time, so a memory
kill costs one family, and give forecast a recent window:

```bash
for f in pm25_hazard_24h anomaly; do
  dc run --rm cycle uv run aeropulse-ml train --family $f \
    --dataset parquet:///app/var/aeropulse/analytics --regions in-north \
    --out /app/var/aeropulse/models/runs --load-eval
done
dc run --rm cycle uv run aeropulse-ml train --family pm25_forecast \
  --dataset parquet:///app/var/aeropulse/analytics --regions in-north \
  --out /app/var/aeropulse/models/runs --load-eval \
  --start "$(date -u -v-60d +%Y-%m-%dT00:00Z)"
```

`date -v-60d` is the macOS form; on Linux use `date -u -d '60 days ago' ...`.



### What happens during a run

For each family, `libs/ml/aeropulse_ml/training/runner.py` does this:

1. **Load.** `ParquetDatasetSource.load("in-north")` returns the region's
  canonical records: PM2.5 observations, weather, meteo forecasts, fires, rasters.
2. **Preprocess.** This is the same `PreprocessingPipeline` the cycle runs:
  dedup, unit and range checks, hour-ending buckets, and the
   stations-outrank-CAMS rule for the same cell-hour.
3. **Features.** The one `FeaturePipeline` (`ml-features-3.0.0`) builds a row
  per station cell and hour. Feature names come from
   `libs/contracts/aeropulse_contracts/feature_spec.py`, which serving imports
   too. `uv run aeropulse-ml parity` checks that training and serving agree.
4. **Labels**, from ground-truth stations only (`openaq`, `cpcb`):
  - `pm25_forecast`: station PM2.5 at `t + h` for `h` in 1, 3, 6, 12 and 24 hours.
    Where the station's current value is known, the model learns the change from
    it and adds it back, so it starts from persistence; otherwise it learns the level.
  - `pm25_hazard_24h` and `anomaly`: 1 if the station concentration reaches
  the region's hazard threshold in `t+1 … t+24`, else 0. The threshold
  comes from the CPCB bands in `config/aqi_standards/`.
5. **Evaluate.** Time-based splits only: purged rolling-origin; leave-region-out
  when more than one region is passed; and a season check when the history
   covers a season from the hazard profile. Baselines are fitted on the same
   training rows.
6. **Final fit** on all labelled rows. The forecast quantiles and the hazard
  calibration use a slice carved off the end of training time.
7. **Gate** per region (see the table below).
8. **Write** `<out>/<run_id>/model.joblib`, `gate.json` (family, version,
  feature version and names, dataset lineage and fingerprint, artifact
   SHA-256, per-region result and failures) and `metrics.jsonl`.

The run never writes `config/model_serving.yaml`.

### What each family must beat


| Family              | Model                                                                        | Must pass, per region                                                                                                                                                                                                         |
| ------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pm25_forecast`     | HistGradientBoosting quantile regression (P10/P50/P90), pooled over horizons | At every horizon: 3+ evaluated folds; RMSE skill above 0 against persistence, raw CAMS for that hour, and hour-of-week climatology; P10–P90 coverage at least 0.70. With leave-region-out, skill against persistence above 0. |
| `pm25_hazard_24h`   | HistGradientBoosting classifier with isotonic calibration                    | 3+ folds; PR-AUC at least 0.05 above each baseline (current PM2.5, already above threshold, max CAMS over 24 h); an operating point exists; false-alert rate no more than 0.10 there.                                         |
| `anomaly`           | Hour-of-week P10/P50/P90 table per station                                   | 3+ folds; detection F1 against the hazard label at least 0.30; F1 above the absolute-threshold rule.                                                                                                                          |
| `source_likelihood` | Heuristic evidence weights                                                   | Never served as a model. It ranks with evidence and never shows a percentage.                                                                                                                                                 |


Do not lower a gate to pass (`libs/ml/aeropulse_ml/gates.py`). A failed gate is
a valid result: the rule keeps serving, labelled degraded.

## Step 3. Read the result

The command prints a JSON summary on stdout. For each family it lists
`run_id`, `model_version`, the `gate_report` path, `servable`, and per region
`passed`, `labelled_rows`, `calibrated` and `failures`.

For a family that passed in some region, stderr also prints a snippet like this:

```yaml
  - family: pm25_forecast
    region_id: in-north
    model_version: hgbq-forecast-<timestamp>
    artifact_uri: /app/var/aeropulse/models/runs/pm25_forecast-<run time>/model.joblib
    gate_report_uri: /app/var/aeropulse/models/runs/pm25_forecast-<run time>/gate.json
    calibrated: false
```

The paths are where the run landed on the volume. Step 4 copies the run into
the repo and switches them to `config/models/...`.

To read a full report later:

```bash
dc run --rm -T cycle sh -c 'ls /app/var/aeropulse/models/runs'
dc run --rm -T cycle sh -c 'cat /app/var/aeropulse/models/runs/<run_id>/gate.json' | python3 -m json.tool
```

If you loaded history (Step 1b), the report's `notes` include a line like
`in-north: N of M ground-station observations were loaded from provider
archives by aeropulse-cycle --mode history, not seen by live cycles`. When
most station rows came from history, the gate measured archive data, not what
the live feed delivers.

When it does not pass:


| Message                                                                    | Meaning                                                                           |
| -------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `no labelled rows for this region in the dataset`                          | No OpenAQ station history. Go back to Step 0.                                     |
| `pm25_forecast: N labelled rows, need 60`                                  | Too little history. Keep the hourly loop running, or load history (Step 1b).      |
| `purged rolling-origin not available: ...` or `N evaluated folds (need 3)` | The labelled span is too short for the folds. See "How much history is enough".   |
| `RMSE skill vs persistence is -0.0123 (must exceed 0)`                     | The model is worse than "the value now". Not servable, and that is a real result. |
| `P10-P90 coverage is 0.55 (must reach 0.7)`                                | The intervals are too narrow to trust.                                            |
| `servable: false` with `synthetic dataset`                                 | `synthetic://` is test data and is never served.                                  |


`fixture` datasets are the committed replay files (25 feature rows and no
labels for `in-north`). Do not promote a model trained on them.

## Step 4. Promote: edit `config/model_serving.yaml`

**4.1 Copy the passed run into the repo.** A run on the volume exists only on
this laptop: the tests, CI and the Cloud Run image cannot see it. Copy the run
folder (about 2.5 MB) under `config/models/<region>/`, which both images
already copy with `config/`:

```bash
dc run --rm -v "$PWD/config/models:/out" cycle \
  sh -c 'mkdir -p /out/in-north && cp -r /app/var/aeropulse/models/runs/<run_id> /out/in-north/'
```

Copy only runs whose gate report passed for that region, and commit them with
the YAML change.

**4.2 Paste the snippet under `entries:`, with the paths in the repo.**

```yaml
schema_version: model_serving.v1
entries:
  - family: pm25_forecast
    region_id: in-north
    model_version: hgbq-forecast-<timestamp>
    artifact_uri: config/models/in-north/<run_id>/model.joblib
    gate_report_uri: config/models/in-north/<run_id>/gate.json
    calibrated: false
```

Leave `calibrated` as the snippet printed it. An entry that claims
calibration its gate report does not support is refused. Relative paths
resolve against the folder that holds `config/`: the repo root on the host,
`/app` in the images.

**4.3 Rebuild the images that read `config/`.** The Dockerfile copies
`config/` in at build time, so an edit on the host does nothing until you
rebuild:

```bash
dc build cycle api
dc up -d --no-deps api
```

**4.4 Check that the entry loads.**

```bash
uv run aeropulse-ml serving --strict
dc run --rm cycle uv run aeropulse-ml serving --strict
uv run pytest tests/unit/test_ml_serving.py -q
```

`served.in-north` should list the family with your `model_version` and
`"degraded": false`. `refused` should be empty. If not, the reason says which
check failed: region gate, feature version, feature names, synthetic data,
artifact missing, SHA-256 mismatch, or calibration claim. The serving tests
read `model_serving.yaml` and fail if any entry is refused.

Accepted artifact URIs, as the cycle and the `serving` command resolve them:


| URI                                             | Resolves to                                                                                                                   |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `config/models/...` (relative)                  | The repository: host checkout, tests, and `/app/config/models/...` in both images. Recommended.                               |
| `/app/var/aeropulse/models/runs/...` (absolute) | The shared volume. Works only inside this laptop's containers; tests and Google Cloud refuse it as `file not found`.         |
| `s3://local-models/<key>`                       | The local object store's `models` area. Objects must be written through the store, because each one has a generation sidecar. |
| `gs://<project>-aeropulse-models/<key>`         | Google Cloud, with `AEROPULSE_PLATFORM=gcp`.                                                                                  |




## Step 5. Serve, and see it in the UI

The resolver loads `model_serving.yaml` once per cycle process. Each
`docker compose run --rm cycle` is a fresh process, so the next run of the
hourly loop uses the new entry. To run one now:

```bash
dc run --rm cycle uv run aeropulse-cycle --region in-north --mode live
```

In the printed JSON, `served` maps each family to the version that actually
answered. Before promotion it shows the rule versions, for example
`persistence-forecast-1.0`. After a successful promotion it shows your
`hgbq-forecast-…`.

How the prediction reaches the browser:

1. The cycle writes a Live snapshot (`snapshots/in-north/…`, then the
  `latest` pointer) with `forecasts`, `hazard`, `anomalies`,
   `source_likelihood`, `plumes` and `served_models`. Each prediction carries
   `model_version`, `degraded`, `degraded_reason` and, for hazard,
   `calibrated`.
2. The API answers from that snapshot: `/api/v1/map/forecast`,
  `/api/v1/map/hazard`, `/api/v1/map/source-likelihood`, `/api/v1/plumes`
   and `/api/v1/models`. The response's `data_source` names the snapshot and
   cycle. `/models` items say `verified_by_cycle: true`.
3. The Live UI calls those endpoints through `services/resolve.ts`:
  - **Models**: one row per family with version, degraded or promoted, and
   calibrated yes or no. Below it, the evaluation runs that `--load-eval`
   wrote.
  - **Forecast**: a model line with version and degraded reason. Hazard shows
  "rank" until calibrated, and "probability" only when it is.
  - **Command Centre map**: forecast, hazard, wind and plume layers from the
  same snapshot.

If a served model fails while predicting (missing column, bad artifact), the
rule answers for that cycle. The family then shows `degraded: true` with
`model <version> failed at serving: <error>`. Nothing silently changes back
to a model.

Rollback: delete the entry, rebuild `cycle` and `api`, and run a cycle. The
rule answers again, marked degraded.

### On Google Cloud

The app image copies `config/`, so promoted runs under `config/models/` travel
inside it: no models-bucket upload is needed, and the same
`model_serving.yaml` serves there. The deploy steps are Step 8 of
[train-and-serve.md](train-and-serve.md).

## Plume: where the smoke travels with the wind

The plume answers two questions: "from this fire or event, where does the
smoke go over the next hours?" (forward) and "this cell's air is unusual;
where did it come from?" (backward). It is physics on forecast wind. **It is
not trained,** `model_serving.yaml` **does not affect it, and no language model
touches it.** Every plume is labelled "Predicted smoke transport —
experimental", has `provenance_class: simulated`, and lists `degraded_reasons`
for anything its inputs could not support.

### What drives it


| Input                                | Source                                                                                    | Used for                                                                                                                                     |
| ------------------------------------ | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Wind at 10 m and 100 m, hourly       | Open-Meteo forecast for up to 60 weather sites (H3 resolution 5) across the source domain | Where particles move. The two heights are blended by the hazard profile; for `in-north` that is `crop_residue_burning`: 70% 10 m, 30% 100 m. |
| Observed 10 m wind                   | Open-Meteo current weather                                                                | Fills hours no forecast covers; the backward run uses observed wind only.                                                                    |
| Cloud cover, precipitation           | Open-Meteo                                                                                | Atmospheric stability (spread) and rain wash-out.                                                                                            |
| Fire clusters                        | NASA FIRMS                                                                                | Forward release points, and candidate sources for backward runs.                                                                             |
| Open pollution events, anomaly flags | Detection and anomaly stages, which OpenAQ station readings feed                          | Forward runs from events, backward runs from anomalies.                                                                                      |
| Seeded citizen reports               | Citizen analyzer, after deterministic corroboration                                       | Forward release points.                                                                                                                      |


OpenAQ does not move the plume. Wind comes from Open-Meteo. OpenAQ matters
because station readings create the anomalies and events that plumes start
from, and because they are how a plume could be checked later.

### Which plumes each cycle runs

`apps/cycle/aeropulse_cycle/plumes.py`, at most 15 per cycle:

- **Forward**, horizons 1, 3, 6, 12 and 24 h (from `crop_residue_burning`):
the 5 fire clusters with the highest total fire radiative power, up to 5
open events, and every seeded citizen report.
- **Backward**, horizons 6, 12 and 24 h: the 5 highest-scoring anomaly cells.

No fire, event, anomaly or report means no plume, and the snapshot says so in
`field_status`.

### How it is computed

`libs/intelligence/aeropulse_intelligence/plume/`, model version
`lagrangian-ens-1.0`:

1. **Wind field** (`wind.py`). For each site and valid hour, take the newest
  forecast issued by the cycle time and blend 10 m and 100 m by the profile
   weights. Between sites, a particle reads the wind by inverse-distance
   weighting; between hours, linearly. Hours with no wind are persisted from
   the nearest covered hour and reported as `persisted_wind_after_<hour>`;
   they are never invented.
2. **Particles** (`ensemble.py`). Release 200 particles at the origin, spread
  by the origin's `initial_spread_km`. Step them every 15 minutes with a
   midpoint (RK2) step through the time-varying wind, so a plume bends when
   the wind turns. Backward runs step against the wind.
3. **Turbulent spread** (`stability.py`). Each step adds a random spread from
  the Pasquill stability class (from wind speed, sun elevation and cloud) and
   Briggs (1973) rural horizontal dispersion. Light wind on a clear night
   spreads little; a sunny afternoon spreads a lot.
4. **Wind uncertainty** (`uncertainty.py`). Once 7 days of forecast-vs-observed
  wind pairs exist, each particle's wind is perturbed by the measured speed
   and direction error for its lead time. Before that, the spread is zero and
   the plume carries `wind_uncertainty_unmeasured`.
5. **Rain wash-out.** In forward runs, particles lose weight while it rains
  (the HYSPLIT default scavenging rate). Positions do not change.
6. **Leaving the domain.** A particle that leaves the source-domain box stops
  counting; the plume reports `left_wind_domain_<n>pct`.

The same inputs always give the same plume: the plume id and its random
stream both come from the region, cycle time, direction and origin.

### What a plume tells you

For each horizon (`horizons[]`):

- `p50_cells` and `p90_cells`: the smallest set of H3 cells holding 50% and
90% of the airborne particle weight. Resolution 8 (about 1 km) inside the
region, resolution 6 outside. This is the footprint the map draws.
- `centroid_lat`, `centroid_lon`: the median particle position, the plume's
centre at that hour.
- `weight_remaining`: the share of weight not washed out by rain.

For the whole run:

- `arrivals` (forward): for each gazetteer place reached, the probability that
particles pass within its radius and the median arrival time.
- `exposure` (forward): estimated population inside the P90 footprint.
- `source_candidates` (backward): fire clusters inside the back-trajectory
footprint, with the share of particles passing over each, distance and
bearing. "Likely source region", never "caused by".
- `settings`: particles, step, diffusion method, wind heights, and whether
wind uncertainty was measured.

`in-north` has no `gazetteer.parquet` or `population_h3r8.parquet` built yet.
Footprints still run; arrivals and exposure are empty, and the snapshot gives
the reason (`gazetteer not built for in-north`, `population raster not built for in-north`). The UI shows "—" with that reason.

A plume is a footprint and timing of transport, not a PM2.5 concentration.
It says where and when smoke from this origin is likely to be, not how many
µg/m³ it adds.

### Direction and distance travelled

To turn a plume into "where it went and how fast", take the bearing and
distance from the origin to each horizon's centroid. After a live cycle has
written a snapshot:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/plumes?region_id=in-north&direction=forward" -o /tmp/plumes.json
python3 - <<'EOF'
import json, math
body = json.load(open("/tmp/plumes.json"))
if not body.get("items"):
    raise SystemExit(f"no plumes: {body.get('field_status')}")
COMPASS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
for p in body["items"]:
    o = p["origin"]
    print(f"{p['plume_id']}  {o['kind']} {o.get('ref_id') or ''}  from {o['lat']:.3f},{o['lon']:.3f}")
    print(f"  degraded: {', '.join(p['degraded_reasons']) or 'no'}")
    for h in p["horizons"]:
        if h["centroid_lat"] is None:
            print(f"  +{h['horizon_hours']:g} h  no particles left in the wind domain")
            continue
        la1, lo1 = math.radians(o["lat"]), math.radians(o["lon"])
        la2, lo2 = math.radians(h["centroid_lat"]), math.radians(h["centroid_lon"])
        dlo = lo2 - lo1
        a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
        km = 2 * 6371.0088 * math.asin(math.sqrt(a))
        brg = (math.degrees(math.atan2(math.sin(dlo) * math.cos(la2),
               math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo))) + 360) % 360
        print(f"  +{h['horizon_hours']:g} h  centre {km:6.1f} km toward {COMPASS[round(brg / 22.5) % 16]:>3} "
              f"({brg:5.1f}°), {km / h['horizon_hours']:5.1f} km/h, P90 {len(h['p90_cells'])} cells")
    for a in p["arrivals"]:
        print(f"  reaches {a['name']}: probability {a['probability']:.2f}, median {a['eta_hours_median']} h")
EOF
```

Bearing is the direction the smoke moves toward (0° north, 90° east). That is
the opposite of the meteorological "wind from" direction.

What the output looks like. This sample is from the **Demo recording**
(`frontend/web/src/data/regions/in-north/recording.json`, a replayed
2026-09-08 episode), not from live data:

```
plm_f8607122f5d0c47c74fb  fire_cluster 863d16dafffffff:20260908T0440Z  from 30.120,75.710
  degraded: persisted_wind_after_2026-09-08T06Z, observed_wind_10m_only, wind_uncertainty_unmeasured, left_wind_domain_100pct
  +1 h  centre   12.4 km toward   E ( 90.9°),  12.4 km/h, P90 10 cells
  +6 h  centre   74.4 km toward   E ( 90.9°),  12.4 km/h, P90 56 cells
  +12 h  centre  147.9 km toward   E ( 90.7°),  12.3 km/h, P90 111 cells
  +24 h  no particles left in the wind domain
```

Read it as: smoke from this fire cluster moves east at about 12 km/h, and the
90% footprint widens from 10 to 111 cells over 12 hours. The degraded reasons
say why to trust it less: the wind after 06Z was held, not forecast; only 10 m
observed wind was available; wind error was not yet measured; and by +24 h
every particle had left the region box.

The wind arrows themselves come from `/api/v1/map/weather?region_id=in-north`.

### Try a release point yourself (what-if)

`POST /api/v1/plume/what-if` runs a forward plume from any point in the region,
on the latest Live cycle's wind and the last 72 hours of raw history. It is not
stored. It needs the operator, analyst, authority or admin role (the admin
token from local-live.md works). Each user gets 30 runs an hour
(`AEROPULSE_PLUME_WHAT_IF_PER_HOUR`), and clicks within about 1 km share one
cached run.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"region_id": "in-north", "lat": 30.90, "lon": 75.85, "initial_spread_km": 1.0}' \
  http://127.0.0.1:8000/api/v1/plume/what-if -o /tmp/plumes-whatif.json
python3 -c 'import json; d=json.load(open("/tmp/plumes-whatif.json")); print(json.dumps({"items": [d]} if "plume_id" in d else d)[:400])'
```

To read it with the direction script above, save the response as
`{"items": [<plume>]}` in `/tmp/plumes.json`. With no Live snapshot, the
answer is `status: not_configured` with the reason. The UI does not call
what-if yet; it is API only.

### Where plumes show in the Live UI

- **Command Centre.** The "Plumes" figure counts forward and backward runs in
the latest cycle. The map draws each plume's P50 and P90 footprint, and the
horizon control steps through +1 h to +24 h. Wind arrows come from the
weather layer. Toggle layers in the map's layer panel.
- **Incident panel.** Open an event to see the plumes linked to it, the places
reached with arrival time, and estimated exposure, or "—" with the reason.
- `GET /api/v1/map/plume?region_id=in-north&horizon_hours=6` returns the same
footprints as GeoJSON, one feature per plume and band, each with
`model_version`, `degraded_reasons` and `experimental`.



### How the plume relates to the trained models

They are separate and answer different questions:


|                         | Plume                                   | `pm25_forecast`                                                 |
| ----------------------- | --------------------------------------- | --------------------------------------------------------------- |
| Question                | Where does smoke from this origin go?   | What PM2.5 will this station cell read in 1–24 h?               |
| Method                  | Lagrangian particles on forecast wind   | Quantile gradient boosting on features, or the persistence rule |
| Trained?                | No                                      | Yes, and served only after its gate passes                      |
| Output                  | Footprint cells, centre track, arrivals | µg/m³ with P10/P50/P90                                          |
| Changes with promotion? | No                                      | Yes                                                             |


Wind also feeds the forecast model as features, so both react to the same
weather, but neither uses the other's output. The `wind-advection-0.1` values
on `/map/forecast` before any cycle has run come from the worker's rule
forecast, not from the plume engine.

### Checking that plumes are working

After a live cycle:

```bash
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/plumes?region_id=in-north" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("total", d.get("total"), d.get("data_source"), d.get("field_status"))'
```


| What you see                                                                   | Meaning                                                                                   |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `no cycle has written a snapshot for in-north yet`                             | Run Step 1.                                                                               |
| `total 0` and `no fire cluster, open event, anomaly, or seeded citizen report` | Nothing to release from this hour. Correct, not a fault.                                  |
| `no forecast or observed wind for forward runs`                                | Open-Meteo did not deliver this cycle (often DNS). See Step 0.                            |
| `degraded_reasons` with `wind_uncertainty_unmeasured`                          | Fewer than 7 days of forecast-vs-observed wind pairs. Clears on its own as history grows. |
| `persisted_wind_after_<hour>`                                                  | The forecast ends before the last horizon; the last wind was held.                        |
| `left_wind_domain_<n>pct`                                                      | That share of particles left the source box; late horizons may be empty.                  |




## Live never shows Demo data: what was checked


| Area                            | Result                                                                                                                                                                                                                                                                                                                                |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend Demo/Live switch       | One switch, in `frontend/web/src/services/resolve.ts`. In Live every call goes to the API through `httpTransport`. A failed Live call is named in the banner and thrown; it never falls back to the recording. No page calls the API or the recording any other way.                                                                  |
| Copilot suggestions             | Read from the Demo recording only when `mode === 'demo'`.                                                                                                                                                                                                                                                                             |
| Forecast and hazard labels      | The UI shows `degraded` and its reason, and "rank" vs "probability" from `calibrated`.                                                                                                                                                                                                                                                |
| Plumes                          | Read from the Live snapshot only. With no snapshot the API answers `not_configured`; the UI never draws the recording's plumes in Live.                                                                                                                                                                                               |
| API map, events, risk, industry | In live mode with no snapshot: Timescale rows, else `not_configured` with a reason. Fixtures are served only in replay mode.                                                                                                                                                                                                          |
| API grid and hazard (fixed)     | `get_grid_reader` used to fall back to the in-memory Punjab replay episode whenever `grid_feature` was empty, **in either mode**, and `/map/hazard` had no `data_source`. In live mode it now returns empty with `data_source.kind = "not_configured"`, and every grid response states its source. Needs the `api` rebuild in Step 0. |
| Cycle                           | `--mode replay` writes under `replay-snapshots/` and never moves the Live pointer, so fixture snapshots cannot reach a Live view.                                                                                                                                                                                                     |


Run these checks yourself at any time:

```bash
python3 - <<'EOF'
import json, os, urllib.request
for path in ("map/hazard", "map/forecast", "models", "map/source-likelihood", "plumes"):
    req = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/{path}?region_id=in-north",
        headers={"Authorization": "Bearer " + os.environ["TOKEN"]},
    )
    body = json.load(urllib.request.urlopen(req, timeout=30))
    shown = {k: body[k] for k in ("data_source", "provenance", "field_status") if body.get(k)}
    print(f"{path:22} {json.dumps(shown)[:300]}")
EOF
```

Live is clean when no answer says `fixtures`, `replay` or `replay_episode`.
`not_configured` with a reason is a correct Live answer.

In the browser: the header says **Live**, and the footer clock is the wall
clock, not the recording's time.

## Keep it current

- Leave the hourly cycle loop running. It grows history, serves predictions
and runs plumes.
- Retrain on a schedule you choose (weekly, say) with the Step 2 command. Each
run gets a new `run_id` and `model_version`. Promote only by editing
`model_serving.yaml` and rebuilding.
- Re-run the monitor count in Step 0 now and then. More live reference
stations in OpenAQ means more labels; nothing in this repository changes
that.
- The `drift-monitor` service already runs `aeropulse-drift-monitor`. Drift is
a reason to retrain, not to change a gate.
- Renaming or changing a feature bumps `ML_FEATURE_VERSION`. Every promoted
entry is then refused at load (`feature version … differs from current`)
until you retrain. Run `uv run aeropulse-ml parity` after feature changes.



## Troubleshooting


| What you see                                                               | Cause and fix                                                                                                                         |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Sources: `openaq HEALTHY`, records `0`                                     | No monitor reported inside the staleness window, or the images predate the discovery fix. Rebuild (Step 0) and run the monitor count. |
| Sources: `[Errno -2] Name or service not known` on every live source       | Docker DNS. Reconnect the network, restart Docker Desktop or `dc restart connector`, and run the DNS check in Step 0.                 |
| Sources: `openaq` `401`                                                    | The key is rejected. Rotate it in `.env` and `dc up -d --force-recreate --no-deps connector`.                                         |
| Training: `no raw history under …/raw`                                     | No live cycle has run. Run Step 1.                                                                                                    |
| Training: `no labelled rows for this region`                               | No OpenAQ station records in history. Run Step 0, then collect again.                                                                 |
| `serving --strict`: `file not found`                                       | The entry points at the volume (`/app/var/...`), which only this laptop's containers see. Copy the run into `config/models/` (Step 4). |
| `serving --strict`: `in-north failed its gate`                             | The report says this region did not pass. Promotion cannot override that.                                                             |
| `serving --strict`: `SHA-256 … differs`                                    | The artifact was replaced after its gate report was written. Retrain; do not edit the hash.                                           |
| Cycle `served` still shows the rule version                                | The image was not rebuilt after the YAML edit, or the entry was refused. Check the cycle's stderr for `model_serving_entry_refused`.  |
| Models page: `listing model_serving.yaml entries that no cycle has loaded` | The API sees the entry, but no live cycle has written a snapshot since. Run one cycle.                                                |
| Plumes: none in Live                                                       | See "Checking that plumes are working".                                                                                               |
| UI shows the Punjab episode in Live                                        | The header is in Demo, or the API runs `AEROPULSE_CONNECTOR_MODE=replay`. See [local-live.md](local-live.md).                         |


