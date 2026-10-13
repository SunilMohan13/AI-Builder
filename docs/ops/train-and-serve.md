# Train every model on a year of data and serve it

A runbook. Do the steps in order; each one says what to run, what you should
see, and what to do if you don't. The reasons behind each limit, the plume, and
the Live-vs-Demo checks are in
[train-and-serve-reference.md](train-and-serve-reference.md). Deploying to
Google Cloud is [deploy-google-cloud.md](deploy-google-cloud.md).

This page is for North India (`in-north`). For Singapore, and for adding any
other place, see [train-and-serve-singapore.md](train-and-serve-singapore.md).

## Run this

From the repository root, with the Live stack from
[local-live.md](local-live.md) set up. The step numbers match the sections
below.

```bash
alias dc='docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml'
export TOKEN=$(grep '^AEROPULSE_WEB_TOKEN=' infrastructure/docker/.env | cut -d= -f2-)

# 0. What is already loaded? If the year is there, skip to Step 3 (or Step 6).
uv run python scripts/history.py status

# 1. Rebuild
dc build connector cycle api && dc up -d --no-deps connector api

# 2. One year of history (about 2 hours), then check and back it up
for w in 2025-10-01T00:00Z,2026-01-01T00:00Z 2026-01-01T00:00Z,2026-04-01T00:00Z \
         2026-04-01T00:00Z,2026-07-01T00:00Z 2026-07-01T00:00Z,; do
  s=${w%,*}; e=${w#*,}
  caffeinate -i docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml \
    run --rm cycle uv run aeropulse-cycle --region in-north --mode history \
    --start="$s" ${e:+--end=$e} --chunk-days 30
done
uv run python scripts/history.py status
uv run python scripts/history.py save

# 3. Train, then back up the runs
for f in pm25_hazard_24h anomaly; do
  dc run --rm cycle uv run aeropulse-ml train --family $f \
    --dataset parquet:///app/var/aeropulse/analytics --regions in-north \
    --out /app/var/aeropulse/models/runs --load-eval
done
dc run --rm cycle uv run aeropulse-ml train --family pm25_forecast \
  --dataset parquet:///app/var/aeropulse/analytics --regions in-north \
  --out /app/var/aeropulse/models/runs --load-eval --start "$(date -u -v-60d +%Y-%m-%dT00:00Z)"
uv run python scripts/history.py save

# 4. Which runs passed: the command in Step 4
# 5. Copy each PASSED run, then edit config/model_serving.yaml by hand (Step 5.2)
mkdir -p config/models/in-north && cp -r aeropulse-data/models/runs/<run_id> config/models/in-north/

# 6. Check, rebuild, one live cycle, re-record Demo
uv run aeropulse-ml serving --strict
uv run ruff check . && uv run pytest tests/unit tests/contract -q
dc build cycle api && dc up -d --no-deps api
dc run --rm cycle uv run aeropulse-cycle --region in-north --mode live
uv run python scripts/generate_demo_recording.py

# 7. Commit (Step 7); 8. Google Cloud: deploy-google-cloud.md
```

After a restore, or on a fresh `aeropulse-data/` folder, refill the local ML
Evaluation page without retraining:
`AEROPULSE_DATA_DIR=aeropulse-data uv run aeropulse-ml load-eval`.

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

1. A history load and the hourly live cycles write raw data to the project
   folder `aeropulse-data/` (see "Where the history lives" below).
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

If the hourly cycle loop (Step 6.7) is already running, stop it with `Ctrl-C`
for Steps 2 and 3, so two 4 GB containers do not compete for memory.

## Where the history lives

Everything lives in the project, next to `config/`:

| Folder                 | Holds                                                     | In git        |
| ---------------------- | --------------------------------------------------------- | ------------- |
| `aeropulse-data/`      | The raw history, the trained runs, the snapshots (GBs)    | No (ignored)  |
| `aeropulse-backups/`   | Dated archives of that folder from `history.py save`      | No (ignored)  |
| `config/models/`       | The runs you promote (Step 5), a few MB each              | Yes           |

The `api`, `cycle` and `citizen-analyzer` containers mount `aeropulse-data/`
at `/app/var/aeropulse`, so every `/app/var/aeropulse/...` path below is that
folder, and you can open it in Finder. Shutting the laptop down, `dc down -v`,
`docker volume prune` and a Docker Desktop reset do not touch it. Both folders
are also left out of the Docker build context, so builds stay fast. To keep the
data somewhere else, set an absolute path in `AEROPULSE_HOST_DATA_DIR` in
`infrastructure/docker/.env`; `history.py` reads the same setting.

