# Run Live on this laptop (Docker)

Live is the map reading this machine's stack. Demo is the scripted episode and
does not need Docker. This page is only the Live path. To train a model on the
live history and serve it, continue with [train-and-serve.md](train-and-serve.md).

The file Compose must be given is [infrastructure/docker/.env](../../infrastructure/docker/.env).
It is gitignored. Do not commit it, and do not paste its values into a ticket.

## What that file controls

| Variable | Live value | If it is missing or empty |
| --- | --- | --- |
| `AEROPULSE_JWT_SECRET` | A random local secret, at least 32 bytes | The API container refuses to start |
| `AEROPULSE_WEB_TOKEN` | A viewer JWT signed with that secret | The Live control stays disabled and says there is no token |
| `AEROPULSE_CONNECTOR_MODE` | `live` | The connector replays fixtures, and an empty database can show those fixtures |
| `AEROPULSE_UI_MODE` | `live` | The map opens in Demo. You can still switch the header after a token exists |
| `AEROPULSE_OPENAQ_API_KEY` | Your OpenAQ key | OpenAQ reports not configured and sends nothing |
| `AEROPULSE_FIRMS_MAP_KEY` | Your NASA FIRMS map key | FIRMS reports not configured and sends nothing |
| `AEROPULSE_GEMINI_API_KEY` | Your Gemini key | Ask AeroPulse answers from stored lookups and says the model was not used |
| `AEROPULSE_GEMINI_MODEL` | `gemini-3.8-flash` unless you change it | The copilot uses that default |
| `AEROPULSE_EARTHENGINE_PROJECT` | A Google Cloud project registered for Earth Engine | Satellite sources that need Earth Engine stay not configured |
| `AEROPULSE_GCLOUD_CONFIG_DIR` | Empty (uses `~/.config/gcloud`) | Earth Engine finds no Google credentials and stays not configured |
| `AEROPULSE_CITIZEN_REPORTER_SALT` | Optional on this laptop | Development uses a process-local salt. Set a random value before any other environment |
| `AEROPULSE_PLATFORM` | `local` | Leave this. `gcp` is the cloud path |
| `AEROPULSE_DEFAULT_REGION` | `in-north` | The map and API open the India north pack |
| `AEROPULSE_DATABASE_URL` | `127.0.0.1:5433` | Only for tools on the host. Containers use the Compose network address |
| `AEROPULSE_REDIS_URL` | `127.0.0.1:6380` | Same: host tools only |
| `AEROPULSE_KAFKA_BOOTSTRAP_SERVERS` | `127.0.0.1:19092` | Same: host tools only |

Open-Meteo needs no key. Weather and CAMS-derived air quality can run live
without one. IMD stays off; Open-Meteo already covers those weather sites.

GCP project, bucket, and BigQuery variables can stay empty for this laptop.

## One-time preparation

1. Docker Desktop is running.
2. From the repository root, the env file already has the Live switches and a
   viewer token. If you rotate `AEROPULSE_JWT_SECRET`, mint a new token with
   the same secret and put it in `AEROPULSE_WEB_TOKEN`:

   ```bash
   set -a
   source infrastructure/docker/.env
   set +a
   uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('web', [Role.VIEWER], ttl_seconds=604800))"
   ```

   The token lasts seven days. It is a development HS256 viewer token. The
   browser bundle can read it. Do not reuse it anywhere but this laptop.
3. Confirm the three Live switches without printing secrets:

   ```bash
   awk -F= '/^AEROPULSE_(CONNECTOR_MODE|UI_MODE)=/{print} /^AEROPULSE_WEB_TOKEN=/{print ($2=="" ? "AEROPULSE_WEB_TOKEN=empty" : "AEROPULSE_WEB_TOKEN=set")}' infrastructure/docker/.env
   ```

   You want `live`, `live`, and `set`.

## Start the stack

From the repository root:

```bash
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml up --build
```

The first start builds images and can take several minutes. Wait until `api`
is healthy.

| Open | URL |
| --- | --- |
| Map | http://127.0.0.1:5173 |
| API docs | http://127.0.0.1:8000/docs |
| API health | http://127.0.0.1:8000/health |

The header should say **Live**. Demo is still one click away. Live numbers
come only from this stack. A missing field is "—" with a reason. A failed
Live call is named. Demo numbers are not filled in.

## What has to be up

| Service | What it does for Live |
| --- | --- |
| `connector` | Pulls Open-Meteo, and OpenAQ or FIRMS when those keys are set. Publishes canonical rows to Redpanda. |
| `worker` | Checks rows, places them on the 1 km grid, runs the rules, and writes Timescale. |
| `api` | Reads Timescale. With `AEROPULSE_CONNECTOR_MODE=live` it does not serve fixture files when the database is empty. |
| `web` | Vite on port 5173. `VITE_API_TOKEN` and `VITE_DEFAULT_DATA_MODE` come from this env file at process start. |
| `timescaledb` | Host port 5433. |
| `redpanda` | Host port 19092. |
| `redis` | API response cache only. Host port 6380. |
| `minio` | Raw archive. Host ports 9000 and 9001. |

