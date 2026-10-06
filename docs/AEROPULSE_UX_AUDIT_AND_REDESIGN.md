# AeroPulse — UX audit and redesign

A live-browser audit of the running application, the findings it produced, and the changes made
in response.

## 1. How this audit was performed

The application was driven in a real Chromium instance (Playwright 1.49) against the running
Docker stack — web on `127.0.0.1:5173`, API on `127.0.0.1:8000` — not read from source. Every
route was visited in **both Demo and Live mode**, screenshotted at 1440×900, and its rendered
text, card count, canvas count and every numeric value with a unit extracted from the live DOM.
The same harness was re-run after the changes, and again per view level, so every claim below is
a before/after comparison of what the browser actually painted.

Console errors: **0 before, 0 after**. No finding in this document is a crash; they are all
comprehension and honesty problems.

The audit was limited in one respect worth stating: the API was serving its Punjab replay seed
rather than live CPCB/FIRMS ingest, because the connector workers are not running on this stack.
Live mode was therefore audited against contract-valid replay data. That does not affect any
finding about layout, language or internal contradiction, but it means "Live" figures below are
replay figures.

## 2. Page inventory as discovered

Nine routes were found. `/events` redirects to `/events/:id`, so there is no event *list* route —
the nav item labelled "Events" opened a single hardcoded event.

| Route | Purpose | Primary user | Primary question | Repeated info | Developer-only info | Action taken |
|---|---|---|---|---|---|---|
| `/` | Briefing | All | How bad is it? | Source freshness (= `/sources`), map (= `/map`) | Screen-job note, event IDs, likelihood % | Restructured around the 5-level hierarchy |
| `/map` | 1 km geospatial | Ops | Where is it? | Fusion ticker (= `/sources`) | Raw endpoint list, grid resolution, scenario lab | Consolidated to one control panel |
| `/events/:id` | Investigation | Ops / judge | Why is this one event? | Confidence shown twice; actions shown twice | Event IDs, four bare percentages | De-duplicated; actions un-buried |
| `/forecast` | Trajectory | Ops / decision | Where is it heading? | Map chrome (= `/map`), horizon scrubber shown twice | Skill-vs-persistence | Map chrome removed; duplicate scrubber removed |
| `/risk` | Exposure | Decision | Who is affected? | Map chrome (= `/map`) | — | Map chrome removed |
| `/evidence` | Fusion graph | Judge | What corroborates this? | — | — | Left as is |
| `/sources` | Ingestion health | Ops | Can I trust the screen? | — | Model registry, artifact IDs, R² | Registry moved to Advanced |
| `/copilot` | Q&A | All | Why? | — | — | Renamed "Ask AeroPulse" |
| `/citizen` | Reports + upload | Citizen | Can I contribute? | — | — | Left as is |

## 3. The single biggest finding

**The application spoke to its own developers.** Almost every screen carried a sentence written
for a reviewer of the code rather than a reader of the data. On the Live overview, the standing
explanation was:

> Live — the UI is calling http://127.0.0.1:8000. On this Docker stack Timescale has no fused
> events yet, so the API answers with the Punjab replay seed (same episode as Demo, as
> contract-valid records). That is fixture replay, not CPCB/FIRMS ingest. Connector workers are
> not running.

Every fact in that paragraph is true and worth keeping. None of it belongs in front of someone
asking whether it is safe to go outside.

## 4. Contradictions found

These are the cases where two things on screen could not both be true. They are listed first
because a contradiction destroys trust faster than any amount of clutter.

1. **A rising arrow above a falling forecast.** Live showed `PM2.5 185 ↑` in the KPI strip while
   the forecast panel immediately beside it read 149 → 125 → 94. The arrow was the literal
   `trend="up"`, hardcoded.
2. **"Healthy" with unknown freshness.** Every live source rendered a green *Healthy* badge and
   `unknown` in the freshness column. The adapter was mapping the registry's `enabled` flag to a
   health status — asserting a measured state from a configuration fact.
3. **Hardcoded status line.** The footer read `Data freshness: 2 min · Models: Production` as
   string literals, in both modes, while the Sources page said freshness was unknown.
4. **A legend for layers that did not exist.** The map legend captioned "Model plume", "Baseline
   persistence" and "Exposure ribbon" unconditionally. All three are demo-only scenario layers;
   Live never draws them.
5. **"Active events 2" above a list of 5.** The KPI counted only `ACTIVE`; the catalog below it
   listed every event.
6. **Two disagreeing peaks.** The Forecast outlook said "Peak expected 260 µg/m³"; the hazard
   panel below said "Highest peak 213". Different scopes (Delhi NCR trajectory vs worst single
   grid cell), identically labelled.
