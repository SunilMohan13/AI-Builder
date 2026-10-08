import { config } from 'maplibre-gl'

/**
 * MapLibre 6 loads `./maplibre-gl-worker.mjs` next to the bundled main script.
 * Vite emits that bundle under `/assets/`, so the relative URL 404s and the SPA
 * fallback returns index.html — MIME "text/html", and the basemap never paints.
 * The Vite plugin serves the official worker (and the module it imports) from
 * site root with a JavaScript content type. Dev and preview both need that,
 * because a `.mjs` missing from Vite's public-file index is answered as HTML.
 */
config.WORKER_URL = '/maplibre-gl-worker.mjs'
