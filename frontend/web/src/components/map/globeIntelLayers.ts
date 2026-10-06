import type { Map } from 'maplibre-gl'
import { hashNoise } from '../../utils/seededRandom'

const SENSOR_SOURCE = 'aero-intel-sensors'
const ROUTE_SOURCE = 'aero-intel-routes'
const ALERT_SOURCE = 'aero-intel-alerts'
const FIRE_SEASON_SOURCE = 'aero-fire-season'

const HUBS: [number, number][] = [
  [77.2, 28.6],
  [72.8, 19.0],
  [103.8, 1.35],
  [55.3, 25.2],
  [37.6, 55.75],
  [2.35, 48.85],
  [-0.12, 51.5],
  [13.4, 52.5],
  [139.7, 35.7],
  [121.5, 31.2],
  [114.1, 22.3],
  [31.2, 30.0],
  [-74.0, 40.7],
  [-118.2, 34.0],
  [151.2, -33.8],
  [18.4, -33.9],
]

function buildSensors(): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = []
  for (let i = 0; i < 220; i++) {
    const hub = HUBS[i % HUBS.length]
    const lon = hub[0] + (hashNoise(i, 4) - 0.5) * 14
    const lat = hub[1] + (hashNoise(i, 7) - 0.5) * 10
    const tier = hashNoise(i, 9) > 0.72 ? 'primary' : 'node'
    features.push({
      type: 'Feature',
      properties: { tier },
      geometry: { type: 'Point', coordinates: [lon, lat] },
    })
  }
  for (let i = 0; i < 380; i++) {
    const lon = hashNoise(i, 11) * 360 - 180
    const lat = (hashNoise(i, 13) - 0.5) * 120
    if (Math.abs(lat) < 8) continue
    features.push({
      type: 'Feature',
      properties: { tier: 'remote' },
      geometry: { type: 'Point', coordinates: [lon, lat] },
    })
  }
  return { type: 'FeatureCollection', features }
}

function arcCoords(
  from: [number, number],
  to: [number, number],
  segments = 64,
): [number, number][] {
  const path: [number, number][] = []
  for (let i = 0; i <= segments; i++) {
    const t = i / segments
    const lon = from[0] + (to[0] - from[0]) * t
    const lift = Math.sin(t * Math.PI) * 12
    const lat = from[1] + (to[1] - from[1]) * t + lift
    path.push([lon, lat])
  }
  return path
}

function buildRoutes(): GeoJSON.FeatureCollection {
  const pairs: [number, number, number, number][] = [
    [55.3, 25.2, 72.8, 19.0],
    [72.8, 19.0, 103.8, 1.35],
    [103.8, 1.35, 121.5, 31.2],
    [121.5, 31.2, 139.7, 35.7],
    [2.35, 48.85, 31.2, 30.0],
    [31.2, 30.0, 55.3, 25.2],
    [-0.12, 51.5, 37.6, 55.75],
    [13.4, 52.5, 77.2, 28.6],
    [77.2, 28.6, 103.8, 1.35],
    [-74.0, 40.7, -0.12, 51.5],
    [151.2, -33.8, 114.1, 22.3],
    [18.4, -33.9, 55.3, 25.2],
  ]
  return {
    type: 'FeatureCollection',
    features: pairs.map((p, idx) => ({
      type: 'Feature' as const,
      properties: { id: `route-${idx}` },
      geometry: {
        type: 'LineString' as const,
        coordinates: arcCoords([p[0], p[1]], [p[2], p[3]]),
      },
    })),
  }
}

function buildAlerts(): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { label: 'Punjab stubble watch' },
        geometry: { type: 'Point', coordinates: [75.4, 30.9] },
      },
      {
        type: 'Feature',
        properties: { label: 'NCR transport haze' },
        geometry: { type: 'Point', coordinates: [77.1, 28.5] },
      },
      {
        type: 'Feature',
        properties: { label: 'Indo-Gangetic plume' },
        geometry: { type: 'Point', coordinates: [82.0, 25.5] },
      },
    ],
  }
}

const OVERLAY_LAYERS = [
  'aero-intel-routes-glow',
  'aero-intel-routes',
  'aero-intel-sensors-glow',
  'aero-intel-sensors',
  'aero-intel-alerts',
  'aero-fire-season',
] as const