`cycle` is a one-shot job. Its Compose command replays the saved 2026-09-08
fixtures into a replay snapshot, which is kept separate from Live snapshots.
It does not replace the connector. For a Live snapshot of the region pack,
after the stack is healthy:

```bash
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml \
  run --rm cycle uv run aeropulse-cycle --region in-north --mode live
```

A source with no key reports not configured and writes zero records. That is
the correct Live result.

## Turn on Earth Engine (Sentinel-5P aerosol index)

The `earthengine` source needs three things. A missing one shows as
not configured on the Data sources page, with the reason.

1. `AEROPULSE_EARTHENGINE_PROJECT` in the env file: a Google Cloud project
   with `earthengine.googleapis.com` enabled **and registered for Earth
   Engine** (Cloud Console, Earth Engine, Configuration; choose noncommercial
   use if that applies). Enabling the API is not registration: an unregistered
   project fails with `403 PERMISSION_DENIED` and "is not registered to use
   Earth Engine", and the source reports unavailable.
2. The Earth Engine client in the `cycle` image. Compose builds `cycle` with
   `--extra earthengine`, so rebuilding `cycle` is enough.
3. Google Application Default Credentials on this Mac. The `cycle` container
   mounts `~/.config/gcloud` read-only (set `AEROPULSE_GCLOUD_CONFIG_DIR` to
   use another folder). Create them once; a browser window opens:

```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/earthengine,https://www.googleapis.com/auth/cloud-platform
```

Then set the billing/quota project for those credentials to the same project:

```bash
gcloud auth application-default set-quota-project YOUR_EARTHENGINE_PROJECT
```

Rebuild and run one live cycle:

```bash
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml build cycle
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml \
  run --rm cycle uv run aeropulse-cycle --region in-north --mode live
```

`sources.earthengine` in the printed line should be `healthy`. The source
reads yesterday's daily aerosol index for each wind-site cell, so its records
change once a day, not every hour. A cloudy cell is reported as missing, not
zero.

## Why CPCB says not configured

`cpcb` is replay only: there is no live CPCB code path, because CPCB
publishes no free API that this build uses. In Live it correctly reports
`cpcb has no live API` with zero records. CPCB station values still arrive
live through OpenAQ, whose reference monitors in India are the CPCB network,
usually days late. A direct feed (for example the data.gov.in real-time AQI
API, which needs its own key) would be a new connector, not a setting.

## Check that Live is real

1. Header says Live, not Demo.
2. `GET http://127.0.0.1:8000/health` returns ok.
3. Source health (paste the viewer token only into this local call):

   ```bash
   curl -s -H "Authorization: Bearer $AEROPULSE_WEB_TOKEN" \
     http://127.0.0.1:8000/api/v1/sources
   ```

   Open-Meteo should be live. OpenAQ and FIRMS follow their keys. A source
   you did not configure says not configured.
4. The map may be sparse for a minute or two while the connector and worker
   finish a cycle. Empty cells are gaps, not Demo filler.
5. Hazard or peak values marked degraded are the persistence rule. `0.80` is
   a rank until the screen says it is calibrated.

## After you change the env file

Vite reads `VITE_*` when the web process starts. The API reads
`AEROPULSE_CONNECTOR_MODE` when it starts. Recreate both after any edit:

```bash
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml up -d --force-recreate --no-deps api web connector
```

## Stop

```bash
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml down
```

`down` keeps the database volume. `down -v` deletes it, and the next start
has no stored rows until the connector runs again.

## If Live is not what you expected

| What you see | What to do |
| --- | --- |
| Header says Demo | `AEROPULSE_UI_MODE` is not `live`, or the web container was not recreated after the edit |
| Live control disabled, "no token" | `AEROPULSE_WEB_TOKEN` is empty, or the web container started before it was set |
| Live calls return 401 | The token was signed with a different `AEROPULSE_JWT_SECRET` than the API is using. Mint again and recreate `api` and `web` |
| Live looks like the scripted Punjab episode | The UI is still Demo, or the API is still in `replay`. Confirm both the header and `AEROPULSE_CONNECTOR_MODE=live` inside the API container |
| A source is empty | That is Live. Check `/api/v1/sources` for not configured or a zero count |
| Ask AeroPulse did not use Gemini | The key is missing, or Google returned an error. The answer from stored evidence is intentional |
| Port already in use | Something else holds 5173, 8000, 5433, 6380, 19092, or 9000 |

To see the mode the connector actually started with:

```bash
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml logs connector | head
```