**Once, if you loaded history before this change**, it is still in the old
Docker volume `aeropulse_aeropulse-data`. Copy it into the folder:

```bash
dc down
uv run python scripts/history.py migrate
uv run python scripts/history.py status
dc up -d
```

`migrate` copies into an empty folder only. If a container already started
with the new mount and wrote into the folder, move that folder aside first
(`mv aeropulse-data /tmp/aeropulse-data.new`). Once `status` shows your
history, the command `migrate` prints removes the old volume.

On Linux, give the container user the folder first:
`mkdir -p aeropulse-data && sudo chown -R 10001 aeropulse-data`.

**Back it up** after each history load and each training run. Archives skip
the raw provider responses (`objects/raw`, large and not needed to train);
add `--with-raw` to keep them.

```bash
uv run python scripts/history.py save      # aeropulse-backups/aeropulse-data-<UTC>.tar.gz
```

**Put a backup back** (a new laptop, or the folder was deleted). The current
folder is moved aside, not deleted:

```bash
dc down
uv run python scripts/history.py restore aeropulse-backups/aeropulse-data-<UTC>.tar.gz
dc up -d
```

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

Check what loaded, then back it up:

```bash
uv run python scripts/history.py status
uv run python scripts/history.py save
```

`status` reads the folder directly (no Docker), one file at a time. It prints
one line per region, table and source with the row count and the first and
last time. The `in-north air_quality openaq` line should span from late 2025
to now. (When checked on 11 Oct 2026, OpenAQ's hourly archive reached back to
at least November 2025.)

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
snippet on stderr; you will use it in Step 5. Back up the new runs with
`uv run python scripts/history.py save`.

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

A run in `aeropulse-data/` exists only on this laptop: the folder is not in git. Tests, CI and the
Google Cloud image can only see what is in the repository.

**5.1 Copy each passed run** (about 2.5 MB each), replacing `<run_id>`:

```bash
mkdir -p config/models/in-north
cp -r aeropulse-data/models/runs/<run_id> config/models/in-north/
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

## Step 8. Deploy to Google Cloud

Follow [deploy-google-cloud.md](deploy-google-cloud.md). The promoted models
travel inside the app image, and both regions get their own cycle job.

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
| `serving --strict`: `SHA-256 … differs`                          | The file changed after training. Copy it again from `aeropulse-data`, or retrain. Never edit the hash.                 |
| `serving --strict`: `feature version … differs`                  | The features changed since that run. Retrain.                                                                            |
| Live header shows "— no cycle yet"; Data sources are all "—"     | No live cycle has finished for the region. Run one (Step 6.3); exit `137` there means it ran out of memory.               |
| Forecast and hazard: "no ground station reported PM2.5 in the 24 h" | OpenAQ's reference monitors are late (see the reference doc). The models are loaded; there is no station row to score.  |
| The cycle's `served` still shows the rule version                | The image was not rebuilt after the YAML edit (Step 6.3), or the entry was refused: look for `model_serving_entry_refused`. |
| Models page: `entries that no cycle has loaded`                  | No live cycle since the rebuild. Run one (Step 6.3).                                                                     |
| The Live UI shows the Punjab Demo episode                        | The header is set to Demo, or `AEROPULSE_CONNECTOR_MODE` is `replay`. See [local-live.md](local-live.md).                |
| History gone after a Docker reset or on a new laptop             | `uv run python scripts/history.py status` first. If the folder is empty, restore the latest backup ("Where the history lives"). Loaded before the folder existed? `history.py migrate`. |
| `history.py status` says `no raw history loaded`                 | Wrong folder: check `AEROPULSE_HOST_DATA_DIR` in `.env`. Or nothing is loaded yet: Step 2.                               |
| A container cannot write `/app/var/aeropulse` (Linux)            | `sudo chown -R 10001 aeropulse-data`.                                                                                  |
| ML Evaluation page is empty                                      | Training ran without `--load-eval`, or the folder was restored: `AEROPULSE_DATA_DIR=aeropulse-data uv run aeropulse-ml load-eval`. |
| Anything on Google Cloud                                         | The troubleshooting table in [deploy-google-cloud.md](deploy-google-cloud.md).                                           |
