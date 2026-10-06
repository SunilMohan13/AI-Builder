import { copyFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const rootDir = dirname(fileURLToPath(import.meta.url))

const MAPLIBRE_WORKER_FILES = ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs'] as const

function copyMaplibreWorkers(): Plugin {
  const srcDir = join(rootDir, 'node_modules/maplibre-gl/dist')

  const copyInto = (destDir: string) => {
    mkdirSync(destDir, { recursive: true })
    for (const name of MAPLIBRE_WORKER_FILES) {
      copyFileSync(join(srcDir, name), join(destDir, name))
    }
  }

  return {
    name: 'copy-maplibre-workers',
    buildStart() {
      copyInto(join(rootDir, 'public'))
    },
    closeBundle() {
      copyInto(join(rootDir, 'dist'))
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), copyMaplibreWorkers()],
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
