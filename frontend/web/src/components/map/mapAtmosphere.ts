import type { Map } from 'maplibre-gl'
import { CARTO_STYLE_URL, CARTO_VOYAGER_STYLE_URL } from './basemapStyle'

export type MapProjection = 'globe' | 'mercator'
export type BasemapFlavor = 'intel' | 'satellite'

const INTEL_FOG_NIGHT = {
  color: 'rgb(4, 8, 18)',
  'high-color': 'rgb(22, 48, 110)',
  'horizon-blend': 0.1,
  'space-color': 'rgb(0, 0, 0)',
  'star-intensity': 0.95,
}

const INTEL_FOG_DAY = {
  color: 'rgb(18, 28, 48)',
  'high-color': 'rgb(56, 120, 200)',
  'horizon-blend': 0.12,
  'space-color': 'rgb(4, 8, 18)',
  'star-intensity': 0.35,
}

const FLAT_FOG = {
  color: 'rgb(8, 12, 20)',
  'high-color': 'rgb(15, 23, 42)',
  'horizon-blend': 0.02,
  'space-color': 'rgb(0, 0, 0)',
  'star-intensity': 0,
}

export function basemapUrl(flavor: BasemapFlavor): string {
  return flavor === 'satellite' ? CARTO_VOYAGER_STYLE_URL : CARTO_STYLE_URL
}

/** Applies globe atmosphere or flat corridor rendering on the MapLibre instance. */
export function applyMapAtmosphere(
  map: Map,
  projection: MapProjection,
  dayNight: boolean,
): void {
  try {
    map.setProjection({ type: projection })
  } catch {
    // Offline fallback styles may not support globe; mercator still works.
  }

  if (projection === 'globe') {
    try {
      map.setPaintProperty('background', 'background-color', 'rgba(0,0,0,0)')
    } catch {
      /* style may not expose background layer */
    }
  }

  const fog = (map as Map & { setFog?: (spec: Record<string, string | number>) => void }).setFog
  if (!fog) return
  try {
    if (projection === 'globe') {
      fog.call(map, dayNight ? INTEL_FOG_NIGHT : INTEL_FOG_DAY)
    } else {
      fog.call(map, FLAT_FOG)
    }
  } catch {
    // Fog is optional on minimal styles.
  }
}
