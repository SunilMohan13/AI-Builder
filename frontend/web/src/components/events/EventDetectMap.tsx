import { useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import { DeckGL } from '@deck.gl/react'
import { PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { useQuery } from '@tanstack/react-query'
import type { EvidenceItem, FireObservation, PollutionEvent } from '../../types'
import { fetchFires } from '../../services/mapService'
import { useAnimationClock } from '../../hooks/useAnimationClock'
import { useDataMode } from '../../context/DataModeContext'
import { useApp } from '../../context/AppContext'
import { basemapUrl } from '../map/mapAtmosphere'
import { attachBasemapFallback } from '../map/basemapStyle'
import {
  buildFireRadarRings,
  createFireGlowLayer,
  createFireLayer,
  createFireRadarLayer,
} from '../map/layerFactories'
import {
  CORRIDOR_LOCATIONS,
  KM_PER_DEG_LAT,
  TRANSPORT_BEARING_DEG,
  WIND_FROM_DEG,
  WIND_SPEED_MS,
  distanceKm,
} from '../../utils/geo'
import { cn } from '../../utils/cn'
import {
  DetectDecisionLab,
  applyDetectScenario,
  applyHorizon,
  horizonRibbonScale,
  scenarioCaption,
  scenarioRibbonKm,
  type DetectHorizon,
  type DetectScenario,
} from './DetectDecisionLab'

type DetectLayerKey = 'fires' | 'plume' | 'smoke' | 'wind' | 'evidence' | 'places'

const DETECT_LAYER_OPTIONS: { key: DetectLayerKey; label: string }[] = [
  { key: 'fires', label: 'Fires' },
  { key: 'plume', label: 'Plume' },
  { key: 'smoke', label: 'Smoke' },
  { key: 'wind', label: 'Wind' },
  { key: 'evidence', label: 'Evidence' },
  { key: 'places', label: 'Places' },
]

const ALL_DETECT_LAYERS: Record<DetectLayerKey, boolean> = {
  fires: true,
  plume: true,
  smoke: true,
  wind: true,
  evidence: true,
  places: true,
}

/** Visual layout offsets (degrees) so evidence radiates from the event hub.
 *  These are map-layout positions, not claimed station coordinates. */
/**
 * Preferred bearing for each evidence category, degrees counter-clockwise
 * from east.
 *
 * This replaced a table of fixed lon/lat offsets. Because that table was
 * keyed by category, two items of the same category — two satellite
 * products, say — resolved to identical coordinates and their labels were
 * drawn exactly on top of each other.
 */
const CATEGORY_ANGLE_DEG: Record<string, number> = {
  Fire: 82,
  CPCB: 18,
  Satellite: -38,
  Weather: 138,
  CAMS: 58,
  Forecast: 205,
  Citizen: -78,
  'Counter-signal': 168,
}

/**
 * Ring radius in degrees latitude. Alternate slots are drawn short so two
 * neighbouring labels sit at different distances from the hub rather than
 * side by side in the same band.
 */
const NODE_RING_DEG = 0.86
const NODE_RING_INNER = 0.74

const NODE_COLOR: Record<string, [number, number, number, number]> = {
  Fire: [255, 140, 40, 230],
  CPCB: [52, 211, 153, 230],
  Satellite: [125, 211, 252, 230],
  Weather: [165, 180, 200, 230],
  CAMS: [94, 234, 212, 220],
  Forecast: [250, 204, 21, 230],
  Citizen: [167, 139, 250, 230],
  'Counter-signal': [148, 163, 184, 200],
}

const DELHI_NCR = CORRIDOR_LOCATIONS[0]

interface EvidenceNode {
  id: string
  label: string
  category: string
  lon: number
  lat: number
  /** Bearing from the hub. Drives which way the label is written. */
  angleDeg: number
}

interface NamedPoint {
  name: string
  lat: number
  lon: number
}

function curvePath(
  from: [number, number],
  to: [number, number],
  bulge: number,
): [number, number][] {
  const mx = (from[0] + to[0]) / 2
  const my = (from[1] + to[1]) / 2
  const dx = to[0] - from[0]
  const dy = to[1] - from[1]
  const cx = mx - dy * bulge
  const cy = my + dx * bulge
  const pts: [number, number][] = []
  for (let t = 0; t <= 1; t += 0.06) {
    const u = 1 - t
    pts.push([
      u * u * from[0] + 2 * u * t * cx + t * t * to[0],
      u * u * from[1] + 2 * u * t * cy + t * t * to[1],
    ])
  }
  return pts
}

/**
 * Shortens a source name to something that fits beside a dot.
 *
 * The full provider strings are the widest thing on this map and are what
 * made neighbouring labels meet. The rail beside the map carries the full
 * name, so nothing is lost by abbreviating here.
 */
function shortLabel(source: string): string {
  return source
    .replace(/^(NASA|Copernicus|AeroPulse|ISRO|IMD)\s+/, '')
    .replace(/\s*\+\s*AQMS$/, '')
    .replace(/\s*Engine$/, '')
    .trim()
}

/**
 * Places evidence sources on a ring around the event.
 *
 * Slots are spread evenly around the full circle rather than at each
 * category's own bearing: bearings clustered several categories into the
 * same arc, which is what drove their labels into each other. Ordering by
 * bearing keeps related evidence adjacent, so the arrangement still reads
 * the same way between renders. The longitude component is divided by
 * cos(latitude) so the ring reads as a circle rather than an ellipse
 * squashed toward the pole.
 */
function layoutNodes(event: PollutionEvent, evidence: EvidenceItem[]): EvidenceNode[] {
  const lonScale = Math.max(Math.cos((event.lat * Math.PI) / 180), 0.2)
  const ordered = [...evidence].sort((a, b) => {
    const byBearing =
      (CATEGORY_ANGLE_DEG[a.category] ?? 0) - (CATEGORY_ANGLE_DEG[b.category] ?? 0)
    return byBearing !== 0 ? byBearing : a.id.localeCompare(b.id)
  })

  // The source place label sits back along the transport axis. Slots start
  // half a step off that bearing so the ring never opens a seat underneath
  // a label that is already there.
  const reservedDeg = 90 - (TRANSPORT_BEARING_DEG + 180)
  const step = 360 / Math.max(ordered.length, 1)

  return ordered.map((item, i) => {
    const angleDeg = reservedDeg + step / 2 + i * step
    const theta = (angleDeg * Math.PI) / 180
    const radius = i % 2 === 0 ? NODE_RING_DEG : NODE_RING_INNER

    return {
      id: item.id,
      label: shortLabel(item.source),
      category: item.category,
      lon: event.lon + (radius * Math.cos(theta)) / lonScale,
      lat: event.lat + radius * Math.sin(theta),
      angleDeg,
    }
  })
}

/** Writes a label away from the hub rather than back across it. */
function labelAnchor(angleDeg: number): 'start' | 'middle' | 'end' {
  const cos = Math.cos((angleDeg * Math.PI) / 180)
  if (cos > 0.35) return 'start'
  if (cos < -0.35) return 'end'
  return 'middle'
}

/** Nudges a label outward along its own bearing. Screen y is inverted. */
function labelOffset(angleDeg: number): [number, number] {
  const theta = (angleDeg * Math.PI) / 180
  return [Math.cos(theta) * 11, -Math.sin(theta) * 13 - 3]
}

/** Destination the predicted plume is drawn toward. Punjab events aim at Delhi NCR. */
function transportTarget(event: PollutionEvent): NamedPoint {
  const km = distanceKm(event.lat, event.lon, DELHI_NCR.lat, DELHI_NCR.lon)
  if (km >= 80) return DELHI_NCR
  const theta = (TRANSPORT_BEARING_DEG * Math.PI) / 180
  const travelKm = 90
  const lonScale = KM_PER_DEG_LAT * Math.cos((event.lat * Math.PI) / 180)
  return {
    name: 'Downwind',
    lat: event.lat + (travelKm * Math.cos(theta)) / KM_PER_DEG_LAT,
    lon: event.lon + (travelKm * Math.sin(theta)) / lonScale,
  }
}

function detectCamera(event: PollutionEvent, dest: NamedPoint) {
  const km = distanceKm(event.lat, event.lon, dest.lat, dest.lon)
  if (km < 80) {
    return {
      longitude: event.lon,
      latitude: event.lat,
      zoom: 8.15,
      pitch: 18,
      bearing: 0,
    }
  }
  return {
    longitude: (event.lon + dest.lon) / 2 + 0.12,
    latitude: (event.lat + dest.lat) / 2,
    zoom: 6.05,
    pitch: 32,
    bearing: -18,
  }
}

/** Tapered smoke ribbon that widens downwind — layout, not an observed plume. */
function plumeRibbon(
  from: [number, number],
  to: [number, number],
  halfWidthKm: number,
): [number, number][] {
  const steps = 28
  const left: [number, number][] = []
  const right: [number, number][] = []
  const dx = to[0] - from[0]
  const dy = to[1] - from[1]
  const len = Math.hypot(dx, dy) || 1
  const nx = -dy / len
  const ny = dx / len
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const lon = from[0] + dx * t
    const lat = from[1] + dy * t
    const taper = 0.28 + t * 1.55
    const wLat = (halfWidthKm / KM_PER_DEG_LAT) * taper
    const lonScale = Math.cos((lat * Math.PI) / 180) || 0.4
    const wLon = wLat / lonScale
    left.push([lon + nx * wLon, lat + ny * wLat])
    right.push([lon - nx * wLon, lat - ny * wLat])
  }
  return [...left, ...right.reverse()]
}

function windChevrons(
  from: [number, number],
  to: [number, number],
  pulse: number,
): { id: string; path: [number, number][] }[] {
  const dx = to[0] - from[0]
  const dy = to[1] - from[1]
  const mag = Math.hypot(dx, dy) || 1
  const ux = dx / mag
  const uy = dy / mag
  const nx = -uy
  const ny = ux
  const len = 0.14
  const drift = ((pulse * 0.08) % 0.12) - 0.02
  const marks = [0.18, 0.34, 0.5, 0.66, 0.82]
  return marks.flatMap((t, i) => {
    const u = Math.min(t + drift, 0.94)
    const lon = from[0] + dx * u
    const lat = from[1] + dy * u
    const tip: [number, number] = [lon + ux * len, lat + uy * len]
    const left: [number, number] = [
      lon - ux * len * 0.15 + nx * len * 0.38,
      lat - uy * len * 0.15 + ny * len * 0.38,
    ]
    const right: [number, number] = [
      lon - ux * len * 0.15 - nx * len * 0.38,
      lat - uy * len * 0.15 - ny * len * 0.38,
    ]
    return [
      { id: `chev-${i}-l`, path: [left, tip] },
      { id: `chev-${i}-r`, path: [right, tip] },
    ]
  })
}

function advectionMotes(
  fires: FireObservation[],
  dest: NamedPoint,
  time: number,
  count = 110,
) {
  if (fires.length === 0) return []
  const cycle = 16
  return Array.from({ length: count }, (_, i) => {
    const fire = fires[i % fires.length]
    const phase = (i * 0.091 + time / cycle) % 1
    const t = phase
    const dx = dest.lon - fire.lon
    const dy = dest.lat - fire.lat
    const mag = Math.hypot(dx, dy) || 1
    const nx = -dy / mag
    const ny = dx / mag
    const spread = (0.03 + t * 0.28) * ((i % 9) / 8 - 0.5)
    const life = Math.sin(phase * Math.PI) ** 0.72
    return {
      id: i,
      position: [fire.lon + dx * t + nx * spread, fire.lat + dy * t + ny * spread] as [
        number,
        number,
      ],
      life,
      size: 1.4 + (i % 6) * 0.45,
    }
  })
}

export function EventDetectMap({
  event,
  evidence,
  className,
}: {
  event: PollutionEvent
  evidence: EvidenceItem[]
  className?: string
}) {
  const { mode } = useDataMode()
  const { demoRunning, demoPhase } = useApp()
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const corridorDest = useMemo(
    () => transportTarget(event),
    [event.lat, event.lon],
  )
  const [scenario, setScenario] = useState<DetectScenario>('now')
  const [horizon, setHorizon] = useState<DetectHorizon>(6)
  const [layersOpen, setLayersOpen] = useState(false)
  const scenarioDest = useMemo(
    () => applyDetectScenario(event, corridorDest, scenario),
    [event.lat, event.lon, corridorDest, scenario],
  )
  const dest = useMemo(
    () => applyHorizon(event, scenarioDest, horizon),
    [event.lat, event.lon, scenarioDest, horizon],
  )
  const camera = useMemo(
    () => detectCamera(event, corridorDest),
    [event.lat, event.lon, corridorDest],
  )
  const [viewState, setViewState] = useState(camera)
  const [visible, setVisible] = useState(ALL_DETECT_LAYERS)
  const [hiddenEvidenceIds, setHiddenEvidenceIds] = useState<Set<string>>(() => new Set())
  const time = useAnimationClock(20)
  const pulse = time * 1.5
  const towardNcr = corridorDest.name === 'Delhi NCR'

  useEffect(() => {
    if (!demoRunning) {
      setVisible(ALL_DETECT_LAYERS)
      setScenario('now')
      setHorizon(6)
      return
    }
    if (demoPhase === 'fire') {
      setVisible({ fires: true, plume: false, smoke: false, wind: false, evidence: false, places: true })
      setScenario('now')
      setHorizon(0)
    } else if (demoPhase === 'anomaly') {
      setVisible({ fires: true, plume: false, smoke: false, wind: false, evidence: true, places: true })
      setHorizon(0)
    } else if (demoPhase === 'wind') {
      setVisible({ fires: true, plume: false, smoke: false, wind: true, evidence: false, places: true })
      setHorizon(0)
    } else if (demoPhase === 'plume') {
      setVisible({ fires: true, plume: true, smoke: true, wind: true, evidence: false, places: true })
      setScenario('now')
      setHorizon(6)
    } else if (demoPhase === 'forecast') {
      setVisible({ fires: true, plume: true, smoke: true, wind: true, evidence: false, places: true })
      setHorizon(12)
    } else if (demoPhase === 'confirmed') {
      setVisible(ALL_DETECT_LAYERS)
      setHorizon(6)
    } else if (demoPhase === 'risk' || demoPhase === 'complete') {
      setVisible(ALL_DETECT_LAYERS)
      setScenario('grap')
      setHorizon(12)
    }
  }, [demoRunning, demoPhase])

  const toggleLayer = (key: DetectLayerKey) => {
    setVisible((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const toggleEvidence = (id: string) => {
    setHiddenEvidenceIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const { data: fires = [] } = useQuery({
    queryKey: ['fires', mode, 0, 1],
    queryFn: () => fetchFires(0, 1),
    placeholderData: (previous) => previous,
  })

  useEffect(() => {
    setViewState(camera)
  }, [camera])

  useEffect(() => {
    const el = mapContainerRef.current
    if (!el) return
    const observer = new ResizeObserver(() => {
      mapRef.current?.resize()
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!mapContainerRef.current) return
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: basemapUrl('intel'),
      center: [camera.longitude, camera.latitude],
      zoom: camera.zoom,
      pitch: camera.pitch,
      bearing: camera.bearing,
      attributionControl: { compact: true },
      interactive: false,
    })
    mapRef.current = map
    attachBasemapFallback(map)
    return () => {
      map.remove()
      mapRef.current = null
    }
    // Recreate only when the event location changes; camera object identity is noisy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event.lat, event.lon])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    map.jumpTo({
      center: [viewState.longitude, viewState.latitude],
      zoom: viewState.zoom,
      bearing: viewState.bearing,
      pitch: viewState.pitch,
    })
  }, [viewState])

  const hub: FireObservation = useMemo(
    () => ({
      id: `${event.id}-hub`,
      lat: event.lat,
      lon: event.lon,
      frp: Math.max(event.frpMw, 80),
      confidence: event.detectionConfidence / 100,
      timestamp: event.detectedAt,
    }),
    [event],
  )

  const nearbyFires = useMemo(() => {
    const ranked = [...fires].sort((a, b) => b.frp - a.frp).slice(0, 8)
    return ranked.some((f) => f.id === hub.id) ? ranked : [hub, ...ranked]
  }, [fires, hub])

  const radarFires = useMemo(() => [hub, ...nearbyFires.slice(0, 2)], [hub, nearbyFires])
  const rings = useMemo(() => buildFireRadarRings(radarFires, pulse, 4), [radarFires, pulse])
  const nodes = useMemo(() => layoutNodes(event, evidence), [event, evidence])
  const shownNodes = useMemo(
    () => nodes.filter((node) => !hiddenEvidenceIds.has(node.id)),
    [nodes, hiddenEvidenceIds],
  )

  const arcs = useMemo(
    () =>
      shownNodes.map((node, i) => ({
        id: `arc-${node.id}`,
        path: curvePath([event.lon, event.lat], [node.lon, node.lat], i % 2 === 0 ? 0.28 : -0.22),
        category: node.category,
      })),
    [shownNodes, event.lat, event.lon],
  )

  const origin = useMemo(
    (): [number, number] => [event.lon, event.lat],
    [event.lon, event.lat],
  )
  const target = useMemo(
    (): [number, number] => [dest.lon, dest.lat],
    [dest.lon, dest.lat],
  )
  const ribbon = useMemo(
    () =>
      plumeRibbon(
        origin,
        target,
        scenarioRibbonKm(scenario) * horizonRibbonScale(horizon),
      ),
    [origin, target, scenario, horizon],
  )
  const ribbonCore = useMemo(
    () =>
      plumeRibbon(
        origin,
        target,
        Math.max(4, scenarioRibbonKm(scenario) * horizonRibbonScale(horizon) * 0.45),
      ),
    [origin, target, scenario, horizon],
  )
  const axis = useMemo(() => curvePath(origin, target, 0.06), [origin, target])
  const chevrons = useMemo(() => windChevrons(origin, target, pulse), [origin, target, pulse])
  const motes = useMemo(
    () => advectionMotes(nearbyFires, dest, time),
    [nearbyFires, dest, time],
  )
  const placeLabels = useMemo(() => {
    // The source label used to sit on the hub itself, inside the evidence
    // ring and under the plume origin. Pushed back along the reverse of the
    // transport bearing, it stays attached to the cluster while clearing it.
    const theta = (TRANSPORT_BEARING_DEG * Math.PI) / 180
    const lonScale = Math.max(Math.cos((event.lat * Math.PI) / 180), 0.2)
    // Beyond the ring, not level with it, so it clears the two slots that
    // flank the reserved bearing as well as the hub.
    const backOff = NODE_RING_DEG * 2.2

    const labels = [
      {
        id: 'src',
        name: towardNcr ? 'Punjab fire cluster' : event.region,
        lon: event.lon - (backOff * Math.sin(theta)) / lonScale,
        lat: event.lat - backOff * Math.cos(theta),
      },
      { id: 'dst', name: corridorDest.name, lon: corridorDest.lon, lat: corridorDest.lat },
    ]
    if (dest.lon !== corridorDest.lon || dest.lat !== corridorDest.lat) {
      labels.push({ id: 'front', name: dest.name, lon: dest.lon, lat: dest.lat })
    }
    return labels
  }, [corridorDest, dest, event.lat, event.lon, event.region, towardNcr])

  const layers = useMemo(() => {
    const glow = 0.55 + Math.sin(pulse) * 0.18
    return [
      visible.plume &&
        new PolygonLayer({
          id: 'predicted-plume',
          data: [{ polygon: ribbon }],
          getPolygon: (d: { polygon: [number, number][] }) => d.polygon,
          getFillColor: [255, 168, 72, 42],
          stroked: false,
          pickable: false,
        }),
      visible.plume &&
        new PolygonLayer({
          id: 'predicted-plume-core',
          data: [{ polygon: ribbonCore }],
          getPolygon: (d: { polygon: [number, number][] }) => d.polygon,
          getFillColor: [255, 196, 120, 28],
          stroked: false,
          pickable: false,
        }),
      visible.plume &&
        new PathLayer({
          id: 'predicted-axis',
          data: [{ path: axis }],
          getPath: (d: { path: [number, number][] }) => d.path,
          getColor: [255, 186, 92, 150],
          getWidth: 2.2,
          widthUnits: 'pixels',
          capRounded: true,
          jointRounded: true,
        }),
      visible.wind &&
        new PathLayer({
          id: 'wind-chevrons',
          data: chevrons,
          getPath: (d: { path: [number, number][] }) => d.path,
          getColor: [186, 230, 253, Math.round(140 + glow * 50)],
          getWidth: 1.8,
          widthUnits: 'pixels',
          capRounded: true,
          updateTriggers: { getColor: [pulse] },
        }),
      visible.smoke &&
        new ScatterplotLayer<(typeof motes)[number]>({
          id: 'advection-motes',
          data: motes,
          pickable: false,
          radiusUnits: 'pixels',
          getPosition: (d) => d.position,
          getRadius: (d) => d.size,
          getFillColor: (d) => [236, 214, 180, Math.round(d.life * 120)],
          radiusMinPixels: 1.2,
          radiusMaxPixels: 4.5,
          updateTriggers: { getPosition: [time], getFillColor: [time] },
        }),
      createFireRadarLayer(rings, visible.fires),
      createFireGlowLayer(radarFires, visible.fires, pulse),
      visible.evidence &&
        new PathLayer({
          id: 'evidence-arcs',
          data: arcs,
          getPath: (d: { path: [number, number][] }) => d.path,
          getColor: (d: { category: string }) => {
            const c = NODE_COLOR[d.category] ?? [56, 189, 248, 180]
            return [c[0], c[1], c[2], Math.round(90 * glow)]
          },
          getWidth: 1.6,
          widthUnits: 'pixels',
          capRounded: true,
          jointRounded: true,
          updateTriggers: { getColor: [pulse] },
        }),
      visible.evidence &&
        new ScatterplotLayer<EvidenceNode>({
          id: 'evidence-nodes',
          data: shownNodes,
          getPosition: (d) => [d.lon, d.lat],
          getFillColor: (d) => NODE_COLOR[d.category] ?? [125, 211, 252, 220],
          getRadius: 5,
          radiusUnits: 'pixels',
          radiusMinPixels: 4,
          radiusMaxPixels: 8,
          stroked: true,
          getLineColor: [8, 12, 24, 220],
          getLineWidth: 1.2,
          lineWidthUnits: 'pixels',
        }),
      createFireLayer(nearbyFires, visible.fires),
      visible.fires &&
        new ScatterplotLayer({
          id: 'hub-core',
          data: [hub],
          getPosition: (d: FireObservation) => [d.lon, d.lat],
          getFillColor: [255, 220, 140, 255],
          getRadius: 7,
          radiusUnits: 'pixels',
          stroked: true,
          getLineColor: [255, 90, 20, 255],
          getLineWidth: 2,
          lineWidthUnits: 'pixels',
        }),
      visible.places &&
        new ScatterplotLayer({
          id: 'dest-core',
          data: [corridorDest],
          getPosition: (d: NamedPoint) => [d.lon, d.lat],
          getFillColor: [125, 211, 252, 230],
          getRadius: 6,
          radiusUnits: 'pixels',
          stroked: true,
          getLineColor: [8, 12, 24, 220],
          getLineWidth: 1.5,
          lineWidthUnits: 'pixels',
        }),
      scenario === 'grap' &&
        new ScatterplotLayer({
          id: 'grap-ncr',
          data: [corridorDest],
          getPosition: (d: NamedPoint) => [d.lon, d.lat],
          getFillColor: [34, 211, 238, 28],
          getRadius: 42000,
          radiusUnits: 'meters',
          radiusMinPixels: 18,
          radiusMaxPixels: 90,
          stroked: true,
          getLineColor: [34, 211, 238, 160],
          getLineWidth: 2,
          lineWidthUnits: 'pixels',
        }),
      visible.evidence &&
        new TextLayer<EvidenceNode>({
          id: 'evidence-labels',
          data: shownNodes,
          getPosition: (d) => [d.lon, d.lat],
          getText: (d) => d.label,
          getSize: 11,
          getColor: [203, 213, 225, 225],
          // Radiates outward from the hub so neighbouring labels grow apart
          // instead of stacking in the same column above their dots.
          getPixelOffset: (d) => labelOffset(d.angleDeg),
          getTextAnchor: (d) => labelAnchor(d.angleDeg),
          getAlignmentBaseline: 'center',
          fontFamily: 'Inter, sans-serif',
          fontSettings: { sdf: true },
          outlineWidth: 2.5,
          outlineColor: [8, 12, 24, 230],
        }),
      visible.places &&
        new TextLayer<(typeof placeLabels)[number]>({
          id: 'place-labels',
          data: placeLabels,
          getPosition: (d) => [d.lon, d.lat],
          getText: (d) => d.name,
          getSize: 13,
          getColor: [248, 250, 252, 240],
          getPixelOffset: [0, 16],
          fontFamily: 'Inter, sans-serif',
          fontSettings: { sdf: true },
          outlineWidth: 3,
          outlineColor: [8, 12, 24, 230],
        }),
      visible.plume &&
        new TextLayer({
          id: 'transport-caption',
          data: [
            {
              lon: (event.lon + dest.lon) / 2,
              lat: (event.lat + dest.lat) / 2,
            },
          ],
          getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
          getText: () => 'PREDICTED transport',
          getSize: 12,
          getColor: [253, 224, 171, 220],
          getAngle: Math.atan2(dest.lat - event.lat, dest.lon - event.lon) * (180 / Math.PI),
          getPixelOffset: [0, -10],
          fontFamily: 'Inter, sans-serif',
          fontSettings: { sdf: true },
          outlineWidth: 3,
          outlineColor: [8, 12, 24, 200],
        }),
    ].filter(Boolean)
  }, [
    axis,
    arcs,
    chevrons,
    dest,
    event.lat,
    event.lon,
    hub,
    motes,
    nearbyFires,
    placeLabels,
    pulse,
    radarFires,
    ribbon,
    ribbonCore,
    rings,
    shownNodes,
    time,
    visible,
    scenario,
    corridorDest,
    horizon,
  ])

  return (
    <div className={cn('relative h-full w-full overflow-hidden bg-black', className)}>
      <div
        ref={mapContainerRef}
        className="absolute inset-0"
        style={{ position: 'absolute' }}
      />
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: next }) =>
          setViewState(next as typeof viewState)
        }
        controller={{
          scrollZoom: true,
          dragPan: true,
          dragRotate: false,
          doubleClickZoom: true,
        }}
        layers={layers}
        style={{ position: 'absolute', inset: '0', zIndex: '1' }}
      />
      <div className="pointer-events-none absolute left-3 top-3 z-10 flex flex-col gap-1">
        {visible.fires ? (
          <div className="rounded border border-orange-400/30 bg-black/60 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-orange-300/90">
            Observed · fire cluster
          </div>
        ) : null}
        {visible.plume ? (
          <div className="rounded border border-amber-300/25 bg-black/60 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-amber-200/90">
            {scenarioCaption(scenario, towardNcr, horizon)}
          </div>
        ) : null}
        {/* Plated like the chips above it: unbacked, the basemap's own
            place names read straight through the key. */}
        <div className="flex flex-wrap gap-2 rounded bg-black/55 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-text-muted">
          <span className="text-orange-300/90">● Fire observed</span>
          <span className="text-amber-200/80">● Plume predicted</span>
          <span className="text-sky-200/80">● Wind</span>
        </div>
      </div>
      <div className="absolute right-3 top-3 z-20 flex max-h-[calc(100%-5.5rem)] w-44 flex-col gap-2">
        {visible.wind ? (
          <div className="pointer-events-none rounded border border-sky-300/20 bg-black/55 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-sky-200/85">
            Wind from {WIND_FROM_DEG}° · {WIND_SPEED_MS} m/s
          </div>
        ) : null}
        {layersOpen ? (
          <DetectLayerPanel
            visible={visible}
            onToggle={toggleLayer}
            evidence={nodes}
            hiddenEvidenceIds={hiddenEvidenceIds}
            onToggleEvidence={toggleEvidence}
            onClose={() => setLayersOpen(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setLayersOpen(true)}
            className="pointer-events-auto rounded-lg border border-border bg-bg-panel/90 px-2.5 py-1.5 text-left font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted backdrop-blur hover:text-text-secondary"
          >
            Layers
          </button>
        )}
      </div>
      <DetectDecisionLab
        scenario={scenario}
        onScenario={setScenario}
        horizon={horizon}
        onHorizon={setHorizon}
        eventId={event.id}
        className="absolute bottom-[7.25rem] left-3 z-20"
      />
    </div>
  )
}

