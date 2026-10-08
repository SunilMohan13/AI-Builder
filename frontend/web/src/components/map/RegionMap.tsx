import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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
import { rampColour, rampCss } from '../../utils/concentration'
import { FALLBACK_STYLE, resolveBasemapStyle, type BasemapTheme } from './basemapStyle'

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
  basemap: BasemapTheme
  onSelect: (selection: MapSelection | null) => void
}

const FOCUS_ZOOM = 10.5

/** One arrow per place: the latest served vector. Older rows at the same point would paint a fan. */
function latestWind(wind: Feature<WindVector, Point>[]): Feature<WindVector, Point>[] {
  const best = new Map<string, Feature<WindVector, Point>>()
  for (const feature of wind) {
    const [lon, lat] = feature.geometry.coordinates
    const props = feature.properties as WindVector & { grid_id?: string; observed_at?: string }
    const key = props.grid_id || props.site_id || `${lat.toFixed(2)},${lon.toFixed(2)}`
    const previous = best.get(key)
    const at = props.observed_at ?? ''
    const previousAt = previous
      ? ((previous.properties as WindVector & { observed_at?: string }).observed_at ?? '')
      : ''
    if (!previous || at >= previousAt) best.set(key, feature)
  }
  return [...best.values()]
}

function windSegments(wind: Feature<WindVector, Point>[], zoom: number) {
  return latestWind(wind).flatMap((f) => {
    const [lon, lat] = f.geometry.coordinates
    const { wind_u: u, wind_v: v } = f.properties
    const speed = Math.hypot(u, v)
    if (speed === 0) return []
    // Direction is the served wind. Length is a screen scale so the arrow
    // stays readable at a regional zoom; it is not a distance.
    const cos = Math.cos(lat * (Math.PI / 180))
    const metresPerPixel = (156543.03392 * cos) / 2 ** zoom
    const lengthPx = Math.min(26, Math.max(14, speed * 2.2))
    const lengthMetres = lengthPx * metresPerPixel
    const east = (u / speed) * lengthMetres
    const north = (v / speed) * lengthMetres
    const tip: [number, number] = [lon + east / (111_320 * cos), lat + north / 111_320]
    const angle = Math.atan2(north, east)
    const head = lengthPx * 0.35 * metresPerPixel
    const barb = (offset: number): [number, number] => {
      const a = angle + offset
      return [
        tip[0] - (head * Math.cos(a)) / (111_320 * cos),
        tip[1] - (head * Math.sin(a)) / 111_320,
      ]
    }
    return [
      { from: [lon, lat] as [number, number], to: tip },
      { from: tip, to: barb(0.45) },
      { from: tip, to: barb(-0.45) },
    ]
  })
}

