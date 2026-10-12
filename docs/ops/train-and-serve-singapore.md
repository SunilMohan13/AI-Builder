# Singapore: load history, train, serve, and show it in the UI

The same pipeline as North India ([train-and-serve.md](train-and-serve.md)),
run for `sg-singapore`. This page lists every command with the Singapore values
and says where Singapore differs. Do the steps in order.

## Read this first: what Singapore can show today

Checked on 12 Oct 2026 against OpenAQ, for the island box in
`config/regions/sg-singapore/region.yaml`:

| Reference-grade PM2.5 monitor (`monitor=true`)         | OpenAQ ids    | Provider | Reported               |
| ------------------------------------------------------ | ------------- | -------- | ---------------------- |
| NEA regions: Central, West, North, East, South         | 367925–367929 | AirNow   | 22 Oct 2022 – 7 Jan 2025 |
| SPARTAN – NUS                                          | 1285352       | SPARTAN  | Apr 2016 – Jan 2020    |

No reference monitor in Singapore has reported to OpenAQ since 7 Jan 2025.
About 20 low-cost AirGradient sensors report live, but the pack keeps OpenAQ to
reference monitors (`monitor_only: true`), and that is deliberate: see "Should
low-cost sensors become labels?" in
[train-and-serve-reference.md](train-and-serve-reference.md).

What follows from that:

| Family              | Can it be trained?                                                                                        | What Live shows after promotion                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `pm25_forecast`     | Yes, on the NEA station history, 22 Oct 2022 – 7 Jan 2025.                                                 | The **Models** page lists it. Forecast shows "—" with the reason "no ground station reported PM2.5 in the 24 h". |
| `pm25_hazard_24h`   | Only after Step 1. Until then training stops with "AQI standard unconfirmed: no hazard threshold, so no hazard label". | "—" with "the region's AQI standard is unconfirmed, so it has no hazard threshold". After Step 1, its rule, marked degraded. |
| `anomaly`           | Same as hazard: its gate is scored against the hazard label.                                               | The threshold rule, marked degraded.                                                                             |
| `source_likelihood` | Never trained. A heuristic ranking with evidence.                                                          | The ranking, labelled heuristic.                                                                                 |

What Singapore shows in the UI regardless of models, once a live cycle has run
(Step 6): the region in the header with its cycle time, Data sources, fires and
wind over the whole source domain (Sumatra, Borneo, the Malay peninsula),
Open-Meteo CAMS values marked model-derived, Sentinel-5P aerosol index, and
smoke plumes. AQI labels show "—" with "NEA band table not yet confirmed"
until Step 1.

**Demo** shows Singapore during the October 2023 haze: one real cycle at
11:00 Singapore time on 7 October 2023, replayed from committed fixtures
(Step 7).

## Before you start

Same as North India: the Live stack running, keys in
`infrastructure/docker/.env`, and in every new terminal:

```bash
alias dc='docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml'
export TOKEN=$(grep '^AEROPULSE_WEB_TOKEN=' infrastructure/docker/.env | cut -d= -f2-)
```

Rebuild once, so the cycle has the history fixes (rasters stamped with their
own chunk time, and the memory-safe history read):

```bash
dc build connector cycle api
dc up -d --no-deps connector api
```

Stop the hourly North India loop while Steps 2 and 3 run, so two 4 GB
containers do not compete for memory.

## Step 0. Check the station data yourself (2 minutes)

Coverage changes with OpenAQ, not with this repository. This reads the key
from `.env` without printing it, and the box from the region pack:

```bash
set -a; . infrastructure/docker/.env; set +a
uv run python - <<'EOF'
import json, os, urllib.parse, urllib.request
from pathlib import Path
from aeropulse_regions import load_catalog

bbox = load_catalog(Path("config")).get("sg-singapore").geometry.bbox
key = {"X-API-Key": os.environ["AEROPULSE_OPENAQ_API_KEY"]}

def get(path, **params):
    url = f"https://api.openaq.org/v3/{path}?" + urllib.parse.urlencode(params)
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=key), timeout=30))

for loc in get("locations", bbox=",".join(map(str, bbox)), parameters_id=2, monitor="true", limit=100)["results"]:
    first = (loc.get("datetimeFirst") or {}).get("utc")
    last = (loc.get("datetimeLast") or {}).get("utc")
    print(loc["id"], loc["name"], loc["provider"]["name"], first, "->", last)
    for sensor in get(f"locations/{loc['id']}/sensors")["results"]:
        if sensor["parameter"]["name"] == "pm25" and last:
            hours = get(f"sensors/{sensor['id']}/hours", datetime_from="2024-06-01T00:00:00Z",
                        datetime_to="2024-07-01T00:00:00Z", limit=1000)["results"]
            print("   June 2024 hourly PM2.5 values:", len(hours))
EOF
```

Expect the table above. If a monitor now reports within the last few hours,
Live forecasts will start to appear for it on their own after Step 6.

## Step 1. Confirm the NEA standard (only for hazard and anomaly)

Skip this step if you only want the forecast model.

`config/aqi_standards/sg_nea.yaml` ships `status: unconfirmed` with no bands.
That is why Singapore AQI labels show "—" and why there is no hazard label.
The project rule: bands are copied from the official NEA publication with a
second person checking, never typed from memory, and never borrowed from
another country.

1. Open NEA's published PM2.5 bands and note the page address.
2. Replace the file with the published values. The shape is fixed; every
   `<...>` comes from the NEA page:

   ```yaml
   schema_version: aqi_standard.v1
   key: sg_nea
   name: Singapore NEA
   pollutant: pm25
   unit: ug/m3
   status: confirmed
   averaging: <"1h" or "24h", as NEA defines the bands>
   source_url: <the NEA page>
   bands:
     - { key: <band key>, label: <NEA label>, low: 0.0, high: <NEA value> }
     # one line per NEA band; each band's high is the next band's low
     - { key: <top band key>, label: <NEA label>, low: <NEA value>, high: null }
   hazard_label: <the band key your team treats as hazardous>
   hazard_threshold_ugm3: <a value inside that band, usually its lower bound>
   hazard_source: <one line: which NEA band and why>
   ```

3. Validate. The loader refuses gaps between bands, an open bottom, and a
   threshold outside its band:

   ```bash
   uv run aeropulse-region validate
   ```

4. Run the tests. These expect Singapore's standard to be unconfirmed and
   must be updated in the same change: `tests/unit/test_region_packs.py`
   (`aqi_for("sg-singapore").status`, `test_unconfirmed_standard_classifies_nothing`,
   `test_unconfirmed_standard_cannot_carry_bands`) and
   `tests/unit/test_feature_pipeline_v3.py::test_unconfirmed_standard_has_no_threshold_and_no_hazard_label`.
   Point them at a standard that is still unconfirmed (`au_nsw_aqc`,
   region `au-nsw`). Also update
   `tests/unit/test_cycle.py::test_a_region_with_an_unconfirmed_standard_says_why_hazard_is_empty`
   and the empty-hazard assertion in `tests/golden/test_demo_recording.py`,
   then re-record Demo (Step 7): Singapore's Demo hazard layer will then be
   scored.

   ```bash
   uv run pytest tests/unit tests/contract tests/golden -q
   ```

Outside haze episodes Singapore's PM2.5 rarely crosses a high band, so the
hazard label will have few positives and its gate may fail. That is a real
result; do not lower the gate.

## Step 2. Load the Singapore history (run it overnight)

The station history is 22 Oct 2022 – 7 Jan 2025, so load that window. One run
per quarter, so a failure costs a quarter. Use 10-day chunks: fires are fetched
over the whole source domain (95–120 E), and the burning season (August to
October) can be large.