function DetectLayerPanel({
  visible,
  onToggle,
  evidence,
  hiddenEvidenceIds,
  onToggleEvidence,
  onClose,
}: {
  visible: Record<DetectLayerKey, boolean>
  onToggle: (key: DetectLayerKey) => void
  evidence: EvidenceNode[]
  hiddenEvidenceIds: Set<string>
  onToggleEvidence: (id: string) => void
  onClose: () => void
}) {
  return (
    <div
      className="pointer-events-auto overflow-auto rounded-lg border border-border bg-bg-panel/90 p-2 backdrop-blur"
      onMouseDown={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className="mb-1.5 flex items-center justify-between px-1">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">Layers</p>
        <button
          type="button"
          onClick={onClose}
          className="text-[10px] text-text-muted hover:text-text-secondary"
        >
          Hide
        </button>
      </div>
      <div className="flex flex-col gap-0.5">
        {DETECT_LAYER_OPTIONS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => onToggle(key)}
            aria-pressed={visible[key]}
            className={`rounded px-2 py-1 text-left text-xs transition-colors ${
              visible[key] ? 'bg-intel/20 text-intel' : 'text-text-muted hover:text-text-secondary'
            }`}
          >
            {visible[key] ? '☑' : '☐'} {label}
          </button>
        ))}
      </div>
      {visible.evidence && evidence.length > 0 ? (
        <div className="mt-2 border-t border-border/70 pt-2">
          <p className="mb-1 px-1 font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
            Evidence
          </p>
          <div className="flex flex-col gap-0.5">
            {evidence.map((item) => {
              const on = !hiddenEvidenceIds.has(item.id)
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onToggleEvidence(item.id)}
                  aria-pressed={on}
                  className={`rounded px-2 py-1 text-left text-[11px] transition-colors ${
                    on ? 'text-text-secondary hover:text-text-primary' : 'text-text-muted/70'
                  }`}
                >
                  {on ? '☑' : '☐'} {item.label}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}
