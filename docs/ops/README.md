# Operations docs: which one, in what order

Every page opens with a **Run this** block: the commands in order, ready to
paste from the repository root. The steps below it explain each one.

| Order | Page                                                             | Open it to                                                                                   |
| ----- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 1     | [local-live.md](local-live.md)                                   | Run the stack on the laptop and see Live: keys, start, stop, checks.                         |
| 2     | [train-and-serve.md](train-and-serve.md)                         | North India: load a year of history, train, promote, serve, save the history.                |
| 2b    | [train-and-serve-singapore.md](train-and-serve-singapore.md)     | The same for Singapore, plus its Demo and adding any other place.                            |
| 3     | [deploy-google-cloud.md](deploy-google-cloud.md)                 | The hackathon deployment: both regions live, the read-only demo token, ML Evaluation filled. |
| 4     | [runbook.md](runbook.md)                                         | Day-two operations: onboarding a region, pausing, rollback, secret rotation.                 |
| 5     | [train-and-serve-reference.md](train-and-serve-reference.md)     | Background: why the limits are where they are, how the plume works, Live-vs-Demo checks.     |

## Where the data lives

| Data                                        | Where                                                              | Survives                                         |
| ------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------ |
| Laptop history, trained runs, snapshots     | `aeropulse-data/` in the project, git-ignored                    | `down -v`, Docker resets, reboots                |
| Backups of that folder                      | `aeropulse-backups/` in the project, git-ignored                 | Anything, if you copy them off the laptop        |
| Promoted models                             | `config/models/` and `config/model_serving.yaml`, in git           | Everything; they ship inside the app image       |
| Cloud history, snapshots, evaluation rows   | BigQuery and Cloud Storage                                         | Restarts and redeploys                           |

The history script, from the repository root:

```bash
uv run python scripts/history.py migrate             # once: copy the old Docker volume into the folder
uv run python scripts/history.py status              # what is loaded, per region and source
uv run python scripts/history.py save                # dated archive in aeropulse-backups/
uv run python scripts/history.py restore <archive>   # put an archive back (stack stopped)
```
