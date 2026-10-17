# AeroPulse APAC — revised hackathon video script

## Purpose

Replace the original 19-clip film with a clearer, evidence-led story: **15 clips of about 8 seconds each, plus a 3-second end card** (approximately **2:03** before the live demo). The video should look like a polished Google hackathon product film—not a map slideshow.

The visual priority is:

1. **Show the product and system, not just describe them.** Use clean, animated architecture diagrams, a data-flow view, a regional-training/evaluation view, a forecast visual, and real product footage.
2. **Use generated video for atmosphere only.** Use Veo/Gemini for the opening environmental footage and subtle transition plates. Do not ask it to render legible labels, dashboards, charts, or architecture diagrams. Add those as editable vector graphics or real screen recordings in post.
3. **Make regional modelling concrete.** Show how data feeds into region-specific configuration and model evaluation, and that a model is served only after its gate passes. Show North India and Singapore as served only if the repository/gate reports still support that; show NSW as rules-based/degraded only if this remains true.
4. **Keep claims auditable.** No invented accuracy percentages, population exposure counts, unsupported hazard coverage, or fabricated live values. Never show demo data as live.

## Timing and film structure

- 15 clips × 8 seconds = 2:00
- 3-second end card = 0:03
- Total: approximately **2:03**, before the live demo
- One consistent voiceover track is recommended. Generate or record the narration once, then lay it over the clips. Use the generated clips for ambient sound only; this avoids voice drift and missed words between AI-generated clips.

| Clip | Time | Story beat | Primary visual (not a generic map) |
|---|---:|---|---|
| 1 | 0:00–0:08 | The problem | Documentary footage of smoke and haze |
| 2 | 0:08–0:16 | The APAC use case | Three clearly separated regional use-case cards |
| 3 | 0:16–0:24 | Architecture at a glance | Full system architecture diagram |
| 4 | 0:24–0:32 | Data sources | Connector cards with source, data type, and health/status |
| 5 | 0:32–0:40 | From feeds to features | Animated ingestion, time/location alignment, and spatial grid |
| 6 | 0:40–0:48 | Regional configuration | Three region packs, hazards, and AQI rules |
| 7 | 0:48–0:56 | Regional model training | Historical regional data → features → train/validate model |
| 8 | 0:56–1:04 | Evaluation and model gate | Held-out time/season checks and baseline comparison |
| 9 | 1:04–1:12 | Scheduled inference | Per-region serving cycle, versioned output, provenance |
| 10 | 1:12–1:20 | Forecast the plume | Real plume view with P50/P90 bands and arrival list |
| 11 | 1:20–1:28 | Explain likely sources | Backward trace and ranked, evidence-backed candidates |
| 12 | 1:28–1:36 | Citizen observations | Real report/photo flow plus AI visual observation |
| 13 | 1:36–1:44 | Corroboration and decision | Fire + wind + station evidence → watch or operator review |
| 14 | 1:44–1:52 | Operational experience | Real Command Centre and Ask AeroPulse with cited answer |
| 15 | 1:52–2:00 | End-to-end payoff | Return to simplified architecture with the product in action |
| End card | 2:00–2:03 | Demo hand-off | Product name and “Live demo” |

> **Important:** This is a script based on the attached Markdown, not a repository audit. Before final export, use the included Cursor prompt to validate all implementation-specific details against the actual code, configuration, and gate reports. Replace any claim the repository cannot prove.

---

## Visual system

### Style

- **Canvas:** 16:9, 1920×1080 delivery target; design all overlays for safe margins.
- **Background:** dark navy `#0B1426`, with subtle cyan grid only where it helps explain geography or data flow. Avoid making the map the default background for every clip.
- **Data:** cyan `#22D3EE`; smoke/forecast `#F59E0B`; risk/watch `#F43F5E`; passed gate / verified corroboration `#FFFFFF`; unavailable or not configured `#7B8495`.
- **Typography:** one clean sans-serif family, e.g. Inter or equivalent. Large labels, short phrases, strong contrast. No paragraphs inside the video.
- **Motion:** use simple left-to-right flow, progressive reveals, gentle zooms, and clean morphs. No spinning dashboards, random particles covering labels, or busy transitions.
- **Diagrams:** create in SVG, HTML/React/Remotion, or another editable source. Animate each layer deliberately. Do not rely on generative video models to draw diagram labels.
- **Real product UI:** screen-record the actual application. Crop browser chrome, hide secrets, keep the correct `Live` or `Demo` banner visible, and never composite demo data under a Live label.

### Narration and audio

Use one narrator and one continuous, edited voice track for consistency. Suggested voice: warm, calm, neutral international English, confident but not theatrical. Target roughly 14–18 words per 8-second clip. Add restrained ambient audio only under the voice; no per-clip generated music. Keep narration intelligible on laptop speakers.