7. **A fabricated agreement score.** The map ticker read `FUSION 4/6 AGREE`, computed as
   `Math.min(healthyCount, 4)`. Nothing in that expression compares sources.
8. **Trend sparklines with no trend.** Source rows drew a seeded-random sparkline from
   `quality ?? 0`, inventing a history for sources that report no quality at all.
9. **Hardcoded forecast skill.** "Forecast confidence 89%" and "vs persistence −18% error" were
   literals rendered in Live.

## 5. Duplication found

- **Three separate controls for one scene switch**, plus a fourth in the toolbar: the header
  Corridor/Globe toggle, the floating globe bar, and the display panel.
- **Two of them physically overlapped.** The globe bar sat at `sm:bottom-36` and the layer chips
  at `bottom-32`, both centred; the chip strip's last two toggles were unreachable. The
  `bottom-40` override in `AeroMap` lost to the `sm:` variant it did not replace.
- **The full map control stack rendered on Forecast and Risk**, over maps roughly 200 px tall.
  Both passed `showControls={false}` but not `embedded`, so the display panel and scenario lab
  covered most of the map.
- **Confidence shown twice on one screen** — the Detect rail and the bottom meter strip.
- **The action list rendered twice** on the event page: once in the action brief, once in a card.
- **Two scrubbers for one value** on Forecast: the page's horizon buttons and the map timeline.
- **Source freshness in three places** with different values: the top bar, the footer, and the
  Overview panel.
- **A "Settings" nav link that navigated to `/sources`** — a second, mislabelled door onto a page
  already in the nav. There is no settings screen.

## 6. The missing level: what should I do

Every screen could say how bad the air was. None said what to do about it. The operator action
brief existed, but it sat inside a `<details>` collapsed by default, at the bottom of the event
page — two navigations and a click from the front door.

## 7. Progressive disclosure: Simple and Advanced

The audit kept producing the same shape of finding: information that is correct, valuable to
somebody, and wrong for the person currently looking at it. Deleting it would have cost the
project its scientific honesty; leaving it made every screen a debug console.

A **Simple / Advanced** switch now sits in the top bar (`context/ViewLevelContext.tsx`).
Advanced is strictly additive — it never hides anything Simple shows, so a reader cannot lose
information by switching. It is presentation only: it changes no request, no query key and no
value.

Advanced reveals: confidence decomposition, model registry and artifact IDs, event IDs, the API
endpoints behind a screen, grid resolution, per-cell hazard scores, the scenario lab, the fusion
ticker, and the replay/Timescale explanation.

## 8. Redesigned dashboard hierarchy

The Overview now reads top to bottom as five answers:

1. **Current status** — AQI, PM2.5 with a *derived* direction arrow, active events of total
   tracked, population at risk.
2. **What is happening** — one sentence: *"Agricultural burning event in Punjab → Haryana →
   Delhi NCR — air quality is severe, and getting worse over the next 3 hours."*
3. **Where it is moving** — three explicit links: see the evidence, where it is heading, who is
   affected.
4. **What happens next** — the +1/+3/+6/+12 h forecast peek.
5. **What should I do** — a new health-guidance block derived from the PM2.5 band, split into
   *Everyone* and *Sensitive groups*, and captioned as standing guidance rather than a
   prediction.

## 9. Map-first consolidation

