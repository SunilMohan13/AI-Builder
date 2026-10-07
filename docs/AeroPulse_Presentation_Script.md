# AeroPulse — Presentation Script

**Use this file to build the deck later.** It is a slide-by-slide script, not the slides themselves.

**Suggested length:** 18 slides, 12–15 minutes, plus questions.  
**Audience:** hackathon judges, operators, and technical reviewers who need the problem, the product, the architecture, and the measured results.  
**Tone:** calm and specific. Lead with the corridor, then the gap, then what the system actually does. Say when a number is a ranking and when a model was withheld.

**Geography:** Punjab – Haryana – Delhi NCR (Indo-Gangetic corridor).  
**Air-quality scale:** CPCB National Air Quality Index. Do not use US EPA bands.

---

## How to turn this into slides

Each section below is one slide. Copy three things into the deck tool:

| Block | Where it goes |
| --- | --- |
| **On screen** | The slide. Keep it short. |
| **Visual** | Diagram, map, or table. Build this in the deck; do not paste the speaker notes onto the slide. |
| **Say** | Speaker notes. This is the script. |

Rules while you build the deck:

1. Every prediction slide must show `model_version` and whether the answer is `degraded`.
2. Hazard scores that are uncalibrated are rankings. Do not draw them as percentages.
3. The training numbers in slides 13–15 come from one documented run: 90 days of Open-Meteo air quality (CAMS-derived model output), five corridor cells, 10,920 grid-hours, 2026-06-10 to 2026-09-08. They are pipeline evidence. They are not CPCB station accuracy.
4. Three of the four trained models failed their promotion gate and stay at `VALIDATION`. The script says that on purpose.
5. What the API serves today for 24 h hazard and 24 h peak is a labelled persistence rule (`persistence-hazard-0.1`, `persistence-peak-0.1`), not a promoted gradient-boosted model.

---

## Slide 1 — Title

**On screen**

```
AeroPulse
Heads-up for the Indo-Gangetic pollution corridor

Punjab · Haryana · Delhi NCR
Evidence-fused air-quality intelligence
```

**Visual:** Dark map of northern India. A 1 km grid fades in over the corridor. No dashboard screenshot yet.

**Say:** AeroPulse is an operations system for the winter pollution corridor. It fuses stations, fires, weather, and satellite context onto a one-kilometre grid, then tells an operator what is happening, which evidence supports it, and where the plume is likely to be in the next few hours — with the model and the confidence labelled on every number.

---

## Slide 2 — The setting

**On screen**

```
One corridor. Many sources. One wind.

Biomass burning in Punjab and Haryana
Industry, traffic, and dust inside the cities
A shallow winter boundary layer that stops the air clearing
North-westerly flow that moves the plume toward Delhi NCR
```

**Visual:** Three stills — field burning, an industrial stack, a smogged arterial — then one arrow from Punjab across Haryana into Delhi.

**Say:** The fire is often in one state and the exposure lands in another. Stubble burning is one source. Brick kilns, industry, vehicles, and construction dust are others. In winter the boundary layer is shallow, so the mix does not vent. North-westerlies can carry that layer across Haryana toward Delhi overnight. By the time a city sees the haze, people have already been breathing it.

---

## Slide 3 — Problem statement

**On screen**

```
The operational problem

Authorities learn the episode from a number
that describes air that has already arrived.

They still need four answers, in time to act:

1. What is the concentration, including where no station sits?
2. Is this hour unusual against this cell's own baseline?
3. Which source family is plausible — as a hint, not a verdict?
4. Where does the plume go in the next 3, 6, and 12 hours?
```

**Visual:** A clock on the left labelled "report". A clock on the right labelled "act". The gap between them is the slide title.

**Say:** The problem is not the absence of an air-quality number. CPCB stations, satellite fire detections, and public AQI apps already produce numbers. The problem is timing and attribution. An operator needs a heads-up: a cell-level picture before the plume arrives, tied to evidence, with a forecast horizon long enough to warn schools, hospitals, and traffic authorities. A single city-wide AQI, published after the hour has passed, does not answer that.

