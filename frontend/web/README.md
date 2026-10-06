# AeroPulse map

The operator UI. Demo and Live are both real products.

## Demo only (no API)

1. `cd frontend/web`
2. `npm install`
3. `npm run dev`
4. Open http://localhost:5173 and leave the switch on **Demo**.

## Live (API on this machine)

1. Start the stack from the repository README (Docker Compose).
2. Copy `.env.example` to `.env.local`.
3. Put a viewer token in `VITE_API_TOKEN` (command is in that example file). Leave `VITE_API_BASE` empty.
4. `npm run dev` and switch the header to **Live**.

Live never fills gaps with Demo numbers. If a call fails, a banner names it.

## Checks

```bash
npm run build
npm run lint
```
