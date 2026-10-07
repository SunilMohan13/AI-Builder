# Operations runbook

How to run, onboard, deploy and recover AeroPulse APAC. Architecture is in
[../architecture.md](../architecture.md); training and promotion in
[../ml/training-and-promotion.md](../ml/training-and-promotion.md).

## Local stack (Docker Compose)

```bash
cp .env.example .env            # then set AEROPULSE_JWT_SECRET to a random value
docker compose --env-file .env -f infrastructure/docker/compose.yaml up --build
```

| Service | Role |
|---|---|
| `cycle` | One replay cycle per region at the fixtures' capture hour (2026-09-08 06:00 UTC), then exits. in-north has fixtures; regions without fixtures report every source as `not_configured` with zero cells. |
| `api` | Serves snapshots from the shared `aeropulse-data` volume, read per request. |
| `citizen-analyzer` | Photo analysis. Backend network only, no host port. |
| `web` | Vite dev server on `127.0.0.1:5173`. Demo needs no API; Live needs `AEROPULSE_WEB_TOKEN`. |

A live cycle (keys come from `.env`; a missing key is "not configured", never a fixture):

```bash
docker compose --env-file .env -f infrastructure/docker/compose.yaml \
  run --rm cycle uv run aeropulse-cycle --region all --mode live
```

Without Docker: `uv run aeropulse-cycle --region in-north --mode replay --cycle-time 2026-09-08T06:00Z`,
then `uv run aeropulse-api`.

## Onboarding a region (configuration only)

No code changes. `tests/unit/test_fourth_region.py` runs this path end to end.

1. Scaffold the pack and its wind sites:

   ```bash
   uv run aeropulse-region init xx-name --display-name "..." --country XX \
     --timezone Area/City --aqi-standard <key> --bbox min_lon,min_lat,max_lon,max_lat \
     --hazards urban_pollution
   ```

2. Add or reuse `config/aqi_standards/<key>.yaml`. Copy bands from the official source
   with two-person review; until then use `status: unconfirmed` and `bands: []`, and the
   UI shows "—" with the reason instead of borrowing another country's scale.
3. Add hazard profiles, gazetteer and population settings as the pack needs.
4. For an offline demo, record replay fixtures and add `fixture:` to each source entry.
5. `uv run aeropulse-region validate`, then run one cycle for the region and check
   `GET /api/v1/regions/<id>`.
6. On Google Cloud, add the id to `region_ids` in the Terraform variables: that creates
   its cycle job and schedule.

Models are not promoted for a new region until it passes its own gate; until then its
rules answer with `degraded=true`.

## Deploying to Google Cloud

Terraform is in `infrastructure/gcp/`. It holds no secret values.

1. Build and push the images (Artifact Registry or any registry the project can pull):

   ```bash
   docker build -f infrastructure/docker/Dockerfile --build-arg UV_EXTRAS="--extra gcp" -t <app_image> .
   docker build -f infrastructure/docker/Dockerfile.ml --build-arg UV_EXTRAS="--extra gcp" -t <ml_image> .
   ```

2. Create the secret containers first, then add their values out of band:

   ```bash
   cd infrastructure/gcp
   terraform init -backend-config="bucket=<state bucket>" -backend-config="prefix=aeropulse"
   terraform apply -var-file=<env>.tfvars -target=google_secret_manager_secret.app
   printf '%s' "$VALUE" | gcloud secrets versions add aeropulse-jwt-secret --data-file=-
   # likewise aeropulse-citizen-reporter-salt, aeropulse-openaq-api-key, aeropulse-firms-map-key
   ```

   Cloud Run refuses to deploy a service whose secret has no version.
3. Apply everything: `terraform apply -var-file=<env>.tfvars`. The `api_url` output is
   the API's address.
4. Build the web image against that address and roll the web service:

   ```bash
   docker build -f frontend/web/Dockerfile.prod --build-arg VITE_API_BASE=<api_url> -t <web_image> frontend/web
   ```

   No API token is baked into the bundle, so the cloud web serves Demo, and Live
   reports "not configured" until sign-in exists (OIDC is later).
5. Register the project for Earth Engine before relying on that source; until then the
   cycle reports it as not configured.

## Day-two operations

| Task | How |
|---|---|
| Pause all cycles (cost kill switch) | `scheduler_paused = true`, then apply; or `gcloud scheduler jobs pause aeropulse-cycle-<region>` |
| Run one cycle now | `gcloud run jobs execute aeropulse-cycle-<region> --region <location>` |
| Why is a source empty? | `GET /api/v1/sources` and the snapshot's `source_health`: `not_configured` names the missing key; nothing is substituted |
| Failed photo analyses | `gcloud pubsub subscriptions pull citizen-reports-dlq-inspect --limit 10` (after 5 delivery attempts) |
| Roll back a model | Revert its entry in `config/model_serving.yaml` and deploy; the rule answers with `degraded=true` |
| Check what would be served | `uv run aeropulse-ml serving --strict` |
| Rotate the JWT secret | Add a new version of `aeropulse-jwt-secret`, then deploy a new revision of the API and the citizen analyzer; existing tokens stop verifying |

## Known limits

- `aero.alerts` exists with publisher grants, but nothing publishes to it yet; alerts are
  written to `ops.alerts` in BigQuery by the cycle.
- The citizen analyzer accepts traffic from all networks but no public invoker: only
  `sa-push` and `sa-api` may call it. Internal-only ingress would also need VPC egress
  for the API.
- The cycle job does not run with `AEROPULSE_ENVIRONMENT=production`: that setting
  requires the JWT secret, which the cycle never uses and is not given.
- No billing budget is created by Terraform; set one on the billing account.
- The Terraform has been checked with `terraform validate` only, not applied.