```bash
for w in 2022-10-22T00:00Z,2023-01-01T00:00Z 2023-01-01T00:00Z,2023-04-01T00:00Z \
         2023-04-01T00:00Z,2023-07-01T00:00Z 2023-07-01T00:00Z,2023-10-01T00:00Z \
         2023-10-01T00:00Z,2024-01-01T00:00Z 2024-01-01T00:00Z,2024-04-01T00:00Z \
         2024-04-01T00:00Z,2024-07-01T00:00Z 2024-07-01T00:00Z,2024-10-01T00:00Z \
         2024-10-01T00:00Z,2025-01-08T00:00Z; do
  s=${w%,*}; e=${w#*,}
  caffeinate -i docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml \
    run --rm cycle uv run aeropulse-cycle --region sg-singapore --mode history \
    --start="$s" --end="$e" --chunk-days 10
done
```

In a test on 12 Oct 2026, one day (1 June 2024) took about 2 minutes and
returned: `openaq` 120 records (five stations × 24 hours), `openmeteo` 12,000,
`firms` 24, `earthengine` 60, all `healthy`. In every chunk line, check that
`sources.openaq.records` is above zero and every source says `healthy`.

If a quarter ends with exit code `137` and no JSON line, it ran out of memory:
re-run that quarter with `--chunk-days 5`. Re-running is always safe; the same
records replace themselves.

Check what loaded, Singapore only:

```bash
dc run --rm -T cycle uv run python -c "
import glob, re
import pandas as pd
src = re.compile('\"source_id\": *\"([^\"]+)\"')
parts = []
for f in glob.glob('/app/var/aeropulse/analytics/raw/air_quality/sg-singapore_*.parquet'):
    d = pd.read_parquet(f, columns=['known_at', 'record'])
    d['source'] = [src.search(r).group(1) for r in d['record']]
    parts.append(d.groupby('source')['known_at'].agg(['size', 'min', 'max']))
print(pd.concat(parts).groupby(level=0).agg({'size': 'sum', 'min': 'min', 'max': 'max'}).to_string())
"
```

The `openaq` row should run from 22 Oct 2022 to 7 Jan 2025.

## Step 3. Train

Forecast, on the whole station window:

```bash
dc run --rm cycle uv run aeropulse-ml train --family pm25_forecast \
  --dataset parquet:///app/var/aeropulse/analytics --regions sg-singapore \
  --out /app/var/aeropulse/models/runs --load-eval \
  --start=2022-10-22T00:00Z --end=2025-01-08T00:00Z
```

Hazard and anomaly, only after Step 1 (and a rebuild, `dc build cycle`, so the
image has the new standard):

```bash
for f in pm25_hazard_24h anomaly; do
  dc run --rm cycle uv run aeropulse-ml train --family $f \
    --dataset parquet:///app/var/aeropulse/analytics --regions sg-singapore \
    --out /app/var/aeropulse/models/runs --load-eval \
    --start=2022-10-22T00:00Z --end=2025-01-08T00:00Z
done
```

If a run ends with exit code `137`, raise `AEROPULSE_CYCLE_MEM_LIMIT=6g` in
`.env`, or shorten the window with a later `--start`.

## Step 4. See which Singapore runs passed

```bash
dc run --rm -T cycle uv run python -c "
import glob, json
for path in sorted(glob.glob('/app/var/aeropulse/models/runs/*/gate.json')):
    g = json.load(open(path))
    for r in g['regions']:
        if r['region_id'] != 'sg-singapore':
            continue
        verdict = 'PASSED' if r['passed'] and g['servable'] else 'failed'
        print(f\"{g['run_id']:38} {g['model_version']:30} calibrated={str(r['calibrated']):5} {verdict:7} {'; '.join(r['failures'])[:150]}\")
"
```

Only `PASSED` runs can be served. The failure reasons are explained in Step 4
of [train-and-serve.md](train-and-serve.md).

## Step 5. Put the passed models in the repo

Copy each passed run into `config/models/sg-singapore/`, replacing `<run_id>`:

```bash
dc run --rm -v "$PWD/config/models:/out" cycle \
  sh -c 'mkdir -p /out/sg-singapore && cp -r /app/var/aeropulse/models/runs/<run_id> /out/sg-singapore/'
```

Add one entry per passed family to `config/model_serving.yaml`, below the
North India entries. Values come from Step 4:

```yaml
  - family: pm25_forecast
    region_id: sg-singapore
    model_version: <model_version from Step 4>
    artifact_uri: config/models/sg-singapore/<run_id>/model.joblib
    gate_report_uri: config/models/sg-singapore/<run_id>/gate.json
    calibrated: <calibrated from Step 4>
```

The loader refuses an entry whose region did not pass in that gate report,
whose file hash differs, or that claims `calibrated: true` without the report.

## Step 6. Serve it and check the UI

**6.1 Check the serving file.**

```bash
uv run aeropulse-ml serving --strict
uv run ruff check . && uv run pytest tests/unit tests/contract -q
```

`refused` must be `[]`, and `served.sg-singapore` lists your version.

**6.2 Rebuild and run one Singapore live cycle.** Images copy `config/` at
build time.

```bash
dc build cycle api
dc up -d --no-deps api
dc run --rm cycle uv run aeropulse-cycle --region sg-singapore --mode live
```

`served.pm25_forecast` should be your version.

**6.3 Check the API.**

```bash
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/models?region_id=sg-singapore" \
  | python3 -c 'import json,sys; [print(m["family"], m["model_version"], "degraded" if m["degraded"] else "model", m.get("degraded_reason") or "", "cycle-verified" if m["verified_by_cycle"] else "NOT verified") for m in json.load(sys.stdin)["items"]]'

for p in regions/sg-singapore map/fire map/weather map/forecast map/hazard plumes; do
  printf '%-22s ' $p
  curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/$p?region_id=sg-singapore" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d.get("features", d.get("items", d.get("sources", [])))), json.dumps(d.get("field_status") or "")[:140])'
done
```

Each family says `cycle-verified`. Empty forecast and hazard layers carry the
reason "no ground station reported PM2.5 in the 24 h …".

**6.4 Check the UI.** Open <http://127.0.0.1:5173>, keep the header on
**Live**, and pick **Singapore** in the region menu.

- The menu shows Singapore without "— no cycle yet".
- **Data sources**: openaq, firms, openmeteo and earthengine with their
  records and last success.
- **Command Centre**: the map opens on the island; fires, wind and plumes
  cover the source domain.
- **Models**: forecast shows your version; hazard and anomaly show their
  rules, degraded, with the reason.
- **Forecast**: "—" with the no-station reason while no NEA station reports.

**6.5 Run both regions every hour.**

```bash
while true; do
  for r in in-north sg-singapore; do
    dc run --rm -T cycle uv run aeropulse-cycle --region $r --mode live
  done
  sleep 3600
done
```

## Step 7. Singapore in Demo

Demo is a recording made by `scripts/generate_demo_recording.py`. It runs the
real live cycle for every region whose pack names a `demo.cycle_time`, at that
hour, with each fetch answered from that region's committed fixtures. Each
region is recorded at its own clock, ten minutes after its cycle.

Singapore's Demo hour is `2023-10-07T03:00:00Z` (11:00 in Singapore), set in
`config/regions/sg-singapore/region.yaml`. It was chosen from the data: in
September–October 2023 it is the hour with the highest mean NEA PM2.5 with all
five regional stations reporting. Its fixtures are verbatim upstream payloads:

| File                                 | What it holds                                                          |
| ------------------------------------ | ---------------------------------------------------------------------- |
| `fixtures/openaq/sg-singapore.json`    | The five NEA monitors and their hourly PM2.5 for the 48 h before the hour |
| `fixtures/firms/sg-singapore.json`     | VIIRS NOAA-20 and SNPP detections over the source domain, previous 24 h  |
| `fixtures/openmeteo/sg-singapore.json` | CAMS air quality and weather for the pack's 60 wind sites                |