function formatCellValue(value: number): string {
  const rounded = Math.round(value * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

function inkFor(rgb: [number, number, number]): [number, number, number, number] {
  const luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
  return luminance > 0.62 ? [15, 23, 42, 255] : [255, 255, 255, 255]
}

const LABEL_GAP_PX = 22

/** Web-mercator pixel, matching deck.gl at pitch 0 and bearing 0. */
function project(lon: number, lat: number, view: ViewState, width: number, height: number) {
  const scale = 512 * 2 ** view.zoom
  const world = (longitude: number, latitude: number) => {
    const x = (180 + longitude) / 360
    const sine = Math.sin((latitude * Math.PI) / 180)
    const y = 0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI)
    return [x * scale, y * scale]
  }
  const [x, y] = world(lon, lat)
  const [cx, cy] = world(view.longitude, view.latitude)
  return { x: width / 2 + (x - cx), y: height / 2 + (y - cy) }
}

interface CellTag {
  cell: GridCell
  x: number
  y: number
  lift: number
  rgb: [number, number, number]
}

/** The dot stays on the cell. Tags that would overlap step upward. */
function placeTags(cells: GridCell[], view: ViewState, width: number, height: number): CellTag[] {
  const placed: { x: number; y: number }[] = []
  return [...cells]
    .sort((a, b) => b.lat - a.lat || a.lon - b.lon)
    .map((cell) => {
      const { x, y } = project(cell.lon, cell.lat, view, width, height)
      let lift = 10
      while (placed.some((point) => Math.hypot(point.x - x, point.y - (y - lift)) < LABEL_GAP_PX)) {
        lift += LABEL_GAP_PX
      }
      placed.push({ x, y: y - lift })
      const rgb: [number, number, number] =
        cell.pm25 === null ? [100, 116, 139] : (rampColour(cell.pm25).slice(0, 3) as [number, number, number])
      return { cell, x, y, lift, rgb }
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
  const { region, cells, fires, wind, plumes, horizonIndex, reports, layers, highlightPlumeIds, focus, basemap, onSelect } =
    props
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const viewRef = useRef<ViewState | null>(null)
  const [offline, setOffline] = useState(false)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [view, setView] = useState<ViewState>(() => ({
    longitude: region.map_view.lon,
    latitude: region.map_view.lat,
    zoom: region.map_view.zoom,
    pitch: 0,
    bearing: 0,
  }))
  viewRef.current = view

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
  // Wait until the pane has a real size. A map built against a 0×0 box never
  // paints, and `load` never fires if the style request fails, so resize-on-load
  // alone leaves the canvas blank.
  useEffect(() => {
    const el = container.current
    if (!el) return
    let cancelled = false
    let map: maplibregl.Map | null = null
    let sized: ResizeObserver | null = null
    let usingRemote = false

    const boot = () => {
      if (cancelled || map || el.clientWidth < 2 || el.clientHeight < 2) return
      void resolveBasemapStyle(basemap).then(({ style, offline: isOffline }) => {
        if (cancelled || map || !container.current) return
        usingRemote = !isOffline
        setOffline(isOffline)
        const camera = viewRef.current
        map = new maplibregl.Map({
          container: el,
          style,
          center: [camera?.longitude ?? region.map_view.lon, camera?.latitude ?? region.map_view.lat],
          zoom: camera?.zoom ?? region.map_view.zoom,
          interactive: false,
          attributionControl: { compact: true },
          fadeDuration: 0,
        })
        const resize = () => map?.resize()
        map.on('load', resize)
        map.on('error', (event) => {
          if (!usingRemote || cancelled || !map) return
          const message = String(event.error?.message ?? '')
          if (!/failed to fetch|ajaxerror|style\.json/i.test(message)) return
          usingRemote = false
          setOffline(true)
          map.setStyle(FALLBACK_STYLE)
          resize()
        })
        sized = new ResizeObserver(resize)
        sized.observe(el)
        mapRef.current = map
        resize()
      })
    }

    const wait = new ResizeObserver(() => {
      if (el.clientWidth >= 2 && el.clientHeight >= 2) boot()
    })
    wait.observe(el)
    boot()

    return () => {
      cancelled = true
      wait.disconnect()
      sized?.disconnect()
      map?.remove()
      mapRef.current = null
    }
    // Rebuild only when the basemap theme changes. The camera is read from
    // viewRef so a switch keeps the place the operator is looking at.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap])

  useEffect(() => {
    mapRef.current?.jumpTo({
      center: [view.longitude, view.latitude],
      zoom: view.zoom,
      bearing: view.bearing,
      pitch: view.pitch,
    })
  }, [view])

  useLayoutEffect(() => {
    const el = container.current
    if (!el) return
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const tags = useMemo(
    () => (layers.cells && size.w >= 2 ? placeTags(cells, view, size.w, size.h) : []),
    [layers.cells, cells, view, size],
  )

  const deckLayers = useMemo(() => {
    const out = []
    out.push(
      new PathLayer({
        id: 'region-outline',
        data: [{ path: bboxPath(region.bbox) }],
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: [8, 145, 178, 220],
        widthUnits: 'pixels',
        getWidth: 2,
      }),
    )
    if (layers.cells) {
      out.push(
        new H3HexagonLayer<GridCell>({
          id: 'cells',
          data: cells,
          getHexagon: (d) => d.grid_id,
          getFillColor: (d) => (d.pm25 === null ? [100, 116, 139, 160] : rampColour(d.pm25, 210)),
          getLineColor: [15, 23, 42, 230],
          lineWidthMinPixels: 1.5,
          extruded: false,
          material: false,
          pickable: true,
          highPrecision: true,
          filled: true,
          stroked: true,
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
            getFillColor: [...tint, bright ? 90 : 36],
            stroked: false,
            extruded: false,
            pickable: true,
            onClick: () => onSelect({ kind: 'plume', plume }),
          }),
          new H3HexagonLayer<string>({
            id: `plume-p50-${plume.plume_id}`,
            data: horizon.p50_cells,
            getHexagon: (d) => d,
            getFillColor: [...tint, bright ? 170 : 70],
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
          data: windSegments(wind, view.zoom),
          getSourcePosition: (d: { from: [number, number] }) => d.from,
          getTargetPosition: (d: { to: [number, number] }) => d.to,
          getColor: basemap === 'light' ? [30, 64, 175, 230] : [125, 211, 252, 230],
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
          getRadius: (d) => 8 + Math.sqrt(Math.max(0, d.properties.frp ?? 0)),
          radiusUnits: 'pixels',
          radiusMinPixels: 8,
          getFillColor: [249, 115, 22, 240],
          getLineColor: [255, 255, 255, 255],
          stroked: true,
          lineWidthMinPixels: 2,
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
          getRadius: 9,
          radiusUnits: 'pixels',
          radiusMinPixels: 9,
          getFillColor: [217, 70, 239, 230],
          getLineColor: [255, 255, 255, 255],
          stroked: true,
          lineWidthMinPixels: 2,
          pickable: true,
        }),
      )
    }
    return out
  }, [region.bbox, layers, cells, plumes, horizonIndex, highlightPlumeIds, wind, fires, reports, onSelect, view.zoom, basemap])

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
      <div ref={container} className="absolute inset-0 h-full w-full" />
      <DeckGL
        viewState={view}
        controller
        layers={deckLayers}
        onViewStateChange={({ viewState }) => setView(viewState as ViewState)}
        onClick={onClick}
        getTooltip={tooltip}
        style={{ position: 'absolute', inset: '0', width: '100%', height: '100%', background: 'transparent' }}
      />
      <div className="pointer-events-none absolute inset-0 z-10">
        {tags.map((tag) => {
          if (!Number.isFinite(tag.x) || !Number.isFinite(tag.y)) return null
          if (tag.x < -40 || tag.y < -40 || tag.x > size.w + 40 || tag.y > size.h + 40) return null
          const text = tag.cell.pm25 === null ? '—' : formatCellValue(tag.cell.pm25)
          const ink = inkFor(tag.rgb)
          const colour = tag.cell.pm25 === null ? 'rgb(100 116 139)' : rampCss(tag.cell.pm25)
          const detail =
            tag.cell.pm25 === null
              ? 'PM2.5 —'
              : `PM2.5 ${tag.cell.pm25} µg/m³ (hourly) · ${tag.cell.provenance_class ?? 'provenance —'}`
          return (
            <div key={`${tag.cell.grid_id}:${tag.cell.observed_at ?? ''}`}>
              <span
                className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow"
                style={{ left: `${tag.x}px`, top: `${tag.y}px`, background: colour }}
              />
              <span
                className="absolute w-px"
                style={{
                  left: `${tag.x}px`,
                  top: `${tag.y - tag.lift}px`,
                  height: `${tag.lift}px`,
                  background: colour,
                }}
              />
              <button
                type="button"
                title={detail}
                onClick={() => onSelect({ kind: 'cell', cell: tag.cell })}
                className="pointer-events-auto absolute -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-full border border-slate-900 px-1.5 py-0.5 text-[12px] font-bold leading-none shadow-md"
                style={{
                  left: `${tag.x}px`,
                  top: `${tag.y - tag.lift}px`,
                  background: colour,
                  color: `rgb(${ink[0]} ${ink[1]} ${ink[2]})`,
                }}
              >
                {text}
              </button>
            </div>
          )
        })}
      </div>
      {offline && (
        <span className="absolute bottom-2 left-2 z-10 rounded bg-black/60 px-2 py-0.5 text-[10px] text-text-muted">
          Offline basemap (tile host unreachable)
        </span>
      )}
    </div>
  )
}
