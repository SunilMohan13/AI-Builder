# Deploy to Google Cloud for the hackathon demo

> New to Google Cloud, or want the images built in Cloud Build instead of local
> Docker? Follow [deploy-google-cloud-step-by-step.md](deploy-google-cloud-step-by-step.md).

Both regions (North India and Singapore) cycling live every 15 minutes, the
trained models served, a public web page where judges can switch between
Demo and Live, and the ML Evaluation page filled in. Do the steps in order.

Before this page: train and promote the models on the laptop
([train-and-serve.md](train-and-serve.md),
[train-and-serve-singapore.md](train-and-serve-singapore.md)) and commit
`config/models/` and `config/model_serving.yaml`. The models travel inside the
app image; the year of laptop history is not uploaded and is not needed.

## Run this

The whole first deployment, from the repository root. Each step is explained
below under the same number; read those once before running this.

```bash
# 1. Shell (repeat the exports in every new terminal)
export PROJECT=project-56e4b7a1-10ef-4296-a08 LOCATION=asia-south1
export REG=$LOCATION-docker.pkg.dev/$PROJECT/aeropulse TAG=$(git rev-parse --short HEAD)
gcloud auth login && gcloud auth application-default login && gcloud config set project $PROJECT

# 2. Project (once)
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com \
  bigquery.googleapis.com storage.googleapis.com pubsub.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com iam.googleapis.com cloudresourcemanager.googleapis.com
gcloud artifacts repositories create aeropulse --repository-format=docker --location=$LOCATION
gcloud auth configure-docker $LOCATION-docker.pkg.dev
gcloud storage buckets create gs://$PROJECT-tfstate --location=$LOCATION --uniform-bucket-level-access

# 3. Images
docker buildx build --platform linux/amd64 -f infrastructure/docker/Dockerfile \
  --build-arg UV_EXTRAS="--extra gcp" -t $REG/app:$TAG --push .
docker buildx build --platform linux/amd64 -f frontend/web/Dockerfile.prod \
  -t $REG/web:bootstrap --push frontend/web

# 4. Settings (no secrets)
cat > infrastructure/gcp/hackathon.tfvars <<EOF
project_id = "$PROJECT"
location   = "$LOCATION"
app_image  = "$REG/app:$TAG"
web_image  = "$REG/web:bootstrap"
region_ids = ["in-north", "sg-singapore"]
EOF

# 5. Secrets: containers first, then values piped in without printing
terraform -chdir=infrastructure/gcp init \
  -backend-config="bucket=$PROJECT-tfstate" -backend-config="prefix=aeropulse"
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars -target=google_secret_manager_secret.app
grep '^AEROPULSE_OPENAQ_API_KEY=' infrastructure/docker/.env | cut -d= -f2- | tr -d '\n' \
  | gcloud secrets versions add aeropulse-openaq-api-key --data-file=-
grep '^AEROPULSE_FIRMS_MAP_KEY=' infrastructure/docker/.env | cut -d= -f2- | tr -d '\n' \
  | gcloud secrets versions add aeropulse-firms-map-key --data-file=-
openssl rand -base64 48 | tr -d '\n' | gcloud secrets versions add aeropulse-jwt-secret --data-file=-
openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add aeropulse-citizen-reporter-salt --data-file=-

# 6. Deploy
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars
export API_URL=$(terraform -chdir=infrastructure/gcp output -raw api_url)
export WEB_URL=$(terraform -chdir=infrastructure/gcp output -raw web_url)

# 7. Web image with the API address and the read-only demo token (never printed)
docker buildx build --platform linux/amd64 -f frontend/web/Dockerfile.prod \
  --build-arg VITE_API_BASE=$API_URL --build-arg VITE_DEFAULT_REGION=in-north \
  --build-arg VITE_API_TOKEN="$(AEROPULSE_JWT_SECRET="$(gcloud secrets versions access latest --secret=aeropulse-jwt-secret)" \
      uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('public-demo', [Role.VIEWER], ttl_seconds=14*86400, read_only=True))")" \
  -t $REG/web:$TAG --push frontend/web
sed -i '' "s#web:bootstrap#web:$TAG#" infrastructure/gcp/hackathon.tfvars
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars

# 8. Seed three days per region, then one live cycle each
for r in in-north sg-singapore; do
  gcloud run jobs execute aeropulse-cycle-$r --region $LOCATION --wait \
    --task-timeout=3600s --args=--region,$r,--mode,history,--days,3
  gcloud run jobs execute aeropulse-cycle-$r --region $LOCATION --wait
done

# 9. ML Evaluation page
AEROPULSE_PLATFORM=gcp AEROPULSE_GCP_PROJECT=$PROJECT AEROPULSE_BIGQUERY_DATASET=aeropulse \
  uv run --extra gcp aeropulse-ml load-eval

# 10. Check
curl -s $API_URL/health && echo && echo "open $WEB_URL"
```