### Evidence rules

- Never add an AQI reading, timestamp, ETA, model metric, station reading, or number unless it is visible in the real product or sourced from a repository artifact/report.
- Keep predicted plumes visually distinct from confirmed smoke: use translucent bands and dashed boundaries.
- Backward source results are **ranked likely sources**, not causal verdicts and not calibrated probabilities unless the implementation explicitly supports them.
- Gemini's citizen-photo description is an observation, not confirmation. The citizen photo alone must not create or modify a pollution event.
- Do not claim population-exposure estimation or push/SMS notification delivery unless the implementation has been added and verified.

---

# Clip-by-clip script

For each clip below, the **narration** is the only spoken line. The **visual build** describes what needs to be shown in the finished video. Use the optional **Veo plate prompt** only for atmospheric footage or a background. For architecture, charts, interface labels, and model evidence, use the editable overlays and real screen captures described here.

## Clip 1 — The problem: smoke travels (0:00–0:08)

**Narration**

> Smoke from crop burning and bushfires travels with the wind. Today's air-quality reading is only a snapshot.

**Visual build**

Open with a strong, realistic 2-second crop-residue-burning shot in North India, then match-cut to a smoky forest ridge or hazy city. Keep it documentary, restrained, and credible. On the final two seconds, place a minimal overlay: `Sources change. Smoke travels.` Avoid showing a map UI yet.

**Veo/Gemini plate prompt**

```text
Create an 8-second, 16:9 cinematic documentary plate about smoke pollution in Asia-Pacific. Begin with a wide view of harvested agricultural fields with a small, realistic crop-residue fire and a plume of grey smoke; let the smoke drift with the wind. Natural light, grounded documentary realism, muted earth colours, no sensational fireball, no disaster spectacle. Smooth camera movement, one continuous shot. Ambient wind and distant field sounds only. No narration, no music, no captions, no text, no logos, no readable screens, no watermarks.
```

**Edit notes**

Use one or two shots at most. Do not add an unverified AQI value. If you include Australia or Indonesia in the opening montage, treat them as examples of the broader APAC smoke/haze problem—not as a claim that every hazard is already modelled by AeroPulse.

## Clip 2 — One platform, regional context (0:08–0:16)

**Narration**

> AeroPulse brings regional air-quality context together across North India, Singapore, and New South Wales.

**Visual build**

Use a crisp three-card layout, not a full-screen map. Each card includes a small location silhouette, a short hazard descriptor, and the relevant regional air-quality framework:

- **North India** — crop-residue smoke — CPCB scale
- **Singapore** — transboundary haze — NEA scale
- **New South Wales** — bushfire smoke — NSW categories

Animate the three cards into one shared workspace. The exact labels and scales must be confirmed from each `config/regions/.../region.yaml` file before export.

**Optional generated background prompt**

```text
Create an 8-second dark navy cinematic background plate for a premium environmental intelligence product film. A faint outline of Asia-Pacific appears briefly, with three subtle cyan points connected by fine lines. Keep the geography understated and leave generous negative space in the centre for three editable information cards to be composited later. Slow, controlled motion, no text, no labels, no symbols that resemble a real dashboard, no logos, no narration, no music.
```

**Editor overlay**

Three cards with location, hazard, and regional standard. Use vector icons and editable type. Do not ask the video model to render the card text.

## Clip 3 — Architecture at a glance (0:16–0:24)

**Narration**

> Multiple environmental feeds enter a shared data pipeline. Regional intelligence then powers forecasts, evidence, and operator decisions.

**Visual build — required architecture diagram**

Build a clean, animated, left-to-right architecture view with five grouped layers. Use short labels and direct connectors; avoid crossed lines.

1. **Data sources**: air-quality observations; fire detections; aerosol observations; weather and wind; citizen reports.
2. **Connectors and preparation**: source connectors → validation and time/location alignment → spatial feature grid.
3. **Regional intelligence**: North India pack | Singapore pack | NSW pack; each has its own configuration and eligible model/rules path.
4. **Evaluation and serving**: train/evaluate → model gate → scheduled regional scoring; a rules/degraded path where no model is served.
5. **Outputs**: forecast plume and arrival estimates; likely-source evidence; citizen-report triage; Command Centre and Ask AeroPulse.

Only include component names confirmed by the repository. In particular, show actual storage, orchestration, training, and inference components if they are present; do not invent microservices or a model-training service just to make the picture look sophisticated.

**Animation**

Reveal sources first, then the shared preparation path, then the region packs, then the evaluation/serving layer, then the product outputs. Highlight one complete path from a source to an output. Hold the full diagram for the final second.