There is no Earth Engine fixture, as for North India, so Data sources shows
it as not configured. Hazard shows "—" with the reason that the NEA standard
is unconfirmed.

To capture again, at the same or another hour (keys come from `.env` and are
never printed):

```bash
set -a; . infrastructure/docker/.env; set +a
uv run python scripts/capture_demo_fixtures.py --region sg-singapore --at 2023-10-07T03:00Z
```

Put the `demo.cycle_time` it prints in the pack, then re-record and check:

```bash
uv run python scripts/generate_demo_recording.py
uv run pytest tests/golden/test_demo_recording.py -q
```

In the UI, switch the header to **Demo** and pick **Singapore**.

## Step 8. Commit

```bash
git add config/models/sg-singapore config/model_serving.yaml
git add config/aqi_standards/sg_nea.yaml     # only if you did Step 1
git add config/regions/sg-singapore fixtures/*/sg-singapore.json frontend/web/src/data/regions
git status --short                           # no .env or env.txt may be listed
git commit -m "Promote Singapore models trained on NEA station history"
```

## Step 9. Google Cloud

The models ship inside the app image, so nothing else is uploaded. In
`infrastructure/gcp/hackathon.tfvars` add the region, so it gets its own cycle
job and schedule. Then ship as in the "Ship a newly promoted model" row of
[train-and-serve.md](train-and-serve.md): 8.3 with a new `TAG`, set
`app_image`, and re-run 8.6.

```hcl
region_ids = ["in-north", "sg-singapore"]
```

Run its first cycle and check it:

```bash
gcloud run jobs execute aeropulse-cycle-sg-singapore --region $LOCATION --wait
curl -s -H "Authorization: Bearer $CLOUD_TOKEN" "$API_URL/api/v1/models?region_id=sg-singapore"
```

## Adding any other place

Singapore and North India are two region packs over the same code. For a new
place:

1. Scaffold the pack (every bbox is a setting to confirm):

   ```bash
   uv run aeropulse-region init xx-place --display-name "..." --country XX \
     --timezone Area/City --aqi-standard <key> --bbox min_lon,min_lat,max_lon,max_lat \
     --source-domain min_lon,min_lat,max_lon,max_lat --hazards urban_pollution
   ```

2. Add `config/aqi_standards/<key>.yaml`: `status: unconfirmed` until the
   official bands are copied and checked (Step 1 above).
3. Run Step 0 with the new region id. **Reference monitors with hourly history
   decide everything:** without them nothing can be trained, and the region
   serves its rules, marked degraded.
4. `uv run aeropulse-region validate`, rebuild, then Steps 2–6 with the new
   region id and its station window.
5. For Demo, pick an hour when its stations reported and run Step 7 with the
   new region id. Add the printed `fixture:` lines and `demo.cycle_time` to its
   pack.

## Troubleshooting

| What you see                                                                 | Fix                                                                                         |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sources.openaq.records` is 0 in a history chunk                             | The window is outside 22 Oct 2022 – 7 Jan 2025, or OpenAQ changed. Re-run Step 0.            |
| Training: `AQI standard unconfirmed: no hazard threshold, so no hazard label` | Expected for hazard and anomaly until Step 1.                                               |
| Training: `no labelled rows for this region in the dataset`                   | No Singapore station history loaded. Check Step 2.                                          |
| Live Forecast: "no ground station reported PM2.5 in the 24 h"                 | Expected: no NEA station reports to OpenAQ now. The model is loaded; nothing to score.     |
| AQI shows "—" with "NEA band table not yet confirmed"                         | Expected until Step 1.                                                                     |
| Demo shows Singapore "Not configured"                                         | The pack has no `demo.cycle_time`, or the frontend was built before Step 7. Re-record and rebuild the web image. |
| Anything else                                                                 | The North India table in [train-and-serve.md](train-and-serve.md) applies to both regions. |
