# Train every model on a year of data, serve it, and deploy to Google Cloud

A runbook. Do the steps in order; each one says what to run, what you should
see, and what to do if you don't. The reasons behind each limit, the plume, and
the Live-vs-Demo checks are in
[train-and-serve-reference.md](train-and-serve-reference.md).

This page is for North India (`in-north`). For Singapore, and for adding any
other place, see [train-and-serve-singapore.md](train-and-serve-singapore.md).

## What you end up with

| Family              | Trained on    | What to expect                                                                                              |
| ------------------- | ------------- | ----------------------------------------------------------------------------------------------------------- |
| `pm25_forecast`     | last 60 days  | Already passes and is served (`hgbq-forecast-202610101116`). Retraining is optional.                        |
| `pm25_hazard_24h`   | the full year | Can pass once the winter episodes are in. On 60 days it failed narrowly. Not guaranteed.                    |
| `anomaly`           | the full year | Unlikely to pass: on 60 days its F1 was 0.175 against the rule's 0.346.                                     |
| `source_likelihood` | not trained   | Always a heuristic ranking with evidence, never a model and never a percentage (see `AGENTS.md`).           |

A family whose gate fails still shows in the UI: its deterministic rule
answers, labelled `degraded` with the reason. That is a correct result. Do not
lower a gate to make it pass.

How a model reaches the screen:

1. A history load and the hourly live cycles write raw data to the
   `aeropulse-data` volume.
2. `aeropulse-ml train` builds features, evaluates against baselines, and
   writes `model.joblib` and `gate.json`. It never changes what is served.
3. You copy a run that passed into `config/models/` and list it in
   `config/model_serving.yaml`.
4. After a rebuild, each live cycle loads the listed models, predicts, and
   writes a Live snapshot.
5. The API serves that snapshot; the Live UI shows it with the model version.

## Before you start

You need:

- The Live stack from [local-live.md](local-live.md) running, with these set in
  `infrastructure/docker/.env`: `AEROPULSE_CONNECTOR_MODE=live`,
  `AEROPULSE_UI_MODE=live`, `AEROPULSE_OPENAQ_API_KEY`,
  `AEROPULSE_FIRMS_MAP_KEY` and `AEROPULSE_WEB_TOKEN`.
- Docker Desktop with at least 8 GB of memory. The cycle container is capped at
  4 GB (`AEROPULSE_CYCLE_MEM_LIMIT`, default `4g`).
- `uv` on the host, for the checks and tests.

In every new terminal, from the repository root:

```bash
alias dc='docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml'
export TOKEN=$(grep '^AEROPULSE_WEB_TOKEN=' infrastructure/docker/.env | cut -d= -f2-)
```

The second line reads your local API token without printing it.

If the hourly cycle loop (Step 6.6) is already running, stop it with `Ctrl-C`
for Steps 2 and 3, so two 4 GB containers do not compete for memory.

## Step 1. Rebuild with the latest code

```bash
dc build connector cycle api
dc up -d --no-deps connector api
```

The `cycle` image carries the history loader, the Open-Meteo archive switch
and the FIRMS archive switch. A container started before this rebuild still
runs the old code.

## Step 2. Load one year of history (about 2 hours)

Four runs, one per quarter, so a failure costs a quarter and not the year.
`caffeinate -i` keeps the Mac awake.

```bash
for w in 2025-10-01T00:00Z,2026-01-01T00:00Z 2026-01-01T00:00Z,2026-04-01T00:00Z \
         2026-04-01T00:00Z,2026-07-01T00:00Z 2026-07-01T00:00Z,; do
  s=${w%,*}; e=${w#*,}
  caffeinate -i docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml \
    run --rm cycle uv run aeropulse-cycle --region in-north --mode history \
    --start="$s" ${e:+--end=$e} --chunk-days 30
done
```

Each 30-day chunk prints one JSON line when it is stored. In each line:

- `sources.openaq.records` is above zero. This is the station data that becomes
  labels.
- `sources.openmeteo` and `sources.firms` say `healthy`. `not_configured` for
  `cpcb` and `earthengine` is expected.

If a quarter ends with exit code `137` and no JSON line, Docker killed it for
memory. Re-run only that quarter with `--chunk-days 10`. Re-running is always
safe: repeated records are dropped before training.

Check what loaded:

```bash
dc run --rm -T cycle uv run python -c "
import glob, re
import pandas as pd
src = re.compile('\"source_id\": *\"([^\"]+)\"')
parts = []
for f in glob.glob('/app/var/aeropulse/analytics/raw/air_quality/*.parquet'):
    d = pd.read_parquet(f, columns=['known_at', 'record'])
    d['source'] = [src.search(r).group(1) for r in d['record']]
    parts.append(d.groupby('source')['known_at'].agg(['size', 'min', 'max']))
print(pd.concat(parts).groupby(level=0).agg({'size': 'sum', 'min': 'min', 'max': 'max'}).to_string())
"
```

It reads one file at a time, so a year of history fits in memory.

The `openaq` row should span from late 2025 to now. (When checked on
11 Oct 2026, OpenAQ's hourly archive reached back to at least November 2025.)

## Step 3. Train every family

Hazard and anomaly use the whole year. Forecast uses the last 60 days: it has
five rows per station-hour (one per horizon), so a year of it does not fit in
4 GB, and it already passes on 60 days.

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

On Linux, use `date -u -d '60 days ago' +%Y-%m-%dT00:00Z`. Forecast took about
4 minutes on 60 days; hazard and anomaly on a year take longer.

Each run prints a JSON summary. For a family that passed, it also prints a YAML
snippet on stderr; you will use it in Step 5.

If a run ends with exit code `137` and no summary, it ran out of memory. Either
raise `AEROPULSE_CYCLE_MEM_LIMIT=6g` in `.env` (Docker Desktop needs the room),
or train on a shorter window with `--start`.

`source_likelihood` is not trained: it stays a heuristic.

## Step 4. See which models passed

```bash
dc run --rm -T cycle uv run python -c "
import glob, json
for path in sorted(glob.glob('/app/var/aeropulse/models/runs/*/gate.json')):
    g = json.load(open(path))
    for r in g['regions']:
        verdict = 'PASSED' if r['passed'] and g['servable'] else 'failed'
        print(f\"{g['run_id']:38} {g['model_version']:30} calibrated={str(r['calibrated']):5} {verdict:7} {'; '.join(r['failures'])[:150]}\")
"
```

One line per run. Only `PASSED` runs can be served. A `failed` line lists the
reasons, for example:

| Reason                                                         | Meaning                                                                     |
| -------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `no labelled rows for this region in the dataset`              | No OpenAQ station history. Check Step 2.                                    |
| `N evaluated folds (need 3)`                                   | The history is too short for the time-based evaluation.                     |
| `RMSE skill vs persistence is -0.0123 (must exceed 0)`         | Forecast is no better than "the value now". A real result; the rule stays.  |
| `P10-P90 coverage is 0.55 (must reach 0.7)`                    | Forecast intervals are too narrow to trust.                                 |
| `PR-AUC margin vs already_above is -0.0387 ...`                | Hazard did not beat that baseline by the required margin.                   |
| `false-alert rate is 0.1026 at the operating point ...`        | Hazard raises too many false alerts.                                        |
| `detection F1 against the hazard label is ... (must reach 0.3)` | Anomaly is not good enough to replace the threshold rule.                  |

## Step 5. Put the passed models in the repo

A run on the Docker volume exists only on this laptop. Tests, CI and the
Google Cloud image can only see what is in the repository.

**5.1 Copy each passed run** (about 2.5 MB each), replacing `<run_id>`:

```bash
dc run --rm -v "$PWD/config/models:/out" cycle \
  sh -c 'mkdir -p /out/in-north && cp -r /app/var/aeropulse/models/runs/<run_id> /out/in-north/'
```

**5.2 List it in `config/model_serving.yaml`.** One entry per family and
region. Take `model_version` and `calibrated` from Step 4 (or the snippet from
Step 3), and point both paths into `config/models/`:

```yaml
schema_version: model_serving.v1
entries:
  - family: pm25_forecast
    region_id: in-north
    model_version: hgbq-forecast-202610101116
    artifact_uri: config/models/in-north/pm25_forecast-20261010T111652Z/model.joblib
    gate_report_uri: config/models/in-north/pm25_forecast-20261010T111652Z/gate.json
    calibrated: false
  - family: pm25_hazard_24h          # only if its run PASSED
    region_id: in-north
    model_version: <model_version from Step 4>
    artifact_uri: config/models/in-north/<run_id>/model.joblib
    gate_report_uri: config/models/in-north/<run_id>/gate.json
    calibrated: <calibrated from Step 4>
```

Rules the loader enforces, so an entry can never serve something it should not:

- The region must have passed in that `gate.json`.
- The file's SHA-256 must match the one the gate report pins. Never edit it.
- `calibrated: true` is refused unless the gate report says so.
- If you retrained forecast and it passed, replace its entry rather than adding
  a second one, and delete the old run folder.

## Step 6. Test locally

**6.1 Check the serving file.**

```bash
uv run aeropulse-ml serving --strict
```

`refused` must be `[]`. Under `served.in-north`, each family you listed shows
your `model_version` and `"degraded": false`; the others show their rule,
`degraded: true`, with a reason. If something is refused, the reason names the
failed check.

**6.2 Run the checks and tests.**

```bash
uv run ruff check .
uv run pytest tests/unit tests/contract -q
```

`tests/unit/test_ml_serving.py` reads `model_serving.yaml` and fails if any
entry is refused.

**6.3 Rebuild and run one live cycle.** Images copy `config/` at build time,
so a YAML edit does nothing until you rebuild.

```bash
dc build cycle api
dc up -d --no-deps api
dc run --rm cycle uv run aeropulse-cycle --region in-north --mode live
```

In the JSON it prints, `served` maps each family to the version that answered:
`hgbq-…` for the models you promoted, rule versions (such as
`persistence-forecast-1.0`) for the rest.

**6.4 Check the API.**

```bash
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/models?region_id=in-north" \
  | python3 -c 'import json,sys; [print(m["family"], m["model_version"], "degraded" if m["degraded"] else "model", m.get("degraded_reason") or "", "cycle-verified" if m["verified_by_cycle"] else "NOT verified") for m in json.load(sys.stdin)["items"]]'
```

Each family should say `cycle-verified`. `NOT verified` means no live cycle
has run since the rebuild; repeat 6.3.

Confirm that Live serves live data and nothing from Demo or replay:

```bash
for p in map/forecast map/hazard models plumes; do
  printf '%-14s ' $p
  curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/$p?region_id=in-north" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get("data_source"))[:160])'
done
```

No line may mention `fixtures`, `replay` or `replay_episode`.
`not_configured` with a reason is a correct Live answer.

**6.5 Check the UI.** Open <http://127.0.0.1:5173>.

- The header says **Live**, and the clock is the wall clock.
- **Models**: one row per family. Promoted families show their `hgbq-…`
  version; the others show the rule, marked degraded with the reason.
- **Forecast**: the model line shows the version. Hazard reads "rank" unless
  its entry is calibrated.
- **Command Centre**: forecast, hazard, wind and plume layers from the latest
  cycle.

**6.6 Refresh the Demo recording.** Demo replays a recording, not the API, so
it keeps showing the old rules until you re-record it with the new YAML:

```bash
uv run python scripts/generate_demo_recording.py
uv run python scripts/generate_demo_recording.py --check   # exit 0 = up to date
(cd frontend/web && npm run build)
```

Switch the header to **Demo**: the **Models** page now lists the promoted
versions. Rebuild the web image (`dc build web && dc up -d --no-deps web`) to
serve the new recording.

**6.7 Keep the hourly loop running.** It grows history, serves predictions and
runs plumes:

```bash
while true; do
  dc run --rm -T cycle uv run aeropulse-cycle --region in-north --mode live
  sleep 3600
done
```

## Step 7. Commit

Add paths explicitly. Never use `git add -A`: `infrastructure/docker/.env` and
`infrastructure/docker/env.txt` hold your keys (both are git-ignored).

```bash
git add config/models config/model_serving.yaml frontend/web/src/data/regions
git status --short     # check that no .env or env.txt is listed
git commit -m "Promote models trained on one year of in-north history"
```

Commit the code changes the same way.

## Step 8. Deploy to Google Cloud, in one region

Everything goes into one Google Cloud region: `asia-south1` (Mumbai), the
Terraform default and the closest to `in-north`. The container registry, Cloud
Run, BigQuery, buckets and Scheduler all use it. To use another region, change
`LOCATION` below and `location` in the tfvars file together.

What gets created (`infrastructure/gcp/`):

| Resource                                         | Role                                                                                |
| ------------------------------------------------ | ----------------------------------------------------------------------------------- |
| Cloud Run service `aeropulse-api`                | The API. Public, every `/api/v1` route needs a token.                               |
| Cloud Run service `aeropulse-web`                | The UI.                                                                             |
| Cloud Run service `aeropulse-citizen-analyzer`   | Citizen photo analysis. Not public.                                                 |
| Cloud Run job `aeropulse-cycle-<region>`         | The live cycle, started by Cloud Scheduler every 15 minutes (`cycle_schedule`).     |
| BigQuery datasets, Cloud Storage buckets         | Raw history, snapshots, citizen uploads.                                            |
| Secret Manager secrets                           | OpenAQ key, FIRMS key, JWT secret, reporter salt. Terraform never holds the values. |

The promoted models ship **inside the app image**, because the image copies
`config/`. No model upload is needed, and the same `model_serving.yaml` serves
in the cloud.

This Terraform has been checked with `terraform validate` only and has not
been applied before (see [runbook.md](runbook.md)). Expect to fix small issues
on the first apply.

You need: the `gcloud` CLI, Terraform 1.6 or newer, Docker with `buildx`, and a
project with billing enabled.

**8.1 Set up your shell.**

```bash
export PROJECT=<your-project-id>
export LOCATION=asia-south1
export REG=$LOCATION-docker.pkg.dev/$PROJECT/aeropulse
export TAG=$(git rev-parse --short HEAD)
gcloud auth login
gcloud auth application-default login
gcloud config set project $PROJECT
```

**8.2 One-time project setup.**

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  secretmanager.googleapis.com bigquery.googleapis.com storage.googleapis.com \
  pubsub.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com \
  iam.googleapis.com cloudresourcemanager.googleapis.com
gcloud artifacts repositories create aeropulse --repository-format=docker --location=$LOCATION
gcloud auth configure-docker $LOCATION-docker.pkg.dev
gcloud storage buckets create gs://$PROJECT-tfstate --location=$LOCATION --uniform-bucket-level-access
```

**8.3 Build and push the images.** Cloud Run runs `linux/amd64`; on an Apple
Silicon Mac the `--platform` flag is required.

```bash
docker buildx build --platform linux/amd64 -f infrastructure/docker/Dockerfile \
  --build-arg UV_EXTRAS="--extra gcp" -t $REG/app:$TAG --push .

# A first web image. The API address is not known until after the first apply.
docker buildx build --platform linux/amd64 -f frontend/web/Dockerfile.prod \
  -t $REG/web:bootstrap --push frontend/web
```

**8.4 Write the settings file** `infrastructure/gcp/hackathon.tfvars`. It holds
no secrets.

```bash
cat > infrastructure/gcp/hackathon.tfvars <<EOF
project_id = "$PROJECT"
location   = "$LOCATION"
app_image  = "$REG/app:$TAG"
web_image  = "$REG/web:bootstrap"
region_ids = ["in-north"]
EOF
```

`region_ids` decides which regions get a cycle job. Only `in-north` has trained
models; add `"sg-singapore", "au-nsw"` to serve their rules too. Leaving
`ml_image` out skips the cloud training job, which you do not need because the
models are already in the image.

**8.5 Create the secrets, then add their values.** Values come from your local
`.env` or are generated, and are piped straight to Secret Manager without being
printed.

```bash
terraform -chdir=infrastructure/gcp init \
  -backend-config="bucket=$PROJECT-tfstate" -backend-config="prefix=aeropulse"
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars \
  -target=google_secret_manager_secret.app

grep '^AEROPULSE_OPENAQ_API_KEY=' infrastructure/docker/.env | cut -d= -f2- | tr -d '\n' \
  | gcloud secrets versions add aeropulse-openaq-api-key --data-file=-
grep '^AEROPULSE_FIRMS_MAP_KEY=' infrastructure/docker/.env | cut -d= -f2- | tr -d '\n' \
  | gcloud secrets versions add aeropulse-firms-map-key --data-file=-
openssl rand -base64 48 | tr -d '\n' | gcloud secrets versions add aeropulse-jwt-secret --data-file=-
openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add aeropulse-citizen-reporter-salt --data-file=-
```

Cloud Run refuses to deploy a service whose secret has no version.

**8.6 Deploy everything.**

```bash
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars
export API_URL=$(terraform -chdir=infrastructure/gcp output -raw api_url)
export WEB_URL=$(terraform -chdir=infrastructure/gcp output -raw web_url)
```

**8.7 Rebuild the web image with the API address and roll it out.**

```bash
docker buildx build --platform linux/amd64 -f frontend/web/Dockerfile.prod \
  --build-arg VITE_API_BASE=$API_URL -t $REG/web:$TAG --push frontend/web
sed -i '' "s#web:bootstrap#web:$TAG#" infrastructure/gcp/hackathon.tfvars
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars
```

**8.8 Seed the cloud history and run the first cycle.** The cloud starts with
no raw history, so its first cycles would have no station lags. Load three days
once (the task timeout is raised because the default is 10 minutes), then run
one live cycle to write the first snapshot:

```bash
gcloud run jobs execute aeropulse-cycle-in-north --region $LOCATION --wait \
  --task-timeout=3600s --args=--region,in-north,--mode,history,--days,3
gcloud run jobs execute aeropulse-cycle-in-north --region $LOCATION --wait
```

From then on Cloud Scheduler runs a cycle every 15 minutes.

**8.9 Verify.**

```bash
curl -s $API_URL/health

CLOUD_TOKEN=$(AEROPULSE_JWT_SECRET="$(gcloud secrets versions access latest --secret=aeropulse-jwt-secret)" \
  uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('check', [Role.VIEWER]))")
curl -s -H "Authorization: Bearer $CLOUD_TOKEN" "$API_URL/api/v1/models?region_id=in-north" \
  | python3 -c 'import json,sys; [print(m["family"], m["model_version"], "degraded" if m["degraded"] else "model", "cycle-verified" if m["verified_by_cycle"] else "NOT verified") for m in json.load(sys.stdin)["items"]]'
```

You should see the same families and versions as in Step 6.4, all
`cycle-verified`. The token is a one-hour viewer token held in a shell
variable; it is never printed or stored.

Open `$WEB_URL` in a browser. Demo works with no backend.

**What the cloud UI shows in Live.** The cloud web image bakes in no API
token, because a token inside a public JavaScript bundle is readable by anyone
who opens the page. So the cloud UI opens in Demo, and switching to Live shows
"not configured" until sign-in exists (OIDC is planned for later). For a demo
of Live models, use the local stack (Step 6.5), and use 8.9 to show that the
cloud API serves the same models.

**Logs and day-to-day operations:**

| Task                      | Command                                                                                                                   |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Recent cycle runs         | `gcloud run jobs executions list --job aeropulse-cycle-in-north --region $LOCATION --limit 5`                              |
| Cycle logs                | `gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="aeropulse-cycle-in-north"' --limit 50` |
| Run one cycle now         | `gcloud run jobs execute aeropulse-cycle-in-north --region $LOCATION`                                                      |
| Pause cycles (stop costs) | `gcloud scheduler jobs pause aeropulse-cycle-in-north --location $LOCATION`                                                |
| Ship a newly promoted model | Steps 4–7 locally, then 8.3 (first command) with a new `TAG`, set `app_image` in the tfvars file, and re-run 8.6        |
| Roll back a model         | Remove its entry from `model_serving.yaml`, then ship as above. The rule answers again, marked degraded.                  |

## Troubleshooting

| What you see                                                     | Fix                                                                                                                      |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| A history or training run ends with exit `137` and no JSON       | Out of memory. History: `--chunk-days 10`. Training: `AEROPULSE_CYCLE_MEM_LIMIT=6g`, or a shorter `--start`.              |
| `sources.openaq` is `HEALTHY` with 0 records                     | Rebuild (Step 1). In history mode, check the window is not in the future.                                                |
| `[Errno -2] Name or service not known` on every source           | Docker DNS. Reconnect the network, restart Docker Desktop, then `dc restart connector`.                                  |
| `openaq` `401`                                                   | The key is rejected. Fix it in `.env`, then `dc up -d --force-recreate --no-deps connector`.                              |
| Training: `no raw history under …/raw`                           | Run Step 2 first.                                                                                                        |
| `serving --strict`: `file not found`                             | The path is not under `config/models/`, or the run was not copied (Step 5.1).                                            |
| `serving --strict`: `in-north failed its gate`                   | That run did not pass. Promotion cannot override a gate.                                                                 |
| `serving --strict`: `SHA-256 … differs`                          | The file changed after training. Copy it again from the volume, or retrain. Never edit the hash.                         |
| `serving --strict`: `feature version … differs`                  | The features changed since that run. Retrain.                                                                            |
| Live header shows "— no cycle yet"; Data sources are all "—"     | No live cycle has finished for the region. Run one (Step 6.3); exit `137` there means it ran out of memory.               |
| Forecast and hazard: "no ground station reported PM2.5 in the 24 h" | OpenAQ's reference monitors are late (see the reference doc). The models are loaded; there is no station row to score.  |
| The cycle's `served` still shows the rule version                | The image was not rebuilt after the YAML edit (Step 6.3), or the entry was refused: look for `model_serving_entry_refused`. |
| Models page: `entries that no cycle has loaded`                  | No live cycle since the rebuild. Run one (Step 6.3).                                                                     |
| The Live UI shows the Punjab Demo episode                        | The header is set to Demo, or `AEROPULSE_CONNECTOR_MODE` is `replay`. See [local-live.md](local-live.md).                |
| Cloud: a service fails to deploy with a secret error             | That secret has no version yet. Re-run its line in 8.5.                                                                  |
| Cloud: `exec format error` in Cloud Run logs                     | The image was built for ARM. Rebuild with `--platform linux/amd64` (8.3).                                                |
| Cloud: the browser reports a CORS error                          | The web build points at the wrong API. Re-run 8.7 with the current `API_URL`.                                            |
