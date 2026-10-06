import type { Map } from 'maplibre-gl'
import type { MapScene } from './MapViewControls'

/** Globe mode uses MapLibre’s native drag/zoom/rotate; corridor uses deck.gl. */
export function setMapInteraction(map: Map, scene: MapScene): void {
  const globe = scene === 'globe'
  const canvas = map.getCanvas()

  const safe = (fn: () => void) => {
    try {
      fn()
    } catch {
      /* handler not available on minimal builds */
    }
  }

  if (globe) {
    safe(() => map.dragPan.enable())
    safe(() => map.scrollZoom.enable())
    safe(() => map.doubleClickZoom.enable())
    safe(() => map.dragRotate.enable())
    safe(() => map.touchZoomRotate.enable())
    safe(() => map.touchPitch.enable())
    safe(() => map.keyboard.enable())
    canvas.style.cursor = 'grab'
  } else {
    safe(() => map.dragPan.disable())
    safe(() => map.scrollZoom.disable())
    safe(() => map.doubleClickZoom.disable())
    safe(() => map.dragRotate.disable())
    safe(() => map.touchZoomRotate.disable())
    safe(() => map.touchPitch.disable())
    safe(() => map.keyboard.disable())
    canvas.style.cursor = ''
  }
}

export function readViewFromMap(map: Map) {
  const c = map.getCenter()
  return {
    longitude: c.lng,
    latitude: c.lat,
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  }
}
