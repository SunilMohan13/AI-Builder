# Singapore: load history, train, serve, and show it in the UI

The same pipeline as North India ([train-and-serve.md](train-and-serve.md)),
run for `sg-singapore`. This page lists every command with the Singapore values
and says where Singapore differs. Do the steps in order.

## Run this

From the repository root, with the Live stack from
[local-live.md](local-live.md) set up. The history is kept in the laptop
project folder `aeropulse-data/` (see "Where the history lives" in
[train-and-serve.md](train-and-serve.md)). Step numbers match the sections
below.

```bash
alias dc='docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml'
export TOKEN=$(grep '^AEROPULSE_WEB_TOKEN=' infrastructure/docker/.env | cut -d= -f2-)

# What is already loaded? If sg-singapore air_quality openaq already spans
# 2022-10-22 to 2025-01-07, skip Step 2.
uv run python scripts/history.py status

dc build connector cycle api && dc up -d --no-deps connector api

# 2. Station window history (overnight), then check and back it up
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
uv run python scripts/history.py status
uv run python scripts/history.py save

# 3. Train forecast (hazard and anomaly only after Step 1), then back up the run
dc run --rm cycle uv run aeropulse-ml train --family pm25_forecast \
  --dataset parquet:///app/var/aeropulse/analytics --regions sg-singapore \
  --out /app/var/aeropulse/models/runs --load-eval \
  --start=2022-10-22T00:00Z --end=2025-01-08T00:00Z
uv run python scripts/history.py save

# 4. Which runs passed: the command in Step 4
# 5. Copy each PASSED run, then add its entry to config/model_serving.yaml (Step 5)
mkdir -p config/models/sg-singapore && cp -r aeropulse-data/models/runs/pm25_forecast-20261013T025029Z config/models/sg-singapore/

# 6. Check, rebuild, one Singapore live cycle (after hh:15, see "Live stations")
uv run aeropulse-ml serving --strict
uv run ruff check . && uv run pytest tests/unit tests/contract -q
dc build connector cycle api && dc up -d --no-deps connector api
dc run --rm cycle uv run aeropulse-cycle --region sg-singapore --mode live

# 7. Re-record Demo
uv run python scripts/generate_demo_recording.py

# 8. Commit (Step 8); 9. Google Cloud: deploy-google-cloud.md
```

## Live stations: NEA, not OpenAQ

Training history comes from OpenAQ, but OpenAQ's Singapore feed stopped in
January 2025. Live readings come from the `nea` source, which reads NEA's hourly
PM2.5 on data.gov.sg (`https://api-open.data.gov.sg/v2/real-time/api/pm25`).
No key is needed. Both sources are listed in `ground_truth_sources` in
`config/regions/sg-singapore/region.yaml`.

- **Same stations as training.** NEA publishes one reading for each of five
  regions (north, south, east, west, central) at a fixed label point. OpenAQ's
  Singapore history is the same readings at the same points, so both land in
  the same five cells.
- **Same timestamps as training.** OpenAQ stamps each reading one hour after
  NEA's timestamp. The connector does the same, so the hour a value is known
  matches between training and serving. NEA publishes about 15 minutes past
  the hour. A reading whose shifted stamp is still in the future is skipped,
  and the next cycle picks it up.
- **Run the cycle after hh:15.** Before that, the current hour has no reading,
  so the forecast's `pm25` input is one hour older.
- **Without NEA, Forecast is empty and says why.** The forecast only scores
  cells with a station reading in the last 24 hours. When `nea` reports zero
  records, the page shows "no ground station reported PM2.5" instead of a
  number. Check the source on the Sources page.
- **Do not backfill NEA over the OpenAQ years.** The two would give duplicate
  readings for the same cell and hour. If you ever switch history to NEA,
  remove `openaq` from `ground_truth_sources` first.

## Evidence can be empty and correct

Evidence lists incidents: an active pollution event, or a fire or anomaly whose
plume reaches a place in `config/regions/sg-singapore/gazetteer.parquet`.
Smoke from Sumatra and Kalimantan often stays south of Singapore within the
48-hour plume run. When no plume reaches a place and no event is active,
"No open incidents" is the honest answer. Under that heading, the page shows
the counts behind it from the latest cycle, in the form
"no pollution event is active (`<n> detected`); `<k>` of `<m>` plumes reached a
place in the gazetteer".

