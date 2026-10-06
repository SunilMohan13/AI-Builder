import {
  PolygonLayer,
  ScatterplotLayer,
  PathLayer,
  LineLayer,
  TextLayer,
  GeoJsonLayer,
} from '@deck.gl/layers'
import geography from '../../data/geography.json'
import type { GridCell, FireObservation, WindObservation, IndustrySite } from '../../types'
import { getPollutionColor, getSmokeColor } from '../../utils/aqi'
import {
  cellPolygonDeg,
  KM_PER_DEG_LAT,
  TRANSPORT_BEARING_DEG,
  WIND_SPEED_KMH,
  type NamedLocation,
} from '../../utils/geo'
import { hashNoise } from '../../utils/seededRandom'
import type { OrbitalPoint } from './orbitalDecor'

const COLOR_TRANSITION = 700

/** Cyan shell visible in globe command view — decorative, not real TLE tracks. */
export function createOrbitalShellHaloLayer(
  points: OrbitalPoint[],
  visible: boolean,
  time: number,
) {
  if (!visible || points.length === 0) return null
  const twinkle = 0.5 + Math.sin(time * 0.9) * 0.08
  return new ScatterplotLayer<OrbitalPoint>({
    id: 'orbital-shell-halo',
    data: points,
    pickable: false,
    radiusUnits: 'pixels',
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => 2.8 + (d.band % 4) * 0.6,
    getFillColor: (d) => {
      const a = Math.round((28 + d.band * 6) * twinkle)
      return d.band % 2 === 0 ? [34, 211, 238, a] : [74, 222, 128, Math.round(a * 0.85)]
    },
    radiusMinPixels: 1.5,
    radiusMaxPixels: 5,
    updateTriggers: { getFillColor: [time] },
  })
}

export function createOrbitalShellLayer(points: OrbitalPoint[], visible: boolean, time: number) {
  if (!visible || points.length === 0) return null
  const twinkle = 0.72 + Math.sin(time * 1.4) * 0.14
  return new ScatterplotLayer<OrbitalPoint>({
    id: 'orbital-shell',
    data: points,
    pickable: false,
    radiusUnits: 'pixels',
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => 1.4 + (d.band % 3) * 0.45,
    getFillColor: (d) => {
      const a = Math.round((70 + d.band * 14) * twinkle)
      return d.band % 2 === 0 ? [34, 211, 238, a] : [74, 222, 128, Math.round(a * 0.8)]
    },
    radiusMinPixels: 1,
    radiusMaxPixels: 3.5,
    updateTriggers: { getFillColor: [time] },
  })
}

/** Great-circle style arcs from the fire source toward exposed metros. */
export function createGlobeArcLayer(
  arcs: { path: [number, number][]; id: string }[],
  visible: boolean,
  pulse: number,
) {
  if (!visible || arcs.length === 0) return null
  const glow = 0.55 + Math.sin(pulse) * 0.15
  return new PathLayer<{ path: [number, number][]; id: string }>({
    id: 'globe-arcs',
    data: arcs,
    pickable: false,
    getPath: (d) => d.path,
    getColor: [56, 189, 248, Math.round(95 * glow)],
    getWidth: 1.4,
    widthUnits: 'pixels',
    widthMinPixels: 1,
    capRounded: true,
    updateTriggers: { getColor: [pulse] },
  })
}

/** Pulsing nodes at CPCB-scale monitoring cities for the world-scale view. */
export function createMonitoringNodesLayer(
  places: NamedLocation[],
  visible: boolean,
  pulse: number,
) {
  if (!visible) return null
  const breathe = 1 + Math.sin(pulse) * 0.1
  return new ScatterplotLayer<NamedLocation>({
    id: 'monitoring-nodes',
    data: places,
    pickable: false,
    stroked: true,
    filled: true,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 5 * breathe,
    radiusUnits: 'pixels',
    getFillColor: [34, 211, 238, 200],
    getLineColor: [15, 23, 42, 230],
    lineWidthUnits: 'pixels',
    getLineWidth: 1.2,
    radiusMinPixels: 4,
    radiusMaxPixels: 10,
    updateTriggers: { getRadius: [pulse] },
  })
}