**Build instruction**

This must be an authored SVG/HTML/Remotion diagram, not an AI-generated image. Deliver an editable source file so the diagram can be revised when a repository detail changes.

## Clip 4 — Data sources and connector health (0:24–0:32)

**Narration**

> AeroPulse combines ground stations, satellite fire detections, a satellite aerosol index, and weather forecasts in every region.

(17 words. All four are configured in all three region packs. The extra regional station feeds are shown on screen, not spoken.)

**Visual build**

Show four shared source cards in a row. Then show two smaller regional cards attached to their region. Each card has an icon, the connector ID exactly as the Data sources page shows it, the data type, and its refresh cadence. Verified against `config/regions/*/region.yaml` and `connectors/`:

| Card (connector ID) | Provides | Regions | Cadence | Card note |
|---|---|---|---|---|
| **OpenAQ** (`openaq`) | Ground PM2.5 and PM10, reference monitors only | All three | 15 min | Measured. Needs `AEROPULSE_OPENAQ_API_KEY` |
| **NASA FIRMS** (`firms`) | Satellite fire detections, VIIRS on NOAA-20 and Suomi NPP, near real time | All three | 15 min | Read over the wider source area, so upwind fires count. Needs `AEROPULSE_FIRMS_MAP_KEY` |
| **Open-Meteo** (`openmeteo`) | Weather and wind forecasts, 48 h kept; CAMS-derived air-quality model output | All three | Hourly | Model-derived. Never shown as a station reading. No key |
| **Earth Engine** (`earthengine`) | Sentinel-5P UV aerosol index | All three | Daily | Needs an Earth Engine project and Google credentials, otherwise "not configured" |
| **NEA** (`nea`) — regional | One-hour PM2.5 for each NEA reporting region, via data.gov.sg | Singapore only | Hourly | Measured. Ground truth for Singapore. No key |
| **CPCB** (`cpcb`) — regional | Station PM2.5 from a recorded fixture | North India only | — | **Replay only, not live.** Label it `replay`, never `live` |

Card labels for the editor: `Measured` on OpenAQ and NEA; `Model-derived` on the Open-Meteo air-quality line; `Replay` on CPCB. Do not draw an IMD, MODIS, INSAT, Bhuvan or `sentinel5p` card. Those connector folders exist, but no region pack enables them.

**Real insert**

Use a genuine 2–3 second recording of the **Data sources** page for one region. Record it right after a completed cycle, so the states reflect that cycle.
- **What the page shows:** a card per connector with:
  - its ID;
  - a state: `Healthy`, `Degraded`, `Failing`, `Not configured` or `Disabled`;
  - its area: `display` or `source`;
  - records this cycle and last success;
  - for keyed sources, the key's **reference name**. The value is never shown.
- **What to point at:** the state badge and "Records this cycle".
- **`Not configured`:** show a card with this state only if that is its real current state. Do not stage it.
- **Singapore:** use it if you want the regional `nea` card in the shot.
- **Live banner:** keep it visible.

Do not imply a connector is active just because it appears in the diagram. The card animation is the concept; the recording is the evidence.

**Motion**

The four shared cards send different-shaped signals into the next clip:
- point pulses for stations;
- red dots for fires;
- a soft haze layer for the aerosol index;
- flowing lines for wind.

The regional NEA and CPCB cards slot in under their region's label, and CPCB carries a grey `replay` tag. Use icons and small moving lines, not a full-screen map.

## Clip 5 — From raw feeds to aligned features (0:32–0:40)

**Narration**

> Time and location are aligned, observations are mapped to spatial cells, and every output keeps its provenance.

**Visual build — required data pipeline diagram**

Show four explicit stages:

`Source records` → `Validate and align time/location` → `Spatial cells and regional features` → `Measured / model-derived / predicted`

Use a short sample record moving through the stages; show its timestamp/location becoming aligned, then landing in a spatial cell. The spatial-grid label in the current script is **H3 resolution 8**; verify the displayed “about one-kilometre” description against the implementation before retaining it. Use the exact provenance field name and labels from the code, including `provenance_class` if still applicable.

**Editor overlay**

Keep these labels large and readable. Use only one sample record and no invented numeric values. If you show a table, populate it from a real or clearly labelled demo record.

## Clip 6 — Region packs, not hard-coded locations (0:40–0:48)

**Narration**

> Region packs define local hazards, map context, and air-quality rules, so regional behaviour is configuration-driven.

**Visual build**

Create three clean configuration cards connected to the shared pipeline:

- `in-north` — CPCB scale; crop-burning hazard profile
- `sg-singapore` — NEA scale; transboundary haze profile
- `au-nsw` — NSW air-quality categories; bushfire-smoke profile