## What gets created

Everything is in one Google Cloud region, `asia-south1` (Mumbai), the
Terraform default. To use another, change `LOCATION` and `location` in the
tfvars file together.

| Resource                                       | Role                                                                                 |
| ---------------------------------------------- | ------------------------------------------------------------------------------------ |
| Cloud Run service `aeropulse-api`              | The API. Public; every `/api/v1` route needs a token.                                |
| Cloud Run service `aeropulse-web`              | The UI, with the read-only demo token (step 7).                                      |
| Cloud Run service `aeropulse-citizen-analyzer` | Citizen photo analysis. Not public.                                                  |
| Cloud Run jobs `aeropulse-cycle-in-north`, `aeropulse-cycle-sg-singapore` | The live cycle per region, started by Cloud Scheduler every 15 minutes. |
| BigQuery datasets `aeropulse_*`, Cloud Storage buckets | The last days of raw data, snapshots, evaluation rows, citizen uploads. Persistent: a restart loses nothing. |
| Secret Manager secrets                         | OpenAQ key, FIRMS key, JWT secret, reporter salt. Terraform never holds the values.  |

Every service scales to zero, so an idle deployment costs little; the cycles
are what run all the time (step 11 pauses them).

This Terraform has been checked with `terraform validate` only and has not
been applied before. Expect small fixes on the first apply.

You need the `gcloud` CLI, Terraform 1.6 or newer, Docker with `buildx`, `uv`,
and a project with billing enabled.

## Step 1. Set up your shell

```bash
export PROJECT=project-56e4b7a1-10ef-4296-a08
export LOCATION=asia-south1
export REG=$LOCATION-docker.pkg.dev/$PROJECT/aeropulse
export TAG=$(git rev-parse --short HEAD)
gcloud auth login
gcloud auth application-default login
gcloud config set project $PROJECT
```

Set these again in every new terminal. Steps 7 and 9 also need `API_URL`
from step 6.

## Step 2. One-time project setup

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  secretmanager.googleapis.com bigquery.googleapis.com storage.googleapis.com \
  pubsub.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com \
  iam.googleapis.com cloudresourcemanager.googleapis.com
gcloud artifacts repositories create aeropulse --repository-format=docker --location=$LOCATION
gcloud auth configure-docker $LOCATION-docker.pkg.dev
gcloud storage buckets create gs://$PROJECT-tfstate --location=$LOCATION --uniform-bucket-level-access
```

## Step 3. Build and push the images

Cloud Run runs `linux/amd64`; on an Apple Silicon Mac `--platform` is
required. The app image copies `config/`, so it carries the promoted models
and `model_serving.yaml`.

```bash
docker buildx build --platform linux/amd64 -f infrastructure/docker/Dockerfile \
  --build-arg UV_EXTRAS="--extra gcp" -t $REG/app:$TAG --push .

# A first web image. The API address is not known until after the first apply.
docker buildx build --platform linux/amd64 -f frontend/web/Dockerfile.prod \
  -t $REG/web:bootstrap --push frontend/web