export function createPollutionLayer(
  data: GridCell[],
  visible: boolean,
  onClick?: (cell: GridCell) => void,
) {
  if (!visible) return null
  return new PolygonLayer<GridCell>({
    id: 'pollution-grid',
    data,
    pickable: true,
    stroked: false,
    filled: true,
    getPolygon: (d) => cellPolygonDeg(d.lat, d.lon, d.stepDeg),
    getFillColor: (d) => getPollutionColor(d.pm25, d.edgeFade),
    updateTriggers: { getFillColor: [data.length, data[0]?.gridId] },
    // Cross-fades concentrations when the timeline moves instead of snapping.
    transitions: { getFillColor: COLOR_TRANSITION },
    onClick: (info) => {
      if (info.object && onClick) onClick(info.object)
    },
  })
}

/**
 * Transported smoke drawn as its own translucent field above the pollution
 * ramp, so the fire-to-Delhi ribbon is legible as a distinct phenomenon.
 */
export function createBaselinePlumeLayer(data: GridCell[], visible: boolean) {
  if (!visible) return null
  const smoke = data.filter((c) => c.plume > 3)
  return new PolygonLayer<GridCell>({
    id: 'baseline-plume',
    data: smoke,
    pickable: false,
    stroked: false,
    filled: true,
    getPolygon: (d) => cellPolygonDeg(d.lat, d.lon, d.stepDeg),
    getFillColor: (d) => {
      const a = Math.min(Math.round(d.plume * 0.85), 72)
      return [148, 163, 184, a]
    },
    updateTriggers: { getFillColor: [smoke.length] },
  })
}

export function createPlumeLayer(data: GridCell[], visible: boolean) {
  if (!visible) return null
  const smoke = data.filter((c) => c.plume > 3)
  return new PolygonLayer<GridCell>({
    id: 'plume',
    data: smoke,
    pickable: false,
    stroked: false,
    filled: true,
    getPolygon: (d) => cellPolygonDeg(d.lat, d.lon, d.stepDeg),
    getFillColor: (d) => getSmokeColor(d.plume, d.edgeFade),
    updateTriggers: { getFillColor: [smoke.length, smoke[0]?.gridId] },
    transitions: { getFillColor: COLOR_TRANSITION },
  })
}

export interface FireRadarRing {
  id: string
  lon: number
  lat: number
  phase: number
}

/**
 * Concentric expanding rings around a detection — the Detect-scene radar.
 * `phase` is 0..1; opacity falls as the ring grows.
 */
export function createFireRadarLayer(rings: FireRadarRing[], visible: boolean) {
  if (!visible || rings.length === 0) return null
  return new ScatterplotLayer<FireRadarRing>({
    id: 'fire-radar',
    data: rings,
    pickable: false,
    stroked: true,
    filled: false,
    radiusUnits: 'meters',
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => 2500 + d.phase * 22000,
    getLineColor: (d) => [255, 92, 18, Math.round(200 * (1 - d.phase) ** 1.4)],
    getLineWidth: (d) => 2.4 - d.phase * 1.2,
    lineWidthUnits: 'pixels',
    lineWidthMinPixels: 1,
    updateTriggers: { getRadius: [rings[0]?.phase], getLineColor: [rings[0]?.phase] },
  })
}

export function buildFireRadarRings(
  fires: FireObservation[],
  pulse: number,
  ringsPerFire = 4,
): FireRadarRing[] {
  return fires.flatMap((fire) =>
    Array.from({ length: ringsPerFire }, (_, i) => ({
      id: `${fire.id}-r${i}`,
      lon: fire.lon,
      lat: fire.lat,
      phase: (pulse * 0.22 + i / ringsPerFire) % 1,
    })),
  )
}