Show each card containing `region.yaml` and its hazard profile. Then add a fourth empty card labelled `New region: configure and validate`—but only if the CLI/tests confirm the add-region workflow. Avoid claiming “zero code changes” unless the test and command path prove it.

**Real insert (optional)**

A brief region-switcher capture is useful, but keep the diagram as the primary visual. Make the three cards visually distinct without implying they have identical coverage or model maturity.

## Clip 7 — Regional training (0:48–0:56)

**Narration**

> Each regional model learns from that region's historical data and configured features, rather than assuming one model fits every climate.

**Visual build — required model-training diagram**

Build a 4-step horizontal pipeline:

`Regional historical observations` → `Feature preparation` → `Train candidate model` → `Regional candidate artifact`

Above the flow, show three separate lanes (North India, Singapore, NSW) so it is visually obvious that data/configuration and model eligibility are regional. Below the flow, show the actual model family and training command only after Cursor verifies them in the repository. If the implementation uses a shared model type with separate regional runs, state that accurately; do not imply three different algorithms unless the code proves it.

**Important accuracy rule**

The current source script does not name the actual model algorithm or enumerate all training features. Cursor must inspect training code, feature builders, run metadata, and configuration to fill these details. Until verified, keep the labels generic as above. Do not invent LSTM, XGBoost, Prophet, neural networks, accuracy scores, or training duration.

## Clip 8 — Evaluation gate: evidence before serving (0:56–1:04)

**Narration**

> Candidates are tested on unseen time periods and seasons. A model is served only when it beats the simple persistence baseline.

**Visual build**

Split the frame into two parts:

- Left: simple animated timeline showing rolling-origin holdouts and a separate seasonal check. Label `time-aware validation` and `season check`.
- Right: one real evaluation view or an authored chart sourced from a real gate report, comparing the candidate with `persistence — same as now`.

Then animate a gate:

- **Passed** → model version can be served
- **Not passed / no model** → keep rules/degraded mode or require review

The original script says North India and Singapore currently pass at 1–24 hour horizons and NSW has no served model. Verify current gate reports and `config/model_serving.yaml` before showing these states. If they still match, show `North India · served`, `Singapore · served`, and `NSW · rules/degraded`. If not, replace them with the current truthful states.

**Real insert recommended**

Use the Models page or generated chart from the gate report. Never fabricate a chart just to show a convincing upward line. Show actual metric names/values only if readable and verified.

## Clip 9 — Scheduled, versioned inference (1:04–1:12)

**Narration**

> On each regional cycle, the eligible model scores the latest inputs and publishes a versioned, traceable prediction.

**Visual build**

Show one compact sequence:

`Latest regional data` → `Scheduled regional job` → `Eligible model or fallback rules` → `Prediction + model version + provenance` → `Command Centre`

Use three lanes, one per region, with staggered progress to show independent cycles. The current script names Cloud Run Jobs, BigQuery, and Cloud Storage; use those labels only after checking deployment/configuration in the repo. If the job actually runs hourly, label `hourly cycle` and show a real timestamp only from a real capture.

**Editor overlay**

`Region-specific cycle` · `Model version` · `Data provenance`

Do not suggest that all regions run a trained model if one region uses a rules/degraded path.

## Clip 10 — Forecast smoke transport (1:12–1:20)

**Narration**

> Forecast winds drive an ensemble plume, showing a possible transport corridor and estimated arrival windows—not a certainty.

**Visual build**

Use a real Command Centre recording as the main layer. Show the source point, wind direction, translucent amber P50/P90 bands if those exact bands are implemented, town/place markers, and an arrival/ETA list if populated. The attached script points to a 200-particle ensemble; verify the parameter and labels in the current code before showing `200 particles`.

Use dashed outer bands and the label `Experimental forecast`. Do not use a white “confirmed” pulse on the plume. Avoid a generated pseudo-dashboard: the product footage must carry this scene.

**Optional generated transition plate**

```text
Create an 8-second dark navy environmental-data background plate with a few soft amber particles moving along a curved wind path and a faint cyan spatial grid. Reserve the centre and right side for a real product screen recording to be composited later. Keep the particles subtle, the motion slow, and the scene uncluttered. No text, numbers, labels, interface, logos, narration, or music.
```

## Clip 11 — Backward trace and likely sources (1:20–1:28)

**Narration**

> When a station spikes, AeroPulse traces air movement backwards and ranks candidate source areas with supporting evidence.

**Visual build**

Start from an actual elevated station reading/event selected for the demo. Animate backward cyan dotted trails to candidate regions, then show a compact ranked list with the evidence used by the implementation. Keep candidates as hollow rings; do not turn the highest-ranked candidate into a confirmed source.