```

## Step 4. Write the settings file

`infrastructure/gcp/hackathon.tfvars` holds no secrets:

```bash
cat > infrastructure/gcp/hackathon.tfvars <<EOF
project_id = "$PROJECT"
location   = "$LOCATION"
app_image  = "$REG/app:$TAG"
web_image  = "$REG/web:bootstrap"
region_ids = ["in-north", "sg-singapore"]
EOF
```

`region_ids` creates one cycle job and one schedule per region. Leaving
`ml_image` out skips the cloud training job; the models are already in the
image.

## Step 5. Create the secrets, then add their values

The values come from your local `.env` or are generated, and go straight to
Secret Manager without being printed:

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

## Step 6. Deploy everything

```bash
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars
export API_URL=$(terraform -chdir=infrastructure/gcp output -raw api_url)
export WEB_URL=$(terraform -chdir=infrastructure/gcp output -raw web_url)
```

The API allows browser calls from `WEB_URL` only (CORS).

## Step 7. Rebuild the web image with the API address and a read-only demo token

Without a token, the cloud page shows Demo and Live says "not configured".
For judges to switch to Live, the bundle carries a token. Anyone who opens
the page can copy it, so it is limited:

- **Read-only.** The API refuses every write from it with
  `403 this demo token is read-only`: citizen reports and photo uploads,
  moderation, and source administration. It may still ask Ask AeroPulse and
  run a plume what-if, which change nothing (setting
  `AEROPULSE_READ_ONLY_ALLOWED_POSTS`). The API's limit of 600 requests per
  minute per client still applies.
- **Viewer role, subject `public-demo`, 14-day expiry.** Set `ttl_seconds` to
  cover your judging window.
- **Revocable.** Adding a new version of `aeropulse-jwt-secret` and
  redeploying the API invalidates it.

The token is minted inside the build command and never printed:

```bash
docker buildx build --platform linux/amd64 -f frontend/web/Dockerfile.prod \
  --build-arg VITE_API_BASE=$API_URL \
  --build-arg VITE_DEFAULT_REGION=in-north \
  --build-arg VITE_API_TOKEN="$(AEROPULSE_JWT_SECRET="$(gcloud secrets versions access latest --secret=aeropulse-jwt-secret)" \
      uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('public-demo', [Role.VIEWER], ttl_seconds=14*86400, read_only=True))")" \
  -t $REG/web:$TAG --push frontend/web
sed -i '' "s#web:bootstrap#web:$TAG#" infrastructure/gcp/hackathon.tfvars
terraform -chdir=infrastructure/gcp apply -var-file=hackathon.tfvars
```

On Linux, use `sed -i` without the `''`. The page opens in Demo; add
`--build-arg VITE_DEFAULT_DATA_MODE=live` to open in Live instead. Docker may
warn that a build argument looks like a secret: the token ends up in the
public JavaScript bundle by design, which is why it is read-only.

## Step 8. Seed both regions, then run the first cycles

The cloud starts with no raw history, so its first cycles would have no
station lags. Load three days per region once (the task timeout is raised for
this run only), then run one live cycle each to write the first snapshot:

```bash
for r in in-north sg-singapore; do
  gcloud run jobs execute aeropulse-cycle-$r --region $LOCATION --wait \
    --task-timeout=3600s --args=--region,$r,--mode,history,--days,3
  gcloud run jobs execute aeropulse-cycle-$r --region $LOCATION --wait
done
```

From then on Cloud Scheduler runs each region every 15 minutes.

## Step 9. Fill the ML Evaluation page

The evaluation rows of the trained runs were only written on the laptop. This
loads the `metrics.jsonl` of every run listed in `config/model_serving.yaml`
into BigQuery, using your `gcloud` login. Running it again adds nothing.

```bash
AEROPULSE_PLATFORM=gcp AEROPULSE_GCP_PROJECT=$PROJECT AEROPULSE_BIGQUERY_DATASET=aeropulse \
  uv run --extra gcp aeropulse-ml load-eval
```

It prints one line per run with its row count. Re-run it after shipping a
newly promoted model (step 12).

## Step 10. Check

```bash
curl -s $API_URL/health

CLOUD_TOKEN=$(AEROPULSE_JWT_SECRET="$(gcloud secrets versions access latest --secret=aeropulse-jwt-secret)" \
  uv run python -c "from aeropulse_auth import encode_token, Role; print(encode_token('check', [Role.VIEWER]))")
for r in in-north sg-singapore; do
  echo "== $r"
  curl -s -H "Authorization: Bearer $CLOUD_TOKEN" "$API_URL/api/v1/models?region_id=$r" \
    | python3 -c 'import json,sys; [print(m["family"], m["model_version"], "degraded" if m["degraded"] else "model", "cycle-verified" if m["verified_by_cycle"] else "NOT verified") for m in json.load(sys.stdin)["items"]]'
