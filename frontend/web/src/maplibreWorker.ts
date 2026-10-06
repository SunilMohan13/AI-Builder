import { config } from 'maplibre-gl'

/**
 * MapLibre 6 loads `./maplibre-gl-worker.mjs` next to the bundled main script.
 * Vite emits that bundle as `/assets/index-*.js`, so the worker 404s and Netlify
 * SPA fallback returns index.html — MIME "text/html" and a blank globe.
 * The Vite plugin copies the official worker + shared module to site root.
 */
config.WORKER_URL = '/maplibre-gl-worker.mjs'