**Real insert**

Capture the actual incident panel or source-ranking view. If there is no active event in Live mode, use a clearly labelled Demo view or a pre-recorded real product state. Do not invent a percent likelihood. Use the phrase `likely source` or `ranked candidate`, never `caused by`.

## Clip 12 — Citizen photo: observation, not proof (1:28–1:36)

**Narration**

> A citizen can submit a smoke photo. AI describes visible content, while location checks and privacy safeguards run separately.

**Visual build**

Show a real citizen-report flow: image upload → sanitization/metadata removal → location/time trust checks → AI visual observation. The result card should be labelled `AI observation — requires corroboration`.

If the UI supports it, show only the actual schema-constrained descriptive fields (for example, the presence of a smoke plume), not model-generated numeric air-quality readings. Use a real report or a synthetic report clearly marked `Demo`; obscure personal information and exact private addresses.

**Technical verification**

The original script refers to the Gemini-based image observer, a validator rejecting numeric claims, and metadata sanitation. Confirm these paths under `apps/citizen_analyzer` and the tests before retaining those details.

## Clip 13 — Independent corroboration controls the decision (1:36–1:44)

**Narration**

> Fire detections, wind direction, and nearby station trends corroborate a report; otherwise, it goes to operator review.

**Visual build — required evidence/decision diagram**

Place the citizen observation on the left and three evidence nodes on the right:

1. Satellite fire detection nearby
2. Wind consistent with transport from the fire
3. Nearby station trend, such as rising PM2.5

Connect the nodes to a visible decision table:

- `Sufficient corroboration` → the configured watch/plume workflow
- `Insufficient or conflicting evidence` → `Operator review`

Use a white outline only after the rule evaluation passes. A coral ripple may mark a watch being raised, but do not make an unsupported claim of automatic public notification. Add a small footer: `A citizen photo alone does not create or change a pollution event` if the code/tests still enforce this rule.

**Build instruction**

Make this a clear authored diagram. No map background is necessary. It should be possible to understand the three checks and two possible outcomes with the sound off.

## Clip 14 — Command Centre + Ask AeroPulse (1:44–1:52)

**Narration**

> Operators can inspect the forecast, follow its evidence, and ask AeroPulse a question with a cited, data-grounded answer.

**Visual build**

Use a real screen recording for most of this clip:

- 0–3 seconds: Command Centre showing the region, correct Live/Demo banner, plume or current event, and an evidence panel.
- 3–6 seconds: Ask AeroPulse question: `Where is this smoke coming from and where will it go?`
- 6–8 seconds: the actual cited response and one visible source/reference. Keep text large enough to read.

Avoid fake UI rendered by a video model. Use an actual answer from the application and validate its citations. Do not display secrets, internal tokens, private addresses, or personal information.

## Clip 15 — One traceable flow (1:52–2:00)

**Narration**

> From source data to regional forecasts and reviewed warnings, AeroPulse connects environmental signals to an explainable operational workflow.

**Visual build**

Return to a simplified version of the architecture diagram from Clip 3. Highlight one end-to-end path with a single animated line:

`Sources` → `Regional features` → `Model gate` → `Forecast / evidence` → `Operator workspace`

Show a small live product inset on the right for the last two seconds, using a genuine product capture. Make the final line settle into the product logo/title area. This is the film's technical summary, not another abstract map sequence.

**Optional generated background prompt**

```text
Create a 8-second premium technology-film background plate, dark navy with a faint cyan glow at the horizon and restrained ambient movement. Leave the left two-thirds clear for an editable architecture diagram and the right third clear for a real product-screen inset. No text, numbers, logos, interface, narration, or music.
```

---

## End card — 3 seconds (2:00–2:03)

**Visual**

Dark navy background, AeroPulse wordmark/title, one concise line `Regional air-quality intelligence`, and `Live demo →`. Use the real project logo if available. Hold long enough to read, then start the live demo on the same dark navy frame/audio bed.

**Audio**

Short ambient tail, then silence. No new narration.

---

# Real captures to record before editing

Record these from the actual application, with browser chrome hidden. Capture at 1920×1080 if possible. Keep the cursor controlled and avoid slow loading states unless the state itself is the point.

| Used in | Capture | Must visibly establish |
|---|---|---|
| Clip 4 | Data Sources page | Real connector names and status; which are configured/unavailable |
| Clip 6 | Region selector or config view | Real region names and per-region rules/configuration |
| Clip 8 | Models page or gate report | Current gate outcome, validation strategy, baseline comparison |
| Clip 9 | Cycle/job history or model metadata | Scheduling and prediction/model version, if exposed |
| Clip 10 | Command Centre plume | Experimental label, band legend, and real populated places/ETAs if available |
| Clip 11 | Incident/source-ranking panel | Ranked candidates and evidence, with no invented percentages |
| Clip 12 | Citizen Reports page | AI observation and privacy/corroboration state; redact personal data |
| Clip 14 | Command Centre + Ask AeroPulse | Actual query, cited answer, correct Live/Demo banner |