---

## Slide 4 — What current tools already do

**On screen**

```
What exists today

CPCB / station monitors     Ground PM2.5, NO2, and co-pollutants at fixed sites
Public AQI apps             A city or station index, after the hour
NASA FIRMS                  Active-fire locations and fire radiative power
Open-Meteo / CAMS           Weather and a model air-quality field
Satellite AOD               A column aerosol signal — not surface PM2.5
```

**Visual:** Five logos or source names in a row, each with one line under it. No red crosses. These tools work. They are incomplete together.

**Say:** Credit the tools that already exist. Ground stations are the best measurement we have, and they outrank any model for the same cell-hour. FIRMS tells you where it is burning. Weather models tell you the wind and the mixing height. CAMS, reached here through Open-Meteo, is a model field, useful as a prior, and it is not a substitute for a CPCB station. Aerosol optical depth is a column measurement. It must never be shown as surface PM2.5.

---

## Slide 5 — What is missing

**On screen**

```
What those tools do not give an operator

No shared grid          A station, a fire, and a wind vector do not land
                        on the same cell by themselves

No fused event          A high hour, an upwind fire, and a wind field
                        stay in three different products

No labelled heads-up    AQI states the present. It does not say
                        where this plume is in six hours, or why

No honesty layer        A model field can be shown beside a station
                        reading with no provenance and no caveat

No action clock         Source, path, and the next 3–12 hours
                        are not one screen
```

**Visual:** Three disconnected panels (station dot, fire dot, wind barb) that do not share a grid. Caption: "Same hour. Three products. No event."

**Say:** The gap is fusion and foresight. Current tools are point products. They do not place fire, weather, and concentration on one grid. They do not open an event that carries its evidence. They do not separate "a station measured this" from "a model estimated this". And they do not give a short-horizon heads-up an operator can act on before the city is already over the CPCB Very Poor line.

---

## Slide 6 — The heads-up AeroPulse is built to give

**On screen**

```
Four questions. One grid. Every answer labelled.

Now        PM2.5 on a 1 km cell, station first, model only where needed
Unusual?   This hour against the cell's own hour-of-week baseline
Who?       Independent source likelihoods — a hint, never a cause
Next?      Wind-driven path, plus a forecast that must beat persistence
```

**Visual:** A single H3 cell with four callouts: Now, Unusual, Who, Next. A small badge on each callout: `model_version`.

**Say:** AeroPulse puts those four questions on the same one-kilometre H3 cell. "Now" prefers a ground station over any model. "Unusual" compares the hour with that cell's own history, not with a national average. "Who" returns separate likelihoods for biomass burning, traffic, regional transport, and mixed or unknown — they are not forced to add up to one, and they are not a proof of cause. "Next" is the heads-up: where the air is going, on a horizon an operator can still use. If the system cannot beat a simple "tomorrow looks like now" rule, it says so and does not pretend.

---

## Slide 7 — How the heads-up is produced

**On screen**

```
From raw feeds to a warning an operator can defend

1. Ingest     Stations, fires, weather, satellite context
2. Place      Snap every record onto H3 resolution 8 (~1 km)
3. Feature    One feature contract for training and for serving
4. Detect     Quality, anomaly, source hint, pollution event
5. Project    Wind-advection path and a short-horizon forecast
6. Label      model_version, degraded, calibrated — on the payload
7. Show       Map, event, evidence, forecast — or an explicit gap
```

**Visual:** A left-to-right pipeline. Step 6 is highlighted. The point of the slide is the label, not the model brand.