/** Soft outer glow; paired with a bright core so fires read as heat, not dots. */
export function createFireGlowLayer(data: FireObservation[], visible: boolean, pulse: number) {
  if (!visible) return null
  const breathe = 1 + Math.sin(pulse) * 0.08
  return new ScatterplotLayer<FireObservation>({
    id: 'fire-glow',
    data,
    pickable: false,
    radiusUnits: 'meters',
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => (5000 + (d.frp / 140) * 9000) * breathe,
    getFillColor: [255, 106, 26, 34],
    radiusMinPixels: 10,
    radiusMaxPixels: 70,
    updateTriggers: { getRadius: [breathe] },
  })
}

export function createFireLayer(
  data: FireObservation[],
  visible: boolean,
  onClick?: (fire: FireObservation) => void,
) {
  if (!visible) return null
  return new ScatterplotLayer<FireObservation>({
    id: 'fires',
    data,
    pickable: true,
    radiusUnits: 'pixels',
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => 2.2 + (d.frp / 140) * 3.4,
    getFillColor: [255, 214, 120, 255],
    getLineColor: [255, 88, 12, 220],
    lineWidthUnits: 'pixels',
    getLineWidth: 1.4,
    radiusMinPixels: 2.5,
    radiusMaxPixels: 8,
    onClick: (info) => {
      if (info.object && onClick) onClick(info.object)
    },
  })
}

interface Particle {
  id: number
  fireIndex: number
  offset: number
  jitter: number
  size: number
}

/** Stable particle definitions; only their positions change per frame. */
export function buildSmokeParticles(count: number, fireCount: number): Particle[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    fireIndex: Math.floor(hashNoise(i, 1) * Math.max(fireCount, 1)),
    offset: hashNoise(i, 2),
    jitter: hashNoise(i, 3) - 0.5,
    size: 0.4 + hashNoise(i, 4) * 0.6,
  }))
}

/**
 * Motes released from the fires and advected downwind. This is what makes the
 * transport read as movement rather than a static gradient.
 */
export function createSmokeParticleLayer(
  particles: Particle[],
  fires: FireObservation[],
  visible: boolean,
  time: number,
  horizonHours: number,
  transportBearingDeg = TRANSPORT_BEARING_DEG,
) {
  if (!visible || fires.length === 0) return null

  const theta = (transportBearingDeg * Math.PI) / 180
  const eastward = Math.sin(theta)
  const northward = Math.cos(theta)
  const travelKm = WIND_SPEED_KMH * Math.max(horizonHours, 8)
  const cycle = 18 // seconds for a mote to traverse the plume

  const km2degLat = 1 / KM_PER_DEG_LAT

  const positioned = particles.map((p) => {
    const fire = fires[p.fireIndex % fires.length]
    const phase = (p.offset + time / cycle) % 1
    const along = phase * travelKm
    // Crosswind wander grows downwind, matching the dispersion of the field.
    const spread = (10 + along * 0.13) * p.jitter * 2
    const km2degLon = km2degLat / Math.cos((fire.lat * Math.PI) / 180)

    const lat = fire.lat + (along * northward - spread * Math.sin(theta)) * km2degLat
    const lon = fire.lon + (along * eastward + spread * Math.cos(theta)) * km2degLon

    // Fade in on release, fade out at the leading edge.
    const life = Math.sin(phase * Math.PI) ** 0.75
    return { position: [lon, lat] as [number, number], life, size: p.size }
  })

  return new ScatterplotLayer<(typeof positioned)[number]>({
    id: 'smoke-particles',
    data: positioned,
    pickable: false,
    radiusUnits: 'pixels',
    getPosition: (d) => d.position,
    getRadius: (d) => 0.7 + d.size * 1.5,
    getFillColor: (d) => [228, 220, 208, Math.round(d.life * 62)],
    radiusMinPixels: 0.8,
    radiusMaxPixels: 3,
    updateTriggers: { getPosition: [time], getFillColor: [time] },
  })
}