**Live/Demo rule:** If there is no useful active Live event, use a clearly labelled Demo capture. Never remove, obscure, or replace the banner in a way that could mislead judges.

---

# Editing and quality-control checklist

1. Generate narration as one track from the 15 lines above. Make only small wording changes after technical verification; keep the final audio within 2:00.
2. Use generated video for Clips 1–2 and subtle transition plates only. Use authored graphics for Clips 3, 5–9, 13, and 15. Use real product captures for Clips 4, 8–12, and 14 where available.
3. Animate architecture diagrams with direct, non-crossing connectors and progressive reveals. Do not put tiny text into diagrams; split or simplify if the layout becomes crowded.
4. Keep source names, region names, model states, and all numeric values tied to the repo or product. Label demo data as Demo.
5. Keep the plume translucent and probabilistic; keep source tracing ranked/uncertain; show corroboration before a watch state.
6. Add burned-in subtitles only in post-production if useful for accessibility; do not rely on AI-generated subtitles. Check every line against the final narration.
7. Check for consistent colour meaning, loudness, typography, framing, and transition rhythm. Avoid repeating the same map animation back-to-back.
8. Watch the final export with sound off: the architecture, training/evaluation gate, forecast uncertainty, and corroboration workflow should still be understandable.
9. Confirm the total runtime and the Google hackathon submission limit before export. The estimated duration here is 2:03 before the live demo; verify the actual exported duration.

---

# Detailed Cursor prompt: audit the repository and finalize the video package

Copy the following prompt into Cursor with the AeroPulse repository open. Ensure the original `video_generation(2).md` (or the current video script file) is available in the workspace. The prompt deliberately requires code verification before it permits implementation-specific claims in the final script.