**Say:** Prediction is only useful if the operator can see what produced it. AeroPulse runs a deterministic intelligence path: quality checks, grid features, anomaly, source likelihood, an event with evidence, and a wind-advection forecast. Trained models sit beside that path. A model is allowed into a user-facing answer only after it beats an honest baseline on temporal and spatial holdouts. Until then the API serves the deterministic rule and marks the answer `degraded`. A hazard score also says whether it is `calibrated`. An uncalibrated 0.80 is a rank, not an 80 percent chance.

---

## Slide 8 — Architecture

**On screen**

```
Three application services, four data services

Connectors          Scheduled pulls. Replay fixtures, or live when configured.
                    CPCB, FIRMS, OpenAQ, Open-Meteo, and further sources.
                    A missing live key publishes nothing. It does not fake a feed.

Object store        Raw payloads, before anything is trusted.
Message bus         Canonical observation envelopes.
Worker              Quality → H3 grid → features → events → forecast → shadow scores.
Database            TimescaleDB + PostGIS. Observations, features, events, lineage.
API                 FastAPI /api/v1. Reads the database. Does not invent a row.
Web                 MapLibre. Demo and Live are separate. They never mix.
```

**Visual:** The architecture diagram in the appendix. One arrow only: connectors → raw store and bus → worker → database → API → web. Shadow scoring is a side branch that does not re-enter the response.

**Say:** The running system packs into three app containers — connector, worker, and API — plus TimescaleDB with PostGIS, Redpanda, Redis, and object storage. Connectors normalise each source into a canonical contract before anything else sees it. The worker is where the grid and the event are built. The API reads what the worker persisted. The web app has two modes. Demo is a scripted Punjab-to-Delhi episode that works with no backend. Live reads the API. A demo value is never drawn while the header says Live. If Live cannot supply a field, the screen shows a dash and the reason.

---

## Slide 9 — Architecture, in more detail

**On screen**

```
Worker path (deterministic Phase 3)

quality gate
  → H3 cell assignment
  → grid features (grid-features-0.5.0)
  → PM2.5 field (baseline-idw-0.1 where the model is not the served answer)
  → anomaly (quantile-baseline-0.1)
  → source likelihood (source-likelihood-0.1)
  → pollution event + evidence + lineage graph
  → forecast (wind-advection-0.1)
  → shadow scores for registered challengers (never shown as the answer)

Served 24 h hazard     persistence-hazard-0.1     degraded: true
Served 24 h peak       persistence-peak-0.1       degraded: true
Feature contract       ml-features-2.0.0
```

**Visual:** Two lanes. Lane A is "what the operator sees now" (named baseline versions). Lane B is "what was trained and registered" (next slides). A lock icon on the shadow-score branch.

**Say:** This slide is the runtime, not the ambition. Grid features are versioned. The served anomaly, source hint, and forecast on the event path are deterministic components with their own version strings. The 24-hour hazard and peak routes answer from a persistence rule and label every item degraded, because no hazard or peak model has been promoted. Challenger models can be scored in the shadow after the answer already exists. A shadow score cannot change, delay, or fail what the user sees. There is no large language model on this path. The copilot is a separate surface, and a number in its answer has to come from a tool over stored evidence.

---

## Slide 10 — Data the system can attach

**On screen**

```
Sources on the corridor

Live-capable now     Open-Meteo (no key), OpenAQ, FIRMS (keys required)
Replay fixtures      CPCB, industry / OCEMS, OSM, ICAR, INSAT,
                     Bhuvan, Sentinel-5P, MODIS, CAMS
Deliberately off     IMD — no public API; Open-Meteo already supplies
                     the same meteorology, and a second copy would
                     inflate sensor coverage

Ground stations outrank model output for the same cell-hour.
AOD is stored as a raster sample. It is never emitted as PM2.5.
```

**Visual:** A map with station pins, fire points, and wind barbs on the same H3 polygons.

**Say:** Thirteen connector packages exist. Three can run live: Open-Meteo without a credential, and OpenAQ and FIRMS when their keys are set. If a live key is missing, that source reports not configured and publishes nothing. It does not quietly serve a fixture under a live banner. IMD stays disabled so the same weather is not counted twice. Satellite AOD stays a raster observation. The contract test that enforces this is part of the build.

