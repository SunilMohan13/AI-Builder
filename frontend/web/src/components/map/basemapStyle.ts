import type { StyleSpecification } from 'maplibre-gl'

export const CARTO_STYLE_URL = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

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

/**
 * Network-free basemap: a one-degree graticule. Keeps Demo usable when tile
 * hosting is blocked; the region outline and data layers come from deck.gl.
 */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: { graticule: { type: 'geojson', data: graticule(1) } },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#070b12' } },
    {
      id: 'graticule',
      type: 'line',
      source: 'graticule',
      paint: { 'line-color': '#151f30', 'line-width': 1, 'line-opacity': 0.9 },
    },
  ],
}
