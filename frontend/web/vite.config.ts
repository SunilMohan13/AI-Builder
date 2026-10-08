import { copyFileSync, createReadStream, existsSync, mkdirSync, statSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const rootDir = dirname(fileURLToPath(import.meta.url))

const MAPLIBRE_WORKER_FILES = ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs'] as const

/** Worker plus the sibling module and source maps it imports by relative URL. */
const MAPLIBRE_SERVED_FILES = new Set<string>([
  ...MAPLIBRE_WORKER_FILES,
  'maplibre-gl-worker.mjs.map',
  'maplibre-gl-shared.mjs.map',
])

function maplibreWorkers(): Plugin {
  const srcDir = join(rootDir, 'node_modules/maplibre-gl/dist')

  const copyInto = (destDir: string) => {
    mkdirSync(destDir, { recursive: true })
    for (const name of MAPLIBRE_WORKER_FILES) {
      copyFileSync(join(srcDir, name), join(destDir, name))
    }
  }

  // Vite indexes `public/` before `buildStart`, so a copy made in that hook
  // is invisible to the static middleware. A request for the missing `.mjs`
  // then hits the SPA fallback and comes back as index.html (`text/html`).
  // Module workers refuse that body, and MapLibre never decodes a tile.
  const serve = (req: IncomingMessage, res: ServerResponse, next: (err?: unknown) => void) => {
    const name = (req.url ?? '').split('?')[0]?.replace(/^\//, '') ?? ''
    if (!MAPLIBRE_SERVED_FILES.has(name)) {
      next()
      return
    }
    const file = join(srcDir, name)
    if (!existsSync(file)) {
      next()
      return
    }
    const stat = statSync(file)
    res.statusCode = 200
    res.setHeader(
      'Content-Type',
      name.endsWith('.map') ? 'application/json; charset=utf-8' : 'text/javascript; charset=utf-8',
    )
    res.setHeader('Content-Length', stat.size)
    res.setHeader('Cache-Control', 'no-cache')
    createReadStream(file).pipe(res)
  }

  return {
    name: 'maplibre-workers',
    configureServer(server) {
      server.middlewares.use(serve)
    },
    configurePreviewServer(server) {
      server.middlewares.use(serve)
    },
    buildStart() {
      copyInto(join(rootDir, 'public'))
    },
    closeBundle() {
      copyInto(join(rootDir, 'dist'))
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), maplibreWorkers()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  optimizeDeps: {
    // MapLibre spawns its tile-decoding worker via `new Worker(new URL(...))`.
    // Dependency pre-bundling rewrites that specifier to a file it never
    // emits, so the worker 404s and MapLibre aborts every style, sprite and
    // tile request — the basemap silently stays blank. Serving MapLibre
    // unbundled keeps the worker URL resolvable.
    exclude: ['maplibre-gl'],
  },
})