---

## Slide 11 — Models used for training

**On screen**

```
One feature contract. Four trained models.
Algorithm: scikit-learn HistGradientBoosting
(same histogram gradient-boosting family as LightGBM)

Model                    Task                         Features   Stage today
PM2.5 estimator          Concentration at a cell     30         Passed gate on
                         with no station                                      the documented run
Anomaly residual         Hour vs hour-of-week         27         VALIDATION
                         baseline, then a detector
Source likelihood        Four independent classes     20         VALIDATION
Propagation forecast     Residual over persistence    27         VALIDATION
                         at 3 / 6 / 12 / 24 h

Also specified, not the served answer:
  24 h peak and 24 h hazard feature sets
  Served answers: persistence-peak-0.1, persistence-hazard-0.1
```

**Visual:** Four model cards. Green border only on the estimator. Amber on the three held at validation. A footnote: "LightGBM was the design choice. HistGradientBoosting is the implementation that runs without a separate OpenMP runtime."

**Say:** Training and serving read the same feature list from `feature_spec.py`. A model cannot be handed its own target, and it cannot be handed a column derived from that target. The trainer is histogram gradient boosting. Random train-test splits are not available in this codebase. Every model is scored on a temporal holdout, a spatial holdout, and, where the window allows, a seasonal holdout. A separate model is fit per holdout, so a test row never trains the model that scores it. The promotion gate is allowed to fail. Three models failed it. They are registered and they are not the answer a user sees.

---

## Slide 12 — What the models are allowed to see

**On screen**

```
Feature families (ml-features-2.0.0)

Weather            temperature, humidity, pressure, rain, wind, mixing height
Stability          ventilation index, stagnation score
Fire               counts and FRP, including 25 km and 50 km rings,
                   plus an upwind fire score
Co-pollutants      PM10, NO2, SO2, CO, O3
Satellite          AOD, as a feature column only
History            lags at 1, 3, 6, 24 h and trailing means
Neighbours         nearby-cell PM2.5, for the nowcast only
Space and time     cell centre, distance to a station,
                   hour, day-of-year, weekend, stubble-season flag

The estimator predicts PM2.5 and is forbidden from seeing PM2.5.
The forecast predicts a future value and may see the present.
Source likelihood is forbidden from seeing the signals used to build its labels.
```

**Visual:** Grouped chips, not a 40-row table. One red chip called out: `pm25` excluded from the estimator.

**Say:** The feature list is the contract. Weather and mixing height describe whether the air can vent. Fire rings distinguish burning next door from burning at the edge of the domain. History is strictly trailing, so it does not leak the current hour into a nowcast. Neighbour concentrations exist so a cell with no station can be estimated from cells that have one. The stubble-season flag is a crop-calendar prior for this corridor, not a claim that a crop survey was joined. Full names are in the appendix if a reviewer asks.

---

## Slide 13 — How they were tested

**On screen**

```
Evaluation rules

Data        Open-Meteo air quality + weather
            5 cells: Delhi NCR, Gurugram, Karnal, Ludhiana, Amritsar
            90 days, hourly → 10,920 grid-hours
            CAMS-derived model output, not CPCB ground truth

Splits      Temporal   last 20% of time, strictly in the future
            Spatial    whole H3 cells held out
            Seasonal   latest calendar month held out

Baseline    Persistence for regression
            Majority class for source classification
            CPCB "Very Poor" breakpoint, 121 µg/m³, for the anomaly label

A model that cannot beat its baseline is not promoted.
```

**Visual:** A timeline with a cut at the 80th percentile, and a small map with one cell greyed out. Caption under the data line: "Optimistic until retrained on CPCB."