function buildFireSeason(): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = []
  for (let i = 0; i < 120; i++) {
    const lon = 72 + hashNoise(i, 20) * 12
    const lat = 28 + hashNoise(i, 21) * 5
    features.push({
      type: 'Feature',
      properties: {},
      geometry: { type: 'Point', coordinates: [lon, lat] },
    })
  }
  return { type: 'FeatureCollection', features }
}

function tearDownIntelOverlays(map: Map): void {
  for (const id of OVERLAY_LAYERS) {
    if (map.getLayer(id)) map.removeLayer(id)
  }
  for (const sourceId of [ROUTE_SOURCE, SENSOR_SOURCE, ALERT_SOURCE, FIRE_SEASON_SOURCE]) {
    if (map.getSource(sourceId)) map.removeSource(sourceId)
  }
}

/** MapLibre-native overlays that stay glued to the globe surface (unlike deck Mercator). */
export function syncGlobeIntelOverlays(
  map: Map,
  active: boolean,
  fireSeason = false,
): void {
  if (!active) {
    tearDownIntelOverlays(map)
    return
  }

  if (!map.getSource(ROUTE_SOURCE)) {
    map.addSource(ROUTE_SOURCE, { type: 'geojson', data: buildRoutes() })
    map.addLayer({
      id: 'aero-intel-routes-glow',
      type: 'line',
      source: ROUTE_SOURCE,
      paint: {
        'line-color': '#22d3ee',
        'line-width': 4,
        'line-opacity': 0.12,
        'line-blur': 2,
      },
    })
    map.addLayer({
      id: 'aero-intel-routes',
      type: 'line',
      source: ROUTE_SOURCE,
      paint: {
        'line-color': '#38bdf8',
        'line-width': 1.2,
        'line-opacity': 0.55,
      },
    })
  }

  if (!map.getSource(SENSOR_SOURCE)) {
    map.addSource(SENSOR_SOURCE, { type: 'geojson', data: buildSensors() })
    map.addLayer({
      id: 'aero-intel-sensors-glow',
      type: 'circle',
      source: SENSOR_SOURCE,
      paint: {
        'circle-radius': ['match', ['get', 'tier'], 'primary', 10, 'node', 7, 5],
        'circle-color': '#4ade80',
        'circle-opacity': 0.15,
        'circle-blur': 0.85,
      },
    })
    map.addLayer({
      id: 'aero-intel-sensors',
      type: 'circle',
      source: SENSOR_SOURCE,
      paint: {
        'circle-radius': ['match', ['get', 'tier'], 'primary', 3.5, 'node', 2.5, 1.8],
        'circle-color': '#4ade80',
        'circle-opacity': 0.92,
        'circle-stroke-width': 1,
        'circle-stroke-color': '#052e16',
        'circle-stroke-opacity': 0.6,
      },
    })
  }

  if (!map.getSource(ALERT_SOURCE)) {
    map.addSource(ALERT_SOURCE, { type: 'geojson', data: buildAlerts() })
    map.addLayer({
      id: 'aero-intel-alerts',
      type: 'circle',
      source: ALERT_SOURCE,
      paint: {
        'circle-radius': 6,
        'circle-color': '#fb923c',
        'circle-opacity': 0.9,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fef3c7',
        'circle-stroke-opacity': 0.85,
      },
    })
  }

  if (fireSeason) {
    if (!map.getSource(FIRE_SEASON_SOURCE)) {
      map.addSource(FIRE_SEASON_SOURCE, { type: 'geojson', data: buildFireSeason() })
      map.addLayer({
        id: 'aero-fire-season',
        type: 'circle',
        source: FIRE_SEASON_SOURCE,
        paint: {
          'circle-radius': 4,
          'circle-color': '#fb923c',
          'circle-opacity': 0.75,
          'circle-blur': 0.4,
        },
      })
    }
  } else if (map.getLayer('aero-fire-season')) {
    map.removeLayer('aero-fire-season')
    if (map.getSource(FIRE_SEASON_SOURCE)) map.removeSource(FIRE_SEASON_SOURCE)
  }
}

/** Quieter basemap labels so the globe reads like a command display, not a road atlas. */
export function softenBasemapLabels(map: Map, globe: boolean): void {
  const style = map.getStyle()
  if (!style?.layers) return
  for (const layer of style.layers) {
    if (layer.type !== 'symbol') continue
    try {
      map.setPaintProperty(layer.id, 'text-opacity', globe ? 0.28 : 1)
      map.setPaintProperty(layer.id, 'icon-opacity', globe ? 0.2 : 1)
    } catch {
      /* layer may not expose these paints */
    }
  }
}