```text
You are acting as a senior technical storyteller, ML platform architect, and product-video director for a Google hackathon submission. Review the existing AeroPulse repository and the attached/current video script. The current script has 19 clips and relies too heavily on an abstract map background. I need a professional, evidence-led video plan with about 15 narrated clips, clear architecture diagrams, visible data sources, an accurate explanation of regional model training/evaluation/serving, uncertainty-aware forecasts, and real product evidence.

PRIMARY OBJECTIVE
Create an updated Markdown video script that can be executed with Gemini/Veo plus real UI capture and editable diagrams. Aim for 15 clips of approximately 8 seconds each plus a 3-second end card (about 2:03 before the live demo). Do not require 19 clips. Do not use a map as the default visual in every scene. Make the video useful to technical judges and legible with sound off.

IMPORTANT WORKING RULES
1. Inspect the actual repository before finalizing technical claims. The existing Markdown script is a source of hypotheses, not proof that every feature still exists or is enabled.
2. Do not guess or invent model types, algorithms, features, metrics, accuracy percentages, latency numbers, ETAs, active data feeds, supported hazards, populations exposed, notification capabilities, or current model-serving states.
3. Every technical claim must be linked to a concrete source: source file, configuration, test, command, evaluation report, or product UI. Record the evidence path and relevant symbol/key in a claim audit.
4. Distinguish implemented and tested, implemented but not currently enabled, planned/future, and demo-only behaviour. Do not present planned behaviour as shipped.
5. Preserve the distinction between measured, model-derived, and predicted values where the application makes it. Preserve the rule that source ranking is a heuristic ranking rather than a causal verdict unless code proves otherwise. Forecast plumes must look uncertain, not confirmed.
6. The citizen image model can describe visible content; do not imply it independently confirms a pollution incident. Verify the evidence/corroboration gates and the rule about citizen photos not creating or changing events.
7. Never show Demo data under a Live banner. Do not reveal credentials, API keys, tokens, internal endpoints that should remain private, personal data, or exact private addresses.
8. Do not change the application's production behaviour. This task is for a video package and supporting visual assets, not a feature implementation.
9. If any item cannot be proven from the workspace, mark it “VERIFY / REMOVE FROM FILM” and write a safe alternative narration/visual. Do not stop to ask me questions; make the best evidence-based draft possible.

PHASE 1 — REPOSITORY AUDIT
Search the workspace and build a short evidence map for these areas:
- Overall application architecture, services/apps, main entry points, and how the front end reaches backend functionality.
- All data-source connectors, each source's actual name, source type, regions using it, configuration keys, health/status handling, and missing-source behaviour.
- Ingestion/ETL/feature preparation, validation, timestamp handling, geospatial mapping, spatial index/resolution, provenance metadata, and storage.
- Region configuration packs, their exact IDs, hazards, AQI standards/categories, and the add/validate-region workflow.
- Model training code and command entry points; actual estimator/model family; features used; target variable; history/windowing; preprocessing; output artifacts; per-region/shared-model strategy; and storage of run metadata.
- Evaluation/gating: time-aware split strategies, season checks, baseline metrics, gating thresholds/logic, gate report format, current gate results, and which model versions are actually allowed to serve.
- Prediction/inference scheduling, per-region cycle behaviour, deployment/runtime services, data stores, model version, provenance, and what happens if a regional model is unavailable.
- Forecast/plume implementation: particle/ensemble count, band quantiles or interval semantics, wind inputs, place-arrival calculations, experimental labels, and any limitations.
- Backward trace/source ranking: evidence inputs, scoring/ranking logic, uncertainty language, and UI output.
- Citizen-report processing: sanitization, location/time trust, metadata stripping, AI visual observation schema, numeric-value validation, corroboration conditions, decision table, operator queue, and safety invariants enforced by tests.
- Command Centre and Ask AeroPulse: actual UI pages, grounding/citations, what data is displayed, and how Live/Demo mode is shown.
- Google Cloud service names (such as Cloud Run Jobs, BigQuery, Cloud Storage) only where deployment/configuration files prove usage.

Use targeted search and follow references into the source/config/tests. Do not summarize file names without reading the relevant code. Inspect generated reports/artifacts where present. Do not run destructive commands, deploy anything, or make a production call that changes state.

PHASE 2 — BUILD A CLAIM AUDIT
Create `docs/video/aeropulse_video_claim_audit.md` with a table containing:
- Claim/phrase proposed for the video
- Status: VERIFIED / PARTIAL / NOT VERIFIED / FUTURE / DEMO ONLY
- Exact repository evidence path(s) and relevant function/config/test/report
- Safe wording permitted in narration/on-screen text
- Recommended visual evidence (diagram, UI capture, test/report, or remove)

At minimum audit these claims from the old video script rather than assuming they remain true:
- Current regional IDs and regional AQI scales/hazard profiles
- Connector/source inventory and regional coverage
- “No code changes” when adding a region
- H3 resolution and “1 km cell” wording
- Measured/model-derived/predicted provenance labels
- Model type, training data/features and per-region training strategy
- `purged_rolling_origin`, `season_check`, or any temporal evaluation claims
- Beating persistence at 1–24 hour horizons in North India and Singapore
- The current NSW no-served-model/rules/degraded state
- Hourly per-region cycle and actual Google Cloud components
- 200-particle ensemble and P50/P90 semantics
- Place arrival/ETA behaviour
- Source ranking and whether any confidence values are calibrated
- Citizen-report sanitization and the rule for not using image observations as numeric measurements
- Fire + wind + station corroboration and operator decision branches
- Ask AeroPulse grounding/citations

PHASE 3 — FINALIZE A 15-CLIP STORY
Create `docs/video/aeropulse_video_script_revised.md` with:
- A concise 15-clip table, timestamps, duration, message, narration, and primary visual.
- A story arc: problem → regional use case → architecture → sources → data preparation → region packs → training → validation/gate → scheduled serving → forward forecast → backward source reasoning → citizen report → independent corroboration → real UI/copilot → end-to-end close.
- Approximately 8 seconds per clip and a 3-second end card. Keep narration comfortably short (normally 14–18 words per clip); one narrator/continuous narration track is preferred to voice generated separately in each clip.
- For each clip: intent, exact narration, on-screen diagram/shot, specific labels, animation order, real product insert needed (if any), generation prompt only where generative footage is genuinely useful, and editor notes.
- Explicit production notes that generative video should NOT draw architecture text, charts, dashboards, or precise UI. Use authored SVG/HTML/Remotion/other editable vector assets and real product captures for these.
- A list of real recordings to capture, with which page/state each one must demonstrate and whether the correct banner must say Live or Demo.
- Technical “do not say/show” guardrails, sound-off readability checks, edit/audio workflow, and final submission QC.

Use these storytelling priorities:
A. Opening footage should be short; do not spend 30 seconds on atmospheric clips.
B. Show a true architecture diagram in the first 25 seconds. It should include sources/connectors, preparation/feature grid, region-specific config/model path, evaluation/serving gate, and outputs. Use only verified component names.
C. Make regional model training visible as a pipeline using actual training code and actual features. If the model algorithm cannot be proven, label it only as “regional forecasting model” or equivalent.
D. Show validation as a gate: temporal/seasonal holdouts and comparison with the baseline only when verified. Show the current per-region gate state only from actual reports/config.
E. Show real forecast evidence (plume/bands/place ETAs) and clearly label predictions experimental when that is the application state.
F. Show backward trace as ranked likely sources with evidence, never as a causal verdict.
G. Make citizen-photo observation, separate corroboration, and the operator-review branch easy to understand visually.
H. Reserve at least one major clip for real Command Centre + Ask AeroPulse footage with an actual cited answer.
I. Do not present volcanic ash tracking, population exposure, push/SMS alerts, or numerical accuracy unless the current repo truly supports them and the claim audit explicitly verifies them.

PHASE 4 — CREATE EDITABLE VISUAL ASSETS
Create `docs/video/assets/` (or a similarly clear directory) with source files for diagrams used in the video. Prefer SVG for static diagrams and HTML/React/Remotion if animation is helpful and the workspace already supports it. Do not add an unnecessary framework or heavyweight dependency just to create a few visuals.

Required assets:
1. `architecture_overview.svg` — five-layer architecture, clear non-crossing connectors, grouping, concise labels, correct verified component names.
2. `data_sources.svg` — actual source/connectors, data types, and a visual difference between active/optional/not-configured only if those states are supported; do not hard-code a state that changes over time.
3. `regional_training_evaluation.svg` — separate regional lanes, real training/feature path, validation strategy, baseline gate, serving/fallback outcomes.
4. `forecast_and_source_trace.svg` — distinguish forward probabilistic plume from backward ranked-source evidence; no fake values or percentages.
5. `citizen_corroboration.svg` — observation → three independently checked signals → watch workflow or operator review; explicit note that a photo alone is not confirmation if the code enforces it.

Design requirements: 16:9-safe layout, dark navy/cyan/amber/coral palette, readable typography, ample padding, restrained iconography, consistent arrows, accessible contrast, and no overlapping or crossing connectors where avoidable. Keep all labels editable. If the repository already has an established visual style, reuse it. Add a README describing how to open/export the assets and which clips use them.

If the repository cannot render SVG/HTML animation directly, provide simple editable SVG assets and explicit animation instructions in the Markdown rather than introducing a new runtime. Do not create fake charts with invented data; link chart callouts to the real report/UI capture that should be used.

PHASE 5 — SUPPORTING DELIVERABLES
Also create:
- `docs/video/recording_checklist.md` — exact screens/states to capture, resolution, data/banner requirements, privacy checks, and shot length.
- `docs/video/shot_list.csv` — clip number, timecode, narration, visual source (generated plate / diagram / real UI), asset path, overlay text, and verification dependency.

QUALITY GATES BEFORE COMPLETION
- Ensure exactly 15 narrated clips plus one 3-second end card unless timing arithmetic makes a slight adjustment necessary; state actual total runtime.
- No two consecutive clips should be primarily the same generic map view.
- Verify that the architecture diagram can be understood in a few seconds and has no messy/crossing connectors.
- Every model-training/evaluation claim traces to code, config, tests, or reports.
- Every UI insert has a recording instruction and an explicit Live/Demo integrity requirement.
- No invented metrics, region status, source status, labels, or outputs.
- Every unsupported claim is removed or labelled “verify before export.”
- All links/asset paths in the Markdown must point to files that actually exist in the workspace.
- Do not stop after writing an outline. Produce the complete script, claim audit, recording checklist, shot list, and editable diagram sources wherever the workspace allows.

At the end, return a concise summary of files created, major changes from the old 19-clip storyboard, key claims that could not be verified, and any screenshots/report captures still required. Do not claim a feature is implemented merely because the old Markdown says so.
```

---

## Suggested folder structure after using Cursor

```text
docs/
  video/
    aeropulse_video_script_revised.md
    aeropulse_video_claim_audit.md
    recording_checklist.md
    shot_list.csv
    assets/
      README.md
      architecture_overview.svg
      data_sources.svg
      regional_training_evaluation.svg
      forecast_and_source_trace.svg
      citizen_corroboration.svg
```

## What changed from the old script

- Reduced the storyboard from 19 clips to 15, keeping the technical story but removing repeated explanatory beats.
- Shortened the cinematic opening and moved the full architecture diagram to the first 24 seconds.
- Replaced repeated abstract map scenes with explicit diagrams, regional training/evaluation visuals, evidence views, and real UI footage.
- Made the regional model lifecycle visible: historical data → features → training → temporal/seasonal evaluation → gate → eligible model or fallback.
- Made data-source coverage and connector status explicit rather than implying all feeds are active in all regions.
- Preserved the uncertainty and citizen-safety guardrails from the original script.
- Added a repository audit requirement so Cursor checks current code/config/reports before reusing the old script's implementation claims.