**Say:** These numbers come from one command against that 90-day window. The important caveat sits on the slide on purpose. Open-Meteo air quality is a CAMS model field. Reconstructing a smooth model field from co-pollutants of the same model is easier than estimating a real CPCB station. Skill on this set shows the pipeline, the split, and the gate. It is not an operational accuracy claim for Delhi. Retraining on CPCB ground truth is the step required before anyone quotes these errors as station error.

---

## Slide 14 — Testing results

**On screen**

```
PM2.5 estimator — gate PASS on this run
(skill = improvement over persistence; higher is better)

Holdout      MAE     RMSE    R²      Bias     Persistence MAE    Skill
Temporal     3.90    5.84    0.975   −1.40    6.89               +0.43
Spatial      3.61    5.69    0.961   −1.09    5.34               +0.32
Seasonal     3.16    4.94    0.961   +0.18    5.46               +0.42

Propagation forecast — skill vs persistence

Horizon    Temporal skill     Spatial skill      Decision
3 h        +0.17              +0.23              Useful on this set
6 h        +0.25              +0.33              Useful on this set
12 h       +0.35              +0.46              Useful on this set
24 h       −0.12              +0.15              Withhold
```

**Visual:** Two tables, exactly as above. Do not add a green check on the 24 h row.

**Say:** The estimator beat persistence on all three holdouts, with a small negative bias on the temporal cut, meaning it under-predicted slightly. That matters for alerting and is worth watching. The forecast shows real skill from 3 to 12 hours. At 24 hours on the temporal holdout it is worse than simply repeating the current value, because the diurnal cycle makes "same hour tomorrow" a strong baseline. The 48-hour horizon was not scored: the window did not contain enough pairs, and the run reports that instead of a made-up number. The correct product decision is to ship the horizons that win and withhold the one that loses.

MAE units are micrograms per cubic metre on the CAMS-derived field.

---

## Slide 15 — Results that failed, and why they are on the slide

**On screen**

```
Held at VALIDATION. Not served.

Anomaly detector
  Residual model is sound (temporal residual R² 0.84)
  Detector recall at the CPCB Very Poor line: 0.046 temporal, 0.204 spatial
  Precision is high. False-alert rate is near zero.
  It misses most real exceedances. Useless to an operator.

Source likelihood
  Temporal accuracy 0.972 vs a majority-class rate of 0.933
  regional_transport F1 0.84
  traffic F1 0.00 (25 supporting rows)
  Labels are heuristics. This is not source attribution.

24 h hazard and 24 h peak
  Served from persistence, marked degraded and, for hazard, uncalibrated.
```

**Visual:** Three cards with the word WITHHELD. No accuracy trophy for 0.972.

**Say:** This is the slide that makes the other results believable. The anomaly residual fits well and the detector built on a one-standard-deviation rule does not: it catches about 5 percent of temporal exceedances. High precision with almost no alerts is the failure mode the design called out in advance. Source likelihood looks accurate only if you ignore the baseline. Always guessing "mixed or unknown" is already right 93 percent of the time. The model does learn regional transport. It does not detect traffic. The labels were rules, fit on training rows only, and the feature set was banned from seeing the inputs of those rules so the score would not be circular. Until there are real attribution labels, this model stays a hint inside the evidence view, not a headline.

---

## Slide 16 — What the product includes

**On screen**

```
Operator surfaces

Overview          Corridor status and active events
Live map          Air quality, fire, weather, forecast, satellite footprints,
                  grid polygons, industry assets, hazard layer
Event             Status, evidence, forecast, lineage graph
Forecast          Short-horizon path for the selected event
Risk              Pollution severity separated from population exposure
Sources           Per-source health: last success, latency, records, errors
Copilot           Answers grounded in stored events and tools
Citizen reports   Submitted, held pending, never auto-opened as a high event
Alerts            High and critical events only

Demo mode         Scripted episode, no backend required
Live mode         API only. Missing fields render as — with a reason
```

**Visual:** A thumbnail strip of the nine screens. One callout on the header toggle: Demo | Live.

