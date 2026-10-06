import type { StyleSpecification } from 'maplibre-gl'
import { CORRIDOR_LOCATIONS } from '../../utils/geo'

export const CARTO_STYLE_URL =
  'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

/** Lighter basemap for the “satellite / map” toggle in globe command view. */
export const CARTO_VOYAGER_STYLE_URL =
  'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json'

function graticule(stepDeg: number) {
  const features = []
  for (let lon = 60; lon <= 100; lon += stepDeg) {
    features.push({
      type: 'Feature' as const,
      properties: {},
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [lon, 5],
          [lon, 40],
        ],
      },
    })
  }
  for (let lat = 5; lat <= 40; lat += stepDeg) {
    features.push({
      type: 'Feature' as const,
      properties: {},
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [60, lat],
          [100, lat],
        ],
      },
    })
  }
  return { type: 'FeatureCollection' as const, features }
}

/**
 * Swaps in the bundled style only when the remote basemap genuinely cannot
 * render.
 *
 * Being conservative matters more than being quick: replacing a working
 * basemap with the bare fallback is far worse than waiting a moment. Two
 * routine events must not count as failure — requests aborted while the camera
 * moves (deck.gl drives the camera, so this happens constantly) and 404s for
 * tiles outside coverage. Once any tile has rendered the basemap is proven, so
 * we never swap after that.
 */
export function attachBasemapFallback(
  map: import('maplibre-gl').Map,
  onFallback?: () => void,
): void {
  let fellBack = false
  let tileRendered = false
  let failures = 0

  map.on('sourcedata', (e) => {
    if (e.tile) tileRendered = true
  })

  const swap = () => {
    if (fellBack || tileRendered) return
    fellBack = true
    onFallback?.()
    map.setStyle(FALLBACK_STYLE)
  }

  map.on('error', (e) => {
    const err = e as unknown as {
      sourceId?: string
      error?: { status?: number; message?: string }
    }

    // Only genuine transport failures count. `isStyleLoaded()` is deliberately
    // not used as a health signal: it reports false in states where the style
    // is in fact fine, which previously swapped out a working basemap.
    const status = err.error?.status
    if (status === 404 || /abort/i.test(err.error?.message ?? '')) return
    failures += 1
    if (failures >= 8) swap()
  })
}

/**
 * Picks a style before the map is built. A single reachability check is more
 * trustworthy than reacting to MapLibre's error stream, and it avoids the
 * visible flash of swapping styles after the fact.
 */
export async function resolveBasemapStyle(
  timeoutMs = 4000,
): Promise<{ style: string | StyleSpecification; offline: boolean }> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const res = await fetch(CARTO_STYLE_URL, { signal: controller.signal })
    clearTimeout(timer)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return { style: CARTO_STYLE_URL, offline: false }
  } catch {
    return { style: FALLBACK_STYLE, offline: true }
  }
}

/** Corridor cities, so the offline basemap still gives a sense of place. */
const cities = {
  type: 'FeatureCollection' as const,
  features: CORRIDOR_LOCATIONS.filter((l) => !l.name.includes('cluster')).map((l) => ({
    type: 'Feature' as const,
    properties: { name: l.name },
    geometry: { type: 'Point' as const, coordinates: [l.lon, l.lat] },
  })),
}

/**
 * Network-free basemap. Keeps the demo usable when tile hosting is blocked;
 * deck.gl layers carry the actual environmental information either way. No
 * corridor rectangle here — a filled box reads as a UI artefact, not geography.
 */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  glyphs: undefined,
  sources: {
    graticule: { type: 'geojson', data: graticule(1) },
    cities: { type: 'geojson', data: cities },
  },
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#070b12' },
    },
    {
      id: 'graticule',
      type: 'line',
      source: 'graticule',
      paint: { 'line-color': '#151f30', 'line-width': 1, 'line-opacity': 0.9 },
    },
    {
      id: 'city-dots',
      type: 'circle',
      source: 'cities',
      paint: {
        'circle-radius': 3,
        'circle-color': '#334155',
        'circle-stroke-color': '#475569',
        'circle-stroke-width': 1,
      },
    },
  ],
}