/**
 * Short, dense streaklets. Long arrows across the whole corridor read as
 * scratches over the data rather than airflow.
 */
export function createWindLayer(data: WindObservation[], visible: boolean, time = 0) {
  if (!visible) return null

  const lengthDeg = 0.075
  const segments = data.map((w, i) => {
    const mag = Math.hypot(w.u, w.v) || 1
    const ux = (w.u / mag) * lengthDeg
    const uy = (w.v / mag) * lengthDeg
    // Slide each streak along its own axis so the field appears to flow.
    const drift = ((time * 0.35 + hashNoise(i, 7)) % 1) - 0.5
    const cx = w.lon + ux * drift * 1.6
    const cy = w.lat + uy * drift * 1.6
    return {
      from: [cx - ux / 2, cy - uy / 2] as [number, number],
      to: [cx + ux / 2, cy + uy / 2] as [number, number],
      fade: 1 - Math.abs(drift) * 1.4,
    }
  })

  return new LineLayer<(typeof segments)[number]>({
    id: 'wind',
    data: segments,
    pickable: false,
    getSourcePosition: (d) => d.from,
    getTargetPosition: (d) => d.to,
    getColor: (d) => [125, 211, 252, Math.round(Math.max(d.fade, 0) * 90)],
    getWidth: 1.2,
    widthUnits: 'pixels',
    widthMinPixels: 1,
    updateTriggers: { getSourcePosition: [time], getTargetPosition: [time], getColor: [time] },
  })
}

export function createIndustryLayer(data: IndustrySite[], visible: boolean) {
  if (!visible) return null
  return new ScatterplotLayer<IndustrySite>({
    id: 'industry',
    data,
    pickable: true,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 4,
    radiusUnits: 'pixels',
    getFillColor: [203, 213, 225, 190],
    getLineColor: [100, 116, 139, 220],
    lineWidthUnits: 'pixels',
    getLineWidth: 1,
    radiusMinPixels: 3,
  })
}

/** Population exposure as hollow rings, so it layers over the grid legibly. */
export function createPopulationLayer(data: GridCell[], visible: boolean) {
  if (!visible) return null
  // High threshold keeps this to a few urban cores; a ring per populated cell
  // produces a halftone moiré over the grid.
  const filtered = data.filter((c) => c.population > 18_000)
  return new ScatterplotLayer<GridCell>({
    id: 'population',
    data: filtered,
    pickable: false,
    stroked: true,
    filled: false,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => Math.min(d.population / 22, 2400),
    radiusUnits: 'meters',
    lineWidthUnits: 'pixels',
    getLineWidth: 1.2,
    getLineColor: (d) => {
      const a = Math.round(170 * d.edgeFade)
      if (d.risk === 'SEVERE') return [248, 113, 113, a]
      if (d.risk === 'HIGH') return [251, 146, 60, a]
      if (d.risk === 'MEDIUM') return [250, 204, 21, a]
      return [74, 222, 128, Math.round(a * 0.6)]
    },
    radiusMinPixels: 2,
    radiusMaxPixels: 26,
  })
}

/**
 * Coastlines and administrative borders drawn from a bundled Natural Earth
 * extract. Rendering geography ourselves means the map is never a blank
 * rectangle, whether or not the remote basemap tiles arrive.
 */
export function createGeographyLayer(visible = true) {
  if (!visible) return null
  return new GeoJsonLayer({
    id: 'geography',
    data: geography as never,
    pickable: false,
    stroked: true,
    filled: false,
    lineWidthUnits: 'pixels',
    getLineWidth: (f: { properties?: { kind?: string } }) =>
      f.properties?.kind === 'state' ? 0.8 : 1.4,
    getLineColor: (f: { properties?: { kind?: string } }) => {
      switch (f.properties?.kind) {
        case 'state':
          return [71, 85, 105, 150]
        case 'country':
          return [100, 116, 139, 210]
        default:
          return [94, 122, 148, 190]
      }
    },
  })
}