done
```

`CLOUD_TOKEN` is a one-hour viewer token held in a shell variable, never
printed or stored. Each family should say `cycle-verified`; `in-north` shows
the promoted versions from `model_serving.yaml`, the rest their rules, marked
degraded.

Then open `$WEB_URL` in a private browser window:

1. **Demo** works with no backend: North India (the Punjab episode) and
   Singapore (the October 2023 haze).
2. Switch the header to **Live**, pick **North India**: Data sources, map,
   Models and Forecast come from the cloud cycle.
3. **ML Evaluation** lists the promoted runs' metrics.
4. Pick **Singapore** in Live: see below.
5. Try to file a citizen report: it is refused with "this demo token is
   read-only". That is expected.

## What judges will see

| Where                       | What it shows                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Demo, either region         | The recorded cycle, with the promoted models on the Models page.                                                |
| Live, North India           | Live sources, the promoted forecast and hazard models with their versions. Hazard reads "rank" unless calibrated. When OpenAQ's reference monitors are late, Forecast shows "—" with "no ground station reported PM2.5 in the 24 h". |
| Live, Singapore             | Fires, wind, CAMS values marked model-derived, plumes. Forecast "—" with "no ground station reported PM2.5": no NEA station has reported to OpenAQ since January 2025. AQI "—" until the NEA bands are confirmed. These are the honest reasons, not errors. |
| Ask AeroPulse               | Answers from tool lookups, through Vertex AI with the service account.                                           |
| Citizen reports, moderation | Read-only: refused with 403.                                                                                     |

## Step 11. Pause to stop costs, and resume

```bash
for r in in-north sg-singapore; do
  gcloud scheduler jobs pause aeropulse-cycle-$r --location $LOCATION
done
```

Resume with `gcloud scheduler jobs resume …`, or set `scheduler_paused = true`
in the tfvars file and apply. Services scale to zero on their own. To delete
everything, run `terraform -chdir=infrastructure/gcp destroy -var-file=hackathon.tfvars`;
buckets and datasets that still hold data are kept by design and must be
emptied first.

## Step 12. Day-to-day

| Task                        | Command                                                                                                                       |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Recent cycle runs           | `gcloud run jobs executions list --job aeropulse-cycle-in-north --region $LOCATION --limit 5`                                  |
| Cycle logs                  | `gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="aeropulse-cycle-in-north"' --limit 50`     |
| Run one cycle now           | `gcloud run jobs execute aeropulse-cycle-sg-singapore --region $LOCATION`                                                      |
| Ship a newly promoted model | Promote on the laptop and commit, then step 3 (first command) with a new `TAG`, set `app_image` in the tfvars file, step 6, step 9 |
| Roll back a model           | Remove its entry from `model_serving.yaml`, then ship as above. The rule answers again, marked degraded.                       |
| Renew the demo token        | `export TAG=$(git rev-parse --short HEAD)-$(date +%s)`, then step 7. A new tag is what makes Terraform roll the web service.  |
| Revoke the demo token       | Add a new JWT secret version (the `openssl rand -base64 48` line in step 5), then start new revisions: `gcloud run services update aeropulse-api --region $LOCATION --update-labels=jwt=$(date +%s)`, and the same for `aeropulse-citizen-analyzer`. Then renew the token as above. |

## Troubleshooting

| What you see                                         | Fix                                                                                                    |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| A service fails to deploy with a secret error        | That secret has no version yet. Re-run its line in step 5.                                             |
| `exec format error` in Cloud Run logs                | The image was built for ARM. Rebuild with `--platform linux/amd64` (step 3).                           |
| The browser reports a CORS error                     | The web build points at another API. Re-run step 7 with the current `API_URL`.                         |
| Live says "demo token expired"                       | The token's 14 days are over. Renew it (step 12).                                                      |
| Live says "Invalid token (401)"                      | The JWT secret was rotated after the web build. Renew the token (step 12).                             |
| Live in the cloud says "not configured"              | The web image was built without `VITE_API_TOKEN` (the bootstrap image). Run step 7.                    |
| A citizen report says "this demo token is read-only" | Expected for the public page.                                                                          |
| ML Evaluation is empty                               | Run step 9.                                                                                            |
| Models say `NOT verified`                            | No cycle has finished since the deploy. Run step 8's second command for that region.                   |
| A cycle execution fails with "Memory limit exceeded" or a timeout | Read its logs (step 12). The limits are `resources.limits` and `cycle_timeout_seconds` in `infrastructure/gcp/run.tf` and `variables.tf`. |
| Singapore Forecast is "—" with the no-station reason | Expected: no NEA station reports to OpenAQ now. The model is not the problem.                          |