One panel now owns layers, scene and basemap. Layers are named for what they answer ("Air
quality", "Predicted plume", "Population") rather than for their data source, each with a
one-line hint, and the header shows how many of them are on.

Defaults dropped from four layers to two. The map opens on *what is in the air* and *what is
burning*; wind and the predicted plume are a deliberate second click. The narrated 60-second
story and the Forecast page switch them on themselves, so the demo is unaffected.

## 10. Changes made

### P0 — correctness

| Fix | File |
|---|---|
| `enabled` no longer renders as `Healthy`; now `Registered`/`Disabled`, neutral badge | `api/adapters.ts`, `types/index.ts`, `pages/Sources.tsx` |
| Trend arrow derived from the forecast on the same screen | `pages/Overview.tsx` |
| Footer freshness derived, or "not reported" | `components/layout/FooterStatus.tsx` |
| Legend hides scenario layers outside Demo | `components/map/MapLegend.tsx` |
| Active-event KPI reads "N of M tracked" | `pages/Overview.tsx` |
| Peak figures scoped ("Peak for Delhi NCR" / "Worst single area") | `pages/Forecast.tsx`, `components/events/HazardOutlook.tsx` |
| Ticker reports "sources reporting", not fabricated agreement | `components/map/MapFusionStrip.tsx` |
| Sparkline suppressed when quality is null | `pages/Sources.tsx` |
| Hardcoded forecast skill restricted to Demo | `pages/Forecast.tsx` |

### P1 — information architecture

| Fix | File |
|---|---|
| Simple / Advanced view level | `context/ViewLevelContext.tsx`, `components/layout/ViewLevelToggle.tsx` |
| Plain-language mode note; endpoint detail to Advanced | `components/common/Provenance.tsx` |
| Health guidance ("what should I do") | `components/common/HealthGuidance.tsx` |
| Situation block rewritten as a sentence | `pages/Overview.tsx` |
| One map control panel; duplicate chips and globe bar removed | `components/map/MapViewControls.tsx`, `MapControls.tsx`, `AeroMap.tsx` |
| Map chrome removed from Forecast and Risk | `pages/Forecast.tsx`, `pages/Risk.tsx` |
| Nav grouped Now / Next / Why / Inputs; fake Settings link removed | `components/layout/Sidebar.tsx` |
| Action brief no longer collapsed; duplicate action card removed | `pages/EventDetail.tsx` |
| Duplicate confidence bars removed; plain summary in Simple | `components/events/DetectWorkspace.tsx` |
| Model registry to Advanced | `pages/Sources.tsx` |
| Tour captions rewritten in plain language | `demo/judgeTourSteps.ts` |

### Regression found and fixed during re-audit

Opening the action brief by default caused the Detect workspace and the brief to compete for the
same flex height, and the brief rendered over the intelligence rail. The event page is now a
single scrolling column with a fixed-height workspace.

## 11. Measured effect

Rendered text and panel counts, Demo mode, before → after:

| Route | Text (chars) | Panels |
|---|---|---|
| Live Map | 1236 → 728 | 6 → 3 |
| Globe | 1799 → 808 | 5 → 4 |
| Forecast | 2362 → 1295 | 10 → 5 |
| Risk | 1623 → 1208 | 8 → 5 |
| Sources | 1993 → 801 | 3 → 2 |
| Events | 1511 → 2869 | 8 → 7 |

Events is the one route that grew, and deliberately: the action brief that was behind a click is
now on the page.

## 12. Verification

- `npx tsc --noEmit` — clean
- `npm run lint` — no errors in `src/`
- `npm run build` — succeeds
- `uv run pytest tests/unit tests/contract -q` — 318 passed
- Browser re-audit, all 9 routes × 2 modes × 2 view levels — 0 console errors

No API call, polling interval, query key or backend behaviour was changed. Every change is
presentation.

## 13. What was deliberately not changed

- **Nothing was removed as a feature.** The scenario lab, fusion ticker, model registry,
  per-cell hazard scores and confidence decomposition all still exist, in Advanced.
- **The Evidence graph** remains demo-shaped in Live because `graph.v1` carries no layout
  coordinates. That is a backend gap, already on the project's backlog.
- **`risk_band()` thresholds** are still presentation values, not an operator-agreed
  classification.
- **Population figures** still come from the five-cell licensed fixture.

## 14. Remaining recommendations (P2–P3)

- ~~**P2** — The Detect map's labels collide at the plume origin.~~ **Fixed.** Three causes, all
  in `EventDetectMap.tsx`. The node table was keyed by evidence *category*, so two items sharing a
  category resolved to the same coordinate and their labels drew exactly on top of each other.
  Those category bearings were also clustered into one arc, crowding the labels that did differ.
  And the source place label sat on the hub, underneath the ring and the plume origin. Evidence
  now takes evenly spaced slots on a staggered two-radius ring, labels radiate outward with a
  per-node text anchor, provider names are abbreviated (the rail carries the full name), and the
  place label is pushed beyond the ring along a reserved bearing that the slots skip.

  `CollisionFilterExtension` was tried first and rejected: in this renderer it filtered out
  *every* label in both text layers, and a polish fix whose failure mode is "all labels vanish"
  is not worth the dependency. The geometry is deterministic and verifiable instead. Labels can
  still meet the *basemap's* own place names, which is inherent to drawing over a labelled
  basemap and is much less severe than what was there before.
- **P2** — Copilot renders ~60% empty space before the first question.
- **P2** — Citizen report map is a fourth map style, with no legend and no shared controls.
- **P3** — `/events` has no list view; the nav entry deep-links to one event.
- **P3** — Source counts still differ by surface (Overview shows 5, Sources shows 6 in Demo and
  7 in Live) because each reads a different slice.