/**
 * City labels rendered by deck.gl rather than left to the basemap. An operator
 * has to know *which* city is glowing, and that has to hold even on a very
 * dark basemap or the offline fallback.
 */
export function createPlaceLabelLayer(places: NamedLocation[], zoom: number) {
  // Drop the secondary towns only when really zoomed out, to avoid a wall of
  // overlapping text at national scale.
  const visible = zoom < 5.5 ? places.filter((p) => p.zoom <= 9) : places

  return new TextLayer<NamedLocation>({
    id: 'place-labels',
    data: visible,
    pickable: false,
    getPosition: (d) => [d.lon, d.lat],
    getText: (d) => d.name.toUpperCase(),
    getSize: (d) => (d.zoom <= 9 ? 12 : 10.5),
    sizeUnits: 'pixels',
    getColor: [226, 232, 240, 235],
    getTextAnchor: 'start',
    getAlignmentBaseline: 'center',
    getPixelOffset: [9, 0],
    fontFamily: 'ui-monospace, SFMono-Regular, monospace',
    characterSet: 'auto',
    // With SDF fonts deck.gl treats outlineWidth as a fraction of font size,
    // so a pixel value here renders as garbage.
    fontSettings: { sdf: true, radius: 12 },
    outlineWidth: 0.3,
    outlineColor: [3, 7, 14, 235],
    updateTriggers: { getText: [visible.length], getSize: [zoom] },
  })
}

/** Small tick marking each labelled place. */
export function createPlaceDotLayer(places: NamedLocation[]) {
  return new ScatterplotLayer<NamedLocation>({
    id: 'place-dots',
    data: places,
    pickable: false,
    stroked: true,
    filled: false,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 3,
    radiusUnits: 'pixels',
    lineWidthUnits: 'pixels',
    getLineWidth: 1,
    getLineColor: [148, 163, 184, 190],
  })
}

/** Dashed corridor axis from the source to the exposed metro. */
export function createTransportAxisLayer(
  origin: { lat: number; lon: number },
  target: { lat: number; lon: number },
  visible: boolean,
) {
  if (!visible) return null
  return new PathLayer<{ path: [number, number][] }>({
    id: 'transport-axis',
    data: [
      {
        path: [
          [origin.lon, origin.lat],
          [target.lon, target.lat],
        ],
      },
    ],
    pickable: false,
    getPath: (d) => d.path,
    getColor: [148, 163, 184, 70],
    getWidth: 1,
    widthUnits: 'pixels',
    widthMinPixels: 1,
  })
}

export function createGrapZoneLayer(ring: [number, number][], visible: boolean) {
  if (!visible) return null
  return new PolygonLayer<{ polygon: [number, number][] }>({
    id: 'grap-zone',
    data: [{ polygon: ring }],
    pickable: false,
    stroked: true,
    filled: true,
    getPolygon: (d) => d.polygon,
    getFillColor: [139, 92, 246, 28],
    getLineColor: [167, 139, 250, 160],
    getLineWidth: 2,
    lineWidthUnits: 'pixels',
  })
}

export function createExposureRibbonLayer(path: [number, number][], visible: boolean) {
  if (!visible || path.length < 2) return null
  return new PathLayer<{ path: [number, number][] }>({
    id: 'exposure-ribbon',
    data: [{ path }],
    pickable: false,
    getPath: (d) => d.path,
    getColor: [251, 191, 36, 200],
    getWidth: 8,
    widthUnits: 'pixels',
    widthMinPixels: 3,
    capRounded: true,
    jointRounded: true,
  })
}
