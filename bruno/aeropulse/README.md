# Checking the API

Use this Bruno collection to call the same API the map uses.

1. Start the stack (see the root README).
2. Open the `bruno/aeropulse` folder in Bruno.
3. Select the **local** environment (base `http://127.0.0.1:8000`).
4. Paste a viewer token into `token`. Do not commit it.
5. Call a list route first, then copy `eventId` / `gridId` / `reportId` into the environment for detail routes.

Hazard and peak responses that say **degraded** are a simple carry-forward, not a trained probability. Read **calibrated** before treating a score as a percent.
