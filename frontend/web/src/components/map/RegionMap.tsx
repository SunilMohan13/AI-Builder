import { useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import { DeckGL } from '@deck.gl/react'
import type { PickingInfo } from '@deck.gl/core'
import { H3HexagonLayer } from '@deck.gl/geo-layers'
import { LineLayer, PathLayer, ScatterplotLayer } from '@deck.gl/layers'
import type {
  CitizenReportRow,
  Feature,
  FireCluster,
  GridCell,
  Plume,
  Region,
  WindVector,
} from '../../api/regionTypes'
import { rampColour } from '../../utils/concentration'
import { resolveBasemapStyle } from './basemapStyle'

export interface LayerToggles {
  cells: boolean
  fires: boolean
  wind: boolean
  plumes: boolean
  citizen: boolean
}

export type MapSelection =
  | { kind: 'cell'; cell: GridCell }
  | { kind: 'fire'; fire: FireCluster }
  | { kind: 'report'; report: CitizenReportRow }
  | { kind: 'plume'; plume: Plume }

type Point = { type: 'Point'; coordinates: [number, number] }

interface ViewState {
  longitude: number
  latitude: number
  zoom: number
  pitch: number
  bearing: number
}

interface Props {
  region: Region
  cells: GridCell[]
  fires: Feature<FireCluster, Point>[]
  wind: Feature<WindVector, Point>[]
  plumes: Plume[]
  /** Index into each plume's `horizons`. */
  horizonIndex: number
  reports: CitizenReportRow[]
  layers: LayerToggles
  /** Plumes of the selected incident are drawn brighter. */
  highlightPlumeIds: Set<string>
  /** `[lon, lat]` to centre on, close enough that 1 km cells are visible. */
  focus: [number, number] | null
  onSelect: (selection: MapSelection | null) => void
}

const FOCUS_ZOOM = 10.5

const WIND_DEG_PER_MS = 0.04

function windSegments(wind: Feature<WindVector, Point>[]) {
  return wind.flatMap((f) => {
    const [lon, lat] = f.geometry.coordinates
    const { wind_u: u, wind_v: v } = f.properties
    const tip: [number, number] = [lon + u * WIND_DEG_PER_MS, lat + v * WIND_DEG_PER_MS]
    const angle = Math.atan2(v, u)
    const head = Math.hypot(u, v) * WIND_DEG_PER_MS * 0.3
    const barb = (offset: number): [number, number] => [
      tip[0] - head * Math.cos(angle + offset),
      tip[1] - head * Math.sin(angle + offset),
    ]
    return [
      { from: [lon, lat] as [number, number], to: tip, f },
      { from: tip, to: barb(0.5), f },
      { from: tip, to: barb(-0.5), f },
    ]
  })
}

function bboxPath(bbox: [number, number, number, number]): [number, number][] {
  const [w, s, e, n] = bbox
  return [
    [w, s],
    [e, s],
    [e, n],
    [w, n],
    [w, s],
  ]
}

export function RegionMap(props: Props) {
  const { region, cells, fires, wind, plumes, horizonIndex, reports, layers, highlightPlumeIds, focus, onSelect } =
    props
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [offline, setOffline] = useState(false)
  const [view, setView] = useState<ViewState>(() => ({
    longitude: region.map_view.lon,
    latitude: region.map_view.lat,
    zoom: region.map_view.zoom,
    pitch: 0,
    bearing: 0,
  }))

  // A new region recentres on its pack's map view.
  useEffect(() => {
    setView({
      longitude: region.map_view.lon,
      latitude: region.map_view.lat,
      zoom: region.map_view.zoom,
      pitch: 0,
      bearing: 0,
    })
  }, [region.region_id, region.map_view.lat, region.map_view.lon, region.map_view.zoom])

  const [focusLon, focusLat] = focus ?? [null, null]
  useEffect(() => {
    if (focusLon === null || focusLat === null) return
    setView((v) => ({ ...v, longitude: focusLon, latitude: focusLat, zoom: Math.max(v.zoom, FOCUS_ZOOM) }))
  }, [focusLon, focusLat])

  // MapLibre is a passive basemap; deck.gl owns the camera.
  useEffect(() => {
    let cancelled = false
    let map: maplibregl.Map | null = null
    void resolveBasemapStyle().then(({ style, offline: isOffline }) => {
      if (cancelled || !container.current) return
      setOffline(isOffline)
      map = new maplibregl.Map({
        container: container.current,
        style,
        center: [region.map_view.lon, region.map_view.lat],
        zoom: region.map_view.zoom,
        interactive: false,
        attributionControl: { compact: true },
      })
      mapRef.current = map
    })
    return () => {
      cancelled = true
      map?.remove()
      mapRef.current = null
    }
    // The basemap is built once; the camera follows `view` below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    mapRef.current?.jumpTo({
      center: [view.longitude, view.latitude],
      zoom: view.zoom,
      bearing: view.bearing,
      pitch: view.pitch,
    })
  }, [view])

  const deckLayers = useMemo(() => {
    const out = []
    out.push(
      new PathLayer({
        id: 'region-outline',
        data: [{ path: bboxPath(region.bbox) }],
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: [34, 211, 238, 120],
        widthUnits: 'pixels',
        getWidth: 1.5,
      }),
    )
    if (layers.cells) {
      out.push(
        new H3HexagonLayer<GridCell>({
          id: 'cells',
          data: cells,
          getHexagon: (d) => d.grid_id,
          getFillColor: (d) => (d.pm25 === null ? [100, 116, 139, 90] : rampColour(d.pm25)),
          getLineColor: [15, 23, 42, 200],
          lineWidthMinPixels: 1,
          extruded: false,
          pickable: true,
          highPrecision: true,
        }),
      )
    }
    if (layers.plumes) {
      for (const plume of plumes) {
        const horizon = plume.horizons[Math.min(horizonIndex, plume.horizons.length - 1)]
        if (!horizon) continue
        const bright = highlightPlumeIds.size === 0 || highlightPlumeIds.has(plume.plume_id)
        const tint: [number, number, number] =
          plume.direction === 'forward' ? [167, 139, 250] : [244, 114, 182]
        out.push(
          new H3HexagonLayer<string>({
            id: `plume-p90-${plume.plume_id}`,
            data: horizon.p90_cells,
            getHexagon: (d) => d,
            getFillColor: [...tint, bright ? 55 : 18],
            stroked: false,
            extruded: false,
            pickable: true,
            onClick: () => onSelect({ kind: 'plume', plume }),
          }),
          new H3HexagonLayer<string>({
            id: `plume-p50-${plume.plume_id}`,
            data: horizon.p50_cells,
            getHexagon: (d) => d,
            getFillColor: [...tint, bright ? 140 : 40],
            stroked: false,
            extruded: false,
            pickable: true,
            onClick: () => onSelect({ kind: 'plume', plume }),
          }),
        )
      }
    }
    if (layers.wind) {
      out.push(
        new LineLayer({
          id: 'wind',
          data: windSegments(wind),
          getSourcePosition: (d: { from: [number, number] }) => d.from,
          getTargetPosition: (d: { to: [number, number] }) => d.to,
          getColor: [226, 232, 240, 200],
          getWidth: 2,
          widthUnits: 'pixels',
        }),
      )
    }
    if (layers.fires) {
      out.push(
        new ScatterplotLayer<Feature<FireCluster, Point>>({
          id: 'fires',
          data: fires,
          getPosition: (d) => d.geometry.coordinates,
          getRadius: (d) => 4 + Math.sqrt(Math.max(0, d.properties.frp ?? 0)),
          radiusUnits: 'pixels',
          getFillColor: [249, 115, 22, 230],
          getLineColor: [254, 215, 170, 255],
          stroked: true,
          lineWidthMinPixels: 1,
          pickable: true,
        }),
      )
    }
    if (layers.citizen) {
      out.push(
        new ScatterplotLayer<CitizenReportRow>({
          id: 'citizen',
          data: reports.filter((r) => r.lat_rounded !== null && r.lon_rounded !== null),
          getPosition: (d) => [d.lon_rounded!, d.lat_rounded!],
          getRadius: 7,
          radiusUnits: 'pixels',
          getFillColor: [217, 70, 239, 200],
          getLineColor: [250, 232, 255, 255],
          stroked: true,
          lineWidthMinPixels: 2,
          pickable: true,
        }),
      )
    }
    return out
  }, [region.bbox, layers, cells, plumes, horizonIndex, highlightPlumeIds, wind, fires, reports, onSelect])

  const onClick = (info: PickingInfo) => {
    if (!info.layer) return onSelect(null)
    const id = info.layer.id
    if (id === 'cells') onSelect({ kind: 'cell', cell: info.object as GridCell })
    else if (id === 'fires')
      onSelect({ kind: 'fire', fire: (info.object as Feature<FireCluster>).properties })
    else if (id === 'citizen') onSelect({ kind: 'report', report: info.object as CitizenReportRow })
  }

  const tooltip = (info: PickingInfo) => {
    if (!info.object || !info.layer) return null
    const id = info.layer.id
    if (id === 'cells') {
      const c = info.object as GridCell
      return `${c.pm25 === null ? 'PM2.5 —' : `PM2.5 ${c.pm25} µg/m³ (hourly)`}\n${c.provenance_class ?? 'provenance —'} · ${c.pm25_source_id ?? 'no source'}`
    }
    if (id === 'fires') {
      const f = (info.object as Feature<FireCluster>).properties
      return `Fire cluster · ${f.frp === null ? 'FRP —' : `${f.frp} MW`} · ${f.detection_count} detection(s)`
    }
    if (id === 'citizen') {
      const r = info.object as CitizenReportRow
      return `Citizen report · ${r.visual_class ?? 'not analysed'} (${r.visual_class_provenance ?? '—'})`
    }
    if (id.startsWith('plume-')) return 'Predicted smoke transport — experimental (simulated)'
    return null
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#070b12]">
      <div ref={container} className="absolute inset-0" />
      <DeckGL
        viewState={view}
        controller
        layers={deckLayers}
        onViewStateChange={({ viewState }) => setView(viewState as ViewState)}
        onClick={onClick}
        getTooltip={tooltip}
      />
      {offline && (
        <span className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-0.5 text-[10px] text-text-muted">
          Offline basemap (tile host unreachable)
        </span>
      )}
    </div>
  )
}
