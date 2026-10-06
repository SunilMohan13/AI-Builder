# AeroPulse hackathon demo

## 90-second judge tour

1. **Overview** → click **Start judge tour** (or top bar **Judge tour**).
2. The app auto-navigates:
   - Live map (corridor) → fire + plume
   - Event **EVT-1024** → action brief + citizen corroboration
   - Evidence explorer
   - Forecast (model vs persistence baseline)
   - Population risk
   - Copilot (auto-question with citations)
   - Back to Overview

Caption bar at top explains each step. **Stop tour** anytime.

## Manual pitch (backup)

| Step | Route | Talking point |
|------|--------|----------------|
| 1 | `/map?scene=corridor` | FIRMS + CPCB fuse; not a generic AQI app |
| 2 | `/events/EVT-1024` | Four confidence dimensions; likelihood ≠ causality |
| 3 | `/evidence` | Graph of independent connectors |
| 4 | `/forecast` | Model must beat persistence baseline |
| 5 | `/risk` | Exposure for coordination |
| 6 | `/copilot` | LLM explains retrieved evidence only |

## Deploy + QR

- Set `VITE_DEMO_URL` in Netlify to your public URL (optional; defaults to current origin).
- Overview **Hackathon demo** card shows QR + copy link.

## Architecture one-liner

Connectors (CPCB, FIRMS, IMD, CAMS) → Kafka → event engine → FastAPI `/api/v1` → this UI. Mock data in the UI; contracts in `libs/contracts`.

## Map / globe feature tour

| Feature | Where |
|---------|--------|
| **Enter Punjab–Delhi theater** | Globe → orange button on map bar → corridor +6h |
| **Explain this cell** | Corridor → click grid → Copilot with citations |
| **Scenario lab** (top-right panel) | Wind ±30°, baseline plume, GRAP zone, exposure ribbon, **Play map story** |
| **GRAP banner** | Appears when plume intersects NCR (mock) |
| **Snapshot** | Corridor → camera icon on map toolbar |
| **Fire season** | Globe → Scenario panel toggle |