**Say:** Walk the room through one path: open the map, select the transported episode, open the event, show evidence, then the forecast. Point at the provenance badge when a number is a baseline. Population exposure is a separate score from pollution severity, and the shipped population grid is a small licensed placeholder marked replace-before-production. Punjab will not show a real headcount until a WorldPop or Census extract is configured. Citizen photos are accepted and stay in moderation. They do not create a high-severity event by themselves.

---

## Slide 17 — Trust rules built into the product

**On screen**

```
If it can mislead an operator, it is a bug

Station beats model          for the same cell and hour
Demo never paints Live       one client, one mode switch, fallback is named
No silent zero               a cell with no PM2.5 is omitted, not scored 0
Hazard magnitude             shown as a rank until calibration exists
Source likelihoods           independent, and labelled as weak supervision
Shadow models                scored after the answer, invisible to the user
Promotion gate               a failing metric blocks release
Feature version              a changed feature list invalidates old artifacts
```

**Visual:** Eight short rules, two columns. This slide can stay up during questions.

**Say:** These are the rules the code enforces, not a style guide. A fast toggle between Demo and Live cannot serve the other mode's cache. List endpoints share one shape: items, total, limit, offset. Auth in development is a signed token with roles; production identity is a later step. The copilot may only state a number that a tool returned, and a missing key or a grounding failure falls back to deterministic retrieval with a stated reason.

---

## Slide 18 — Close

**On screen**

```
AeroPulse gives the corridor a heads-up
that current AQI tools do not assemble.

Fuse stations, fires, and weather on a 1 km grid.
Open an event with evidence.
Project the next 3–12 hours.
Label every number with the model that made it.
Withhold the model that loses to a simple baseline.

Next, before any operational accuracy claim:
retrain the estimator on CPCB,
promote only the horizons that beat persistence,
calibrate the 24 h hazard so a score can be a probability.
```

**Visual:** Return to the corridor map from slide 1. One caption: "The fire is upwind. The warning is here."

**Say:** Close on the job, not on the stack. People in Delhi should not meet the episode only after they have breathed it. AeroPulse is the system that puts the upwind evidence and the next few hours on one screen, and that refuses to show a confident number it has not earned. I can walk through the map, the event, or the holdout tables.

---

## Appendix A — Architecture diagram (build this as one slide visual)

```text
┌──────────────── connectors (scheduled loop) ────────────────┐
│ CPCB · FIRMS · OpenAQ · Open-Meteo · industry · satellite   │
│ live only when configured; otherwise replay, never mixed    │
└───────────────┬───────────────────────┬─────────────────────┘
                │ raw object            │ canonical envelope
                ▼                       ▼
           object store            message bus
                                        │
                                        ▼
┌──────────────────────── worker ─────────────────────────────┐
│ quality → H3 r8 → grid features → anomaly → source hint     │
│        → event + evidence + lineage                         │
│        → wind-advection forecast                            │
│        → shadow score (side write, not the response)        │
└────────────────────────────┬────────────────────────────────┘
                             ▼
                    TimescaleDB + PostGIS
                             │
                             ▼
                    FastAPI  /api/v1
                             │
                             ▼
              Web  (Demo episode  |  Live API)
```

Versions to print on the diagram if there is room:

| Component | Version on the running path |
| --- | --- |
| Grid features | `grid-features-0.5.0` |
| PM2.5 field used by the deterministic path | `baseline-idw-0.1` |
| Anomaly | `quantile-baseline-0.1` |
| Source likelihood | `source-likelihood-0.1` |
| Forecast | `wind-advection-0.1` |
| 24 h hazard | `persistence-hazard-0.1` (`degraded`) |
| 24 h peak | `persistence-peak-0.1` (`degraded`) |
| ML feature spec | `ml-features-2.0.0` |

---

## Appendix B — Feature names by model

Use this only if someone asks. Do not put it on a title slide.

**Shared building blocks**

