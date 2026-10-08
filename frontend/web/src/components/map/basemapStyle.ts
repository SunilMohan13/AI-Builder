import type { LayerSpecification, StyleSpecification } from 'maplibre-gl'

// Both styles use the same OpenFreeMap planet tiles. Fiord is the blue-gray
// dusk map. Liberty is the light street map. Fiord ships the shaded-relief
// source but does not draw it, so the dusk style adds a dim raster under the
// vectors. Land stays darker than the roads and place names.
export type BasemapTheme = 'dark' | 'light'

const STYLE_URL: Record<BasemapTheme, string> = {
  dark: 'https://tiles.openfreemap.org/styles/fiord',
  light: 'https://tiles.openfreemap.org/styles/liberty',
}

const THEME_KEY = 'aeropulse.basemap'

export function loadBasemapTheme(): BasemapTheme {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function saveBasemapTheme(theme: BasemapTheme) {
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Private browsing can refuse storage. The choice still applies this visit.
  }
}

function withDuskTerrain(style: StyleSpecification): StyleSpecification {
  const layers: LayerSpecification[] = style.layers.map((layer) => {
    if (layer.id !== 'landuse_residential' || layer.type !== 'fill') return layer
    return {
      ...layer,
      paint: { ...layer.paint, 'fill-color': '#3a4560', 'fill-opacity': 0.55 },
    }
  })
  const sources = style.sources ?? {}
  if (!layers.some((layer) => layer.type === 'raster') && 'ne2_shaded' in sources) {
    const at = layers.findIndex((layer) => layer.id === 'background') + 1
    layers.splice(Math.max(at, 0), 0, {
      id: 'natural_earth',
      type: 'raster',
      source: 'ne2_shaded',
      paint: {
        'raster-opacity': ['interpolate', ['linear'], ['zoom'], 0, 0.35, 6, 0.18],
        'raster-saturation': -0.25,
        'raster-brightness-max': 0.7,
      },
    })
  }
  return { ...style, layers }
}

function graticule(stepDeg: number) {
  const features = []
  for (let lon = -180; lon <= 180; lon += stepDeg) {
    features.push({
      type: 'Feature' as const,
      properties: {},
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [lon, -85],
          [lon, 85],
        ],
      },
    })
  }
  for (let lat = -80; lat <= 80; lat += stepDeg) {
    features.push({
      type: 'Feature' as const,
      properties: {},
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [-180, lat],
          [180, lat],
        ],
      },
    })
  }
  return { type: 'FeatureCollection' as const, features }
}

/**
 * Picks a style before the map is built. A single reachability check is more
 * trustworthy than reacting to MapLibre's error stream, and it avoids the
 * visible flash of swapping styles after the fact.
 */
export async function resolveBasemapStyle(
  theme: BasemapTheme = 'light',
  timeoutMs = 8000,
): Promise<{ style: StyleSpecification; offline: boolean }> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const res = await fetch(STYLE_URL[theme], { signal: controller.signal })
    clearTimeout(timer)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    // Hand MapLibre the document itself. Giving it the URL makes it fetch the
    // style again, and that second request was failing (status 0) so the
    // canvas stayed the empty background colour.
    const loaded = (await res.json()) as StyleSpecification
    return { style: theme === 'dark' ? withDuskTerrain(loaded) : loaded, offline: false }
  } catch {
    return { style: FALLBACK_STYLE, offline: true }
  }
}

/**
 * Network-free basemap: a one-degree graticule. Keeps Demo usable when tile
 * hosting is blocked; the region outline and data layers come from deck.gl.
 */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: { graticule: { type: 'geojson', data: graticule(1) } },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#121820' } },
    {
      id: 'graticule',
      type: 'line',
      source: 'graticule',
      paint: { 'line-color': '#5b7c99', 'line-width': 1.25, 'line-opacity': 0.9 },
    },
  ],
}