- Time: `sin_hour`, `cos_hour`, `sin_doy`, `cos_doy`, `is_weekend`, `is_stubble_season`
- Space: `center_lat`, `center_lon`, `station_distance`
- Weather: `temperature`, `humidity`, `pressure`, `rainfall`, `wind_u`, `wind_v`, `wind_speed`, `boundary_layer_height`
- Stability: `ventilation_index`, `stagnation_score`
- Fire: `fire_count`, `fire_frp`, `upwind_fire_score`, `fire_count_25km`, `fire_count_50km`, `fire_frp_50km`, `upwind_fire_frp`
- Co-pollutants: `pm10`, `no2`, `so2`, `co`, `o3`
- Satellite: `aod`
- History: `pm25_lag_1h`, `pm25_lag_3h`, `pm25_lag_6h`, `pm25_lag_24h`, `pm25_roll_6h`, `pm25_roll_24h`, plus extended roll max, roll std, and trend columns on the later feature sets
- Neighbours, estimator only: `neighbor_pm25_mean`, `neighbor_pm25_max`, `neighbor_count`, `upwind_pm25`

**What each model must not see**

| Model | Target | Excluded on purpose |
| --- | --- | --- |
| PM2.5 estimator | `pm25` | The target, and anything derived from it (for example `pm25_delta_1h`) |
| Anomaly | residual against an hour-of-week baseline | Baseline statistics fit on training rows only |
| Source likelihood | class label | Fire columns and co-pollutants, because the weak label was built from those |
| Propagation | future PM2.5 residual | The future value itself |

---

## Appendix C — Numbers to memorise, and numbers to refuse

**Safe to say**

- Grid: H3 resolution 8, about 1 km.
- Hazard line used in evaluation: 121 µg/m³, CPCB Very Poor.
- Estimator skill on the CAMS-derived 90-day run: about +0.32 to +0.43 versus persistence.
- Forecast skill on that same run: positive at 3, 6, and 12 hours; negative at 24 hours on the temporal holdout.
- Anomaly detector temporal recall: 0.046. That is why it is withheld.
- Source model temporal accuracy 0.972 against a 0.933 majority baseline. That is why accuracy is the wrong headline.
- Developer-machine API smoke, 50 sequential requests, 2026-09-14: events p95 16 ms, grid features p95 11 ms, grid predictions p95 19 ms. This is not a production SLO.

**Do not say**

- Do not quote the estimator MAE as CPCB station error.
- Do not call source likelihood a determination of who caused the episode.
- Do not call an uncalibrated hazard score a probability.
- Do not say the 24 h gradient-boosted forecast is what the API serves.
- Do not say Sentinel, MODIS, or CAMS HTTP ingestion is live. Those connectors replay fixtures.
- Do not present the five-cell population fixture as a census.

---

## Appendix D — Suggested demo path while the deck is up

1. Start in Demo. Show the scripted episode moving from Punjab toward Delhi NCR.
2. Open one event. Show evidence and the forecast horizon.
3. Point at provenance: baseline versus model, and `degraded` where it applies.
4. Switch to Live only if the API is up and a token is configured. If it is not, leave Demo on and say why the Live control is disabled.
5. If Live is up, show source health and one grid cell. If a field is missing, leave the dash on screen and read the reason.

---

## Source notes for the presenter

Figures and versions in this script were taken from the repository documents current at the time of writing:

- `docs/architecture.md` — running intelligence versions and the service path
- `docs/AeroPulse_ML_Architecture.md` — the 90-day training run, holdout tables, and promotion outcomes
- `docs/api.md` — routes, latency smoke numbers, hazard labelling
- `libs/contracts/aeropulse_contracts/feature_spec.py` — `ml-features-2.0.0` and the feature families
- `docs/video/AeroPulse_Hackathon_Video_Script.md` — the corridor narrative this deck shares

If a later training run promotes a model, update slides 9, 11, 14, and 15 before presenting. The gate outcome is the slide. The algorithm name is not.
