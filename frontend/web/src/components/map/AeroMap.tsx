import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import * as maplibregl from 'maplibre-gl'
import { DeckGL } from '@deck.gl/react'
import { useQuery } from '@tanstack/react-query'
import type { GridCell, FireObservation, MapLayerVisibility } from '../../types'
import { cn } from '../../utils/cn'
import {
  buildSmokeParticles,
  buildFireRadarRings,
  createFireGlowLayer,
  createFireLayer,
  createFireRadarLayer,
  createGeographyLayer,
  createGlobeArcLayer,
  createIndustryLayer,
  createMonitoringNodesLayer,
  createOrbitalShellHaloLayer,
  createOrbitalShellLayer,
  createPlaceDotLayer,
  createPlaceLabelLayer,
  createBaselinePlumeLayer,
  createExposureRibbonLayer,
  createGrapZoneLayer,
  createPlumeLayer,
  createPollutionLayer,
  createPopulationLayer,
  createSmokeParticleLayer,
  createTransportAxisLayer,
  createWindLayer,
} from './layerFactories'
import { buildCorridorArcs, buildOrbitalShell } from './orbitalDecor'
import {
  applyMapAtmosphere,
  basemapUrl,
  type BasemapFlavor,
} from './mapAtmosphere'
import { MapGlobeBar } from './MapGlobeBar'
import { MapIntelChrome } from './MapIntelChrome'
import { softenBasemapLabels, syncGlobeIntelOverlays } from './globeIntelLayers'
import { MapViewControls, type MapScene } from './MapViewControls'
import { readViewFromMap, setMapInteraction } from './mapInteraction'
import { useApp } from '../../context/AppContext'
import { fetchAirQuality, fetchFires, fetchWeather, fetchIndustries } from '../../services/mapService'
import { resolveStep, stepToKm, type GridBounds } from '../../data/mockGrid'
import { MapPopup } from './MapPopup'
import { MapControls } from './MapControls'
import { MapToolbar } from './MapToolbar'
import { MapTimeline } from './MapTimeline'
import { MapLegend } from './MapLegend'
import { MapFusionStrip } from './MapFusionStrip'
import { MapScenarioPanel, MapStoryButton } from './MapScenarioPanel'
import { MapGrapBanner } from './MapGrapBanner'
import { MapStoryCaption } from './MapStoryCaption'
import {
  buildBaselinePlumeCells,
  buildExposureRibbonPath,
  GRAP_NCR_RING,
  grapPlumeIntersection,
} from './mapScenarioGeo'
import { CORRIDOR_LOCATIONS, PUNJAB_FIRE_CENTER, TRANSPORT_BEARING_DEG, type NamedLocation } from '../../utils/geo'
import { attachBasemapFallback } from './basemapStyle'
import { useAnimationClock } from '../../hooks/useAnimationClock'
import { useDataMode } from '../../context/DataModeContext'
import { useViewLevel } from '../../context/ViewLevelContext'
const CORRIDOR_VIEW = {
  longitude: 76.2,
  latitude: 29.8,
  zoom: 6.2,
  pitch: 0,
  bearing: 0,
}

const GLOBE_VIEW = {
  longitude: 72,
  latitude: 22,
  zoom: 2.15,
  pitch: 0,
  bearing: -12,
}

const INITIAL_VIEW = CORRIDOR_VIEW

type ViewState = typeof CORRIDOR_VIEW

const MIN_ZOOM = 1.6
const MAX_ZOOM = 13
const ZOOM_STEP = 0.9

const TILE_SIZE = 512

function mercatorY(lat: number): number {
  const rad = (lat * Math.PI) / 180
  return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2
}

function inverseMercatorY(y: number): number {
  const n = Math.PI * (1 - 2 * y)
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))
}

/**
 * Exact visible extent from the Web Mercator projection, over-scanned by
 * `pad`. The padding keeps the generated patch's edge off-screen — otherwise
 * the layer boundary shows up as a hard-edged rectangle over the basemap.
 */
function boundsFor(view: ViewState, width: number, height: number, pad = 1.5): GridBounds {
  const worldPx = TILE_SIZE * 2 ** view.zoom
  const spanLon = (360 * width * pad) / worldPx
  const dY = (height * pad) / (2 * worldPx)
  const yCenter = mercatorY(view.latitude)

  return {
    west: view.longitude - spanLon / 2,
    east: view.longitude + spanLon / 2,
    north: inverseMercatorY(Math.max(yCenter - dY, 1e-6)),
    south: inverseMercatorY(Math.min(yCenter + dY, 1 - 1e-6)),
  }
}

/** Snap bounds so small pans reuse the same query key instead of refetching. */
function quantise(bounds: GridBounds, q = 0.25): GridBounds {
  return {
    west: Math.floor(bounds.west / q) * q,
    east: Math.ceil(bounds.east / q) * q,
    south: Math.floor(bounds.south / q) * q,
    north: Math.ceil(bounds.north / q) * q,
  }
}

interface AeroMapProps {
  /** Preview mode: chrome-free map for embedding in a dashboard card. */
  compact?: boolean
  showControls?: boolean
  showTimeline?: boolean
  showLegend?: boolean
  /** Per-instance layer overrides, so a page can require its own layers
   *  without mutating the shared toggle state other pages read. */
  forceLayers?: Partial<MapLayerVisibility>
  /** Globe on load (Overview + Live Map). */
  initialScene?: MapScene
  /** Tour / deep-link: switch corridor vs globe when this changes. */
  sceneRequest?: MapScene
  /** Show Globe / Corridor bar inside compact dashboard cards. */
  showGlobeBar?: boolean
  /** Sit inside Detect rails: drop overlapping HUD chrome. */
  embedded?: boolean
  className?: string
}

export function AeroMap({
  compact = false,
  showControls = !compact,
  showTimeline = !compact,
  showLegend = !compact,
  forceLayers,
  initialScene = 'corridor',
  sceneRequest,
  showGlobeBar: showGlobeBarProp,
  embedded = false,
  className,
}: AeroMapProps) {
  const { mode } = useDataMode()
  const { advanced: advancedView } = useViewLevel()
  const scenarioChrome = mode === 'demo'
  // On the full map the scene switch already lives in the layers panel. The
  // bar stays for the globe, which is where the "enter the theater" call to
  // action belongs, and for previews that have no layers panel at all.
  const showGlobeBar = showGlobeBarProp ?? (compact || embedded)
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const {
    hourOffset,
    layers: globalLayers,
    setLayers,
    setHourOffset,
    demoIntensity,
    setSelectedFireId,
    setSelectedGridId,
    selectedFireId,
    windBearingOffset,
    showBaselinePlume,
    showGrapZone,
    showExposureRibbon,
    showFireSeasonGlobe,
    mapStoryCaption,
  } = useApp()
  const layers = useMemo(
    () => ({ ...globalLayers, ...forceLayers }),
    [globalLayers, forceLayers],
  )
  const [viewState, setViewState] = useState<ViewState>(
    initialScene === 'globe' ? GLOBE_VIEW : INITIAL_VIEW,
  )
  const time = useAnimationClock(24)
  const pulse = time * 1.6
  const [popupCell, setPopupCell] = useState<GridCell | null>(null)
  const [popupFire, setPopupFire] = useState<FireObservation | null>(null)
  const [offlineBasemap, setOfflineBasemap] = useState(false)
  const [size, setSize] = useState({ width: 1200, height: 600 })
  const [expanded, setExpanded] = useState(false)
  const [scene, setScene] = useState<MapScene>(initialScene)
  const [basemapFlavor, setBasemapFlavor] = useState<BasemapFlavor>('intel')
  const [dayNight, setDayNight] = useState(true)
  const [dimension3d, setDimension3d] = useState(false)
  const [showOrbit, setShowOrbit] = useState(true)
  const basemapFlavorRef = useRef(basemapFlavor)
  basemapFlavorRef.current = basemapFlavor
  const sceneRef = useRef(scene)
  const dayNightRef = useRef(dayNight)
  sceneRef.current = scene
  dayNightRef.current = dayNight
  const basemapAppliedRef = useRef(basemapFlavor)
  const skipMapSyncRef = useRef(false)

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  useEffect(() => {
    const el = mapContainerRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width <= 0 || height <= 0) return
      setSize({ width, height })
      // MapLibre latches its transform size at construction. If the container
      // had no layout yet, that transform stays 0x0 and the map silently never
      // requests a single tile, so it must be told about the new size.
      mapRef.current?.resize()
    })
    observer.observe(el)
    return () => observer.disconnect()
    // The observed element is replaced when the map moves into the portal.
  }, [expanded])

  const bounds = useMemo(
    () => quantise(boundsFor(viewState, size.width, size.height)),
    [viewState, size.width, size.height],
  )
  const boundsKey = `${bounds.west},${bounds.east},${bounds.south},${bounds.north}`
  const resolutionKm = useMemo(() => stepToKm(resolveStep(bounds)), [bounds])
  const transportBearing = TRANSPORT_BEARING_DEG + windBearingOffset

  const { data: grid = [] } = useQuery({
    queryKey: ['air-quality', mode, hourOffset, demoIntensity, boundsKey, windBearingOffset],
    queryFn: () => fetchAirQuality(hourOffset, demoIntensity, bounds, transportBearing),
    placeholderData: (previous) => previous,
    // Each snapshot is tens of MB and every hour/viewport combination is a
    // distinct key, so the default 5-minute retention accumulated gigabytes
    // while scrubbing the timeline and crashed the tab. Snapshots are cheap to
    // regenerate, so evict them almost immediately.
    gcTime: 10_000,
    staleTime: 10_000,
  })
  const { data: fires = [] } = useQuery({
    queryKey: ['fires', mode, hourOffset, demoIntensity],
    queryFn: () => fetchFires(hourOffset, demoIntensity),
    placeholderData: (previous) => previous,
  })
  const { data: wind = [] } = useQuery({ queryKey: ['wind', mode], queryFn: fetchWeather })
  const { data: industries = [] } = useQuery({
    queryKey: ['industries', mode],
    queryFn: fetchIndustries,
  })

  // Read without subscribing, so re-creating the map preserves the camera
  // instead of snapping back to the initial view.
  const viewRef = useRef(viewState)
  viewRef.current = viewState

  // MapLibre is a passive basemap; deck.gl owns interaction so the two
  // cannot fight over the camera. Expanding moves this subtree into a portal,
  // which destroys the container element, so the map is rebuilt alongside it.
  useEffect(() => {
    if (!mapContainerRef.current) return
    const view = viewRef.current
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: basemapUrl(basemapFlavorRef.current),
      center: [view.longitude, view.latitude],
      zoom: view.zoom,
      attributionControl: { compact: true },
      interactive: false,
    })
    mapRef.current = map
    if (import.meta.env.DEV) {
      ;(window as unknown as { __aeroMap?: maplibregl.Map }).__aeroMap = map
    }

    const onStyleReady = () => {
      applyMapAtmosphere(
        map,
        sceneRef.current === 'globe' ? 'globe' : 'mercator',
        dayNightRef.current,
      )
      setMapInteraction(map, sceneRef.current)
      softenBasemapLabels(map, sceneRef.current === 'globe')
      syncGlobeIntelOverlays(map, sceneRef.current === 'globe', scenarioChrome && showFireSeasonGlobe)
    }
    map.on('load', onStyleReady)
    map.on('style.load', onStyleReady)

    // Tile hosting can be blocked on demo networks; fall back to a bundled
    // style instead of showing an empty canvas.
    attachBasemapFallback(map, () => setOfflineBasemap(true))

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [expanded])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    applyMapAtmosphere(map, scene === 'globe' ? 'globe' : 'mercator', dayNight)
    setMapInteraction(map, scene)
  }, [scene, dayNight])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const applyIntel = () => {
      softenBasemapLabels(map, scene === 'globe')
      syncGlobeIntelOverlays(map, scene === 'globe' && showOrbit, scenarioChrome && showFireSeasonGlobe)
    }
    if (map.isStyleLoaded()) applyIntel()
    else map.once('style.load', applyIntel)
  }, [scene, showOrbit, expanded, basemapFlavor, showFireSeasonGlobe, scenarioChrome])

  useEffect(() => {
    const map = mapRef.current
    if (!map || scene !== 'globe') return

    const onMove = () => {
      if (skipMapSyncRef.current) return
      setViewState((prev) => ({ ...prev, ...readViewFromMap(map) }))
    }
    const onDragStart = () => {
      map.getCanvas().style.cursor = 'grabbing'
    }
    const onDragEnd = () => {
      map.getCanvas().style.cursor = 'grab'
    }

    map.on('move', onMove)
    map.on('dragstart', onDragStart)
    map.on('dragend', onDragEnd)
    return () => {
      map.off('move', onMove)
      map.off('dragstart', onDragStart)
      map.off('dragend', onDragEnd)
    }
  }, [scene, expanded])

  useEffect(() => {
    const map = mapRef.current
    if (!map || offlineBasemap || basemapAppliedRef.current === basemapFlavor) return
    basemapAppliedRef.current = basemapFlavor
    map.setStyle(basemapUrl(basemapFlavor))
    map.once('style.load', () => {
      applyMapAtmosphere(
        map,
        sceneRef.current === 'globe' ? 'globe' : 'mercator',
        dayNightRef.current,
      )
    })
  }, [basemapFlavor, offlineBasemap])

  const syncBasemap = useCallback((v: ViewState, animate = false) => {
    const map = mapRef.current
    if (!map) return
    skipMapSyncRef.current = true
    const camera = {
      center: [v.longitude, v.latitude] as [number, number],
      zoom: v.zoom,
      pitch: v.pitch,
      bearing: v.bearing,
    }
    if (animate) {
      map.flyTo({ ...camera, duration: 1400, essential: true })
    } else {
      map.jumpTo(camera)
    }
    window.setTimeout(() => {
      skipMapSyncRef.current = false
    }, animate ? 1500 : 0)
  }, [])

  const applyView = useCallback(
    (next: ViewState) => {
      const clamped = {
        ...next,
        pitch: dimension3d ? Math.min(Math.max(next.pitch ?? 48, 20), 58) : 0,
        zoom: Math.min(Math.max(next.zoom, MIN_ZOOM), MAX_ZOOM),
      }
      setViewState(clamped)
      syncBasemap(clamped)
    },
    [syncBasemap, dimension3d],
  )

  const zoomBy = useCallback(
    (delta: number) => {
      const map = mapRef.current
      if (scene === 'globe' && map) {
        const next = Math.min(Math.max(map.getZoom() + delta, MIN_ZOOM), MAX_ZOOM)
        map.zoomTo(next, { duration: 280 })
        setViewState((prev) => ({ ...prev, zoom: next }))
        return
      }
      applyView({ ...viewState, zoom: viewState.zoom + delta })
    },
    [applyView, viewState, scene],
  )
  const resetView = useCallback(
    () => applyView(scene === 'globe' ? GLOBE_VIEW : CORRIDOR_VIEW),
    [applyView, scene],
  )

  const goToScene = useCallback(
    (next: MapScene) => {
      setScene(next)
      const target = {
        ...(next === 'globe' ? GLOBE_VIEW : CORRIDOR_VIEW),
        pitch: next === 'globe' ? (dimension3d ? 48 : 0) : dimension3d ? 48 : 0,
        bearing: next === 'globe' ? GLOBE_VIEW.bearing : 0,
      }
      setViewState(target)
      syncBasemap(target, true)
    },
    [syncBasemap, dimension3d],
  )

  useEffect(() => {
    if (!sceneRequest || sceneRequest === scene) return
    goToScene(sceneRequest)
  }, [sceneRequest, scene, goToScene])

  const toggleScene = useCallback(() => {
    goToScene(scene === 'globe' ? 'corridor' : 'globe')
  }, [goToScene, scene])

  const enterTheater = useCallback(() => {
    goToScene('corridor')
    setLayers({
      pollution: true,
      fires: true,
      wind: true,
      forecast: true,
      industry: false,
      population: false,
    })
    setHourOffset(6)
    setViewState(CORRIDOR_VIEW)
    syncBasemap(CORRIDOR_VIEW, true)
  }, [goToScene, setLayers, setHourOffset, syncBasemap])

  const exportSnapshot = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    const link = document.createElement('a')
    link.download = `aeropulse-map-${Date.now()}.png`
    link.href = map.getCanvas().toDataURL('image/png')
    link.click()
  }, [])

  // deck.gl draws in Web Mercator; on MapLibre globe that misaligns and Punjab
  // fires/smoke look like they float in space. Environmental layers only in
  // corridor (flat) mode — globe is for world context + orbital decor only.
  const showEnvironmentalLayers = scene === 'corridor'

  const baselineGrid = useMemo(
    () => buildBaselinePlumeCells(grid, transportBearing),
    [grid, transportBearing],
  )
  const exposurePath = useMemo(
    () => buildExposureRibbonPath(grid, transportBearing),
    [grid, transportBearing],
  )
  const grapAlert = useMemo(
    () =>
      scenarioChrome && showGrapZone && showEnvironmentalLayers && grapPlumeIntersection(grid),
    [scenarioChrome, showGrapZone, showEnvironmentalLayers, grid],
  )
  const globeDecor = scene === 'globe'

  const orbitalPoints = useMemo(
    () => buildOrbitalShell(2600, time),
    [time],
  )
  const corridorArcs = useMemo(() => buildCorridorArcs(), [])

  const handleFireClick = useCallback(
    (fire: FireObservation) => {
      setSelectedFireId(fire.id)
      setPopupFire(fire)
      setPopupCell(null)
      applyView({ ...viewState, longitude: fire.lon, latitude: fire.lat, zoom: 8.5 })
    },
    [applyView, setSelectedFireId, viewState],
  )

  const handleCellClick = useCallback(
    (cell: GridCell) => {
      setSelectedGridId(cell.gridId)
      setPopupCell(cell)
      setPopupFire(null)
    },
    [setSelectedGridId],
  )

  // Each layer memoises independently so the animation clock only rebuilds the
  // cheap animated layers, never the large polygon fields.
  const pollutionLayer = useMemo(
    () =>
      createPollutionLayer(
        grid,
        showEnvironmentalLayers && layers.pollution,
        handleCellClick,
      ),
    [grid, layers.pollution, showEnvironmentalLayers, handleCellClick],
  )
  const baselinePlumeLayer = useMemo(
    () =>
      createBaselinePlumeLayer(
        baselineGrid,
        showEnvironmentalLayers && scenarioChrome && showBaselinePlume && layers.forecast,
      ),
    [baselineGrid, showBaselinePlume, layers.forecast, showEnvironmentalLayers, scenarioChrome],
  )
  const plumeLayer = useMemo(
    () => createPlumeLayer(grid, showEnvironmentalLayers && layers.forecast),
    [grid, layers.forecast, showEnvironmentalLayers],
  )
  const grapLayer = useMemo(
    () => createGrapZoneLayer(GRAP_NCR_RING, showEnvironmentalLayers && scenarioChrome && showGrapZone),
    [showGrapZone, showEnvironmentalLayers, scenarioChrome],
  )
  const exposureRibbonLayer = useMemo(
    () =>
      createExposureRibbonLayer(
        exposurePath,
        showEnvironmentalLayers && scenarioChrome && showExposureRibbon && layers.forecast,
      ),
    [exposurePath, showExposureRibbon, layers.forecast, showEnvironmentalLayers, scenarioChrome],
  )
  const populationLayer = useMemo(
    () => createPopulationLayer(grid, showEnvironmentalLayers && layers.population),
    [grid, layers.population, showEnvironmentalLayers],
  )
  const industryLayer = useMemo(
    () => createIndustryLayer(industries, showEnvironmentalLayers && layers.industry),
    [industries, layers.industry, showEnvironmentalLayers],
  )
  const axisLayer = useMemo(
    () =>
      createTransportAxisLayer(
        PUNJAB_FIRE_CENTER,
        CORRIDOR_LOCATIONS[0],
        showEnvironmentalLayers && (layers.forecast || layers.wind),
      ),
    [layers.forecast, layers.wind, showEnvironmentalLayers],
  )

  const particles = useMemo(() => buildSmokeParticles(520, fires.length), [fires.length])

  const labelPlaces = useMemo(
    () => CORRIDOR_LOCATIONS.filter((l) => !l.name.includes('cluster')),
    [],
  )
  // Coastlines, borders and city names duplicate what the real basemap draws,
  // so they only stand in when the basemap is the offline fallback.
  const geographyLayer = useMemo(
    () => createGeographyLayer(offlineBasemap),
    [offlineBasemap],
  )
  const placeDotLayer = useMemo(
    () => (offlineBasemap ? createPlaceDotLayer(labelPlaces) : null),
    [labelPlaces, offlineBasemap],
  )
  const placeLabelLayer = useMemo(
    () => (offlineBasemap ? createPlaceLabelLayer(labelPlaces, viewState.zoom) : null),
    [labelPlaces, offlineBasemap, viewState.zoom],
  )

  const fireGlowLayer = useMemo(
    () => createFireGlowLayer(fires, showEnvironmentalLayers && layers.fires, pulse),
    [fires, layers.fires, showEnvironmentalLayers, pulse],
  )
  const radarFires = useMemo(() => {
    if (fires.length === 0) return []
    const ranked = [...fires].sort((a, b) => b.frp - a.frp)
    const ids = new Set(ranked.slice(0, 2).map((f) => f.id))
    if (selectedFireId) ids.add(selectedFireId)
    return fires.filter((f) => ids.has(f.id))
  }, [fires, selectedFireId])
  const fireRadarLayer = useMemo(
    () =>
      createFireRadarLayer(
        buildFireRadarRings(radarFires, pulse, 4),
        showEnvironmentalLayers && layers.fires,
      ),
    [radarFires, pulse, layers.fires, showEnvironmentalLayers],
  )
  const fireLayer = useMemo(
    () => createFireLayer(fires, showEnvironmentalLayers && layers.fires, handleFireClick),
    [fires, layers.fires, showEnvironmentalLayers, handleFireClick],
  )
  const smokeLayer = useMemo(
    () =>
      createSmokeParticleLayer(
        particles,
        fires,
        showEnvironmentalLayers &&
          layers.fires &&
          (layers.forecast || layers.pollution),
        time,
        Math.max(hourOffset, 6),
        transportBearing,
      ),
    [
      particles,
      fires,
      layers.fires,
      layers.forecast,
      layers.pollution,
      showEnvironmentalLayers,
      time,
      hourOffset,
      transportBearing,
    ],
  )
  const windLayer = useMemo(
    () => createWindLayer(wind, showEnvironmentalLayers && layers.wind, time),
    [wind, layers.wind, showEnvironmentalLayers, time],
  )

  const orbitalHaloLayer = useMemo(
    () => createOrbitalShellHaloLayer(orbitalPoints, showOrbit && globeDecor, time),
    [orbitalPoints, showOrbit, globeDecor, time],
  )
  const orbitalLayer = useMemo(
    () => createOrbitalShellLayer(orbitalPoints, showOrbit && globeDecor, time),
    [orbitalPoints, showOrbit, globeDecor, time],
  )
  const globeArcLayer = useMemo(
    () => createGlobeArcLayer(corridorArcs, globeDecor, pulse),
    [corridorArcs, globeDecor, pulse],
  )
  const monitoringLayer = useMemo(
    () => createMonitoringNodesLayer(labelPlaces, globeDecor, pulse),
    [labelPlaces, globeDecor, pulse],
  )

  const deckLayers = useMemo(
    () =>
      (showEnvironmentalLayers
        ? [
            geographyLayer,
            grapLayer,
            pollutionLayer,
            baselinePlumeLayer,
            plumeLayer,
            exposureRibbonLayer,
            axisLayer,
            populationLayer,
            windLayer,
            industryLayer,
            fireGlowLayer,
            fireRadarLayer,
            smokeLayer,
            fireLayer,
            placeDotLayer,
            placeLabelLayer,
          ]
        : [orbitalHaloLayer, orbitalLayer]
      ).filter(Boolean),
    [
      showEnvironmentalLayers,
      geographyLayer,
      orbitalHaloLayer,
      orbitalLayer,
      globeArcLayer,
      monitoringLayer,
      grapLayer,
      pollutionLayer,
      baselinePlumeLayer,
      plumeLayer,
      exposureRibbonLayer,
      axisLayer,
      populationLayer,
      windLayer,
      industryLayer,
      fireGlowLayer,
      fireRadarLayer,
      smokeLayer,
      fireLayer,
      placeDotLayer,
      placeLabelLayer,
    ],
  )

  const zoomToFireCenter = useCallback(() => {
    applyView({
      ...viewState,
      longitude: PUNJAB_FIRE_CENTER.lon,
      latitude: PUNJAB_FIRE_CENTER.lat,
      zoom: 8,
    })
  }, [applyView, viewState])

  const goToLocation = useCallback(
    (location: NamedLocation) => {
      applyView({
        ...viewState,
        longitude: location.lon,
        latitude: location.lat,
        zoom: location.zoom,
      })
    },
    [applyView, viewState],
  )

  const closePopup = useCallback(() => {
    setPopupCell(null)
    setPopupFire(null)
    setSelectedFireId(null)
    setSelectedGridId(null)
  }, [setSelectedFireId, setSelectedGridId])

  // Expanding overrides the caller's sizing entirely and reveals the full
  // chrome, so a dashboard preview becomes a usable map without a route change.
  const chrome = expanded
    ? { controls: true, timeline: true, legend: true }
    : { controls: showControls, timeline: showTimeline, legend: showLegend }

  const content = (
    // `relative` is structural — the basemap and deck.gl canvas both position
    // against it — so it is always applied, never replaced by the caller.
    <div
      className={
        expanded
          ? 'fixed inset-0 z-50 bg-black'
          : cn('relative h-full w-full', scene === 'globe' && 'aero-map-space', className)
      }
    >
      {/* maplibre-gl.css sets `.maplibregl-map { position: relative }`, which
          beats the utility class and collapses this box to zero height (and
          then MapLibre requests no tiles at all). Inline style wins. */}
      <div
        ref={mapContainerRef}
        className="absolute inset-0"
        style={{
          position: 'absolute',
          zIndex: scene === 'globe' ? 3 : 0,
        }}
      />
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }) => {
          if (scene === 'globe') return
          applyView(vs as ViewState)
        }}
        controller={
          scene === 'globe'
            ? false
            : {
                inertia: 280,
                scrollZoom: true,
                dragPan: true,
                dragRotate: dimension3d,
                touchRotate: true,
                doubleClickZoom: true,
              }
        }
        style={{
          position: 'absolute',
          top: '0',
          left: '0',
          width: '100%',
          height: '100%',
          zIndex: scene === 'globe' ? '1' : '2',
          pointerEvents: scene === 'globe' ? 'none' : 'auto',
        }}
        layers={deckLayers}
        getTooltip={({ object }) => {
          if (!object) return null
          if ('frp' in object) return `Fire · FRP ${(object.frp as number).toFixed(0)} MW`
          if ('pm25' in object) return `PM2.5 ${object.pm25} µg/m³ · AQI ${object.aqi}`
          return null
        }}
      />
      {/* Connector freshness is engineering telemetry and repeats Source
          Health verbatim; it covers the map for everyone else. */}
      {advancedView && !compact && !embedded && (
        <MapFusionStrip className={scene === 'globe' ? 'top-12 sm:top-11' : undefined} />
      )}
      <MapToolbar
        scene={scene}
        onToggleScene={toggleScene}
        zoom={viewState.zoom}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        onZoomIn={() => zoomBy(ZOOM_STEP)}
        onZoomOut={() => zoomBy(-ZOOM_STEP)}
        onReset={resetView}
        expanded={expanded}
        onToggleExpand={() => setExpanded((v) => !v)}
        onExportSnapshot={scene === 'corridor' ? exportSnapshot : undefined}
      />
      {(showGlobeBar || (!compact && !embedded && scene === 'globe')) && (
        <MapGlobeBar
          scene={scene}
          onSceneChange={goToScene}
          bearing={viewState.bearing}
          onEnterTheater={enterTheater}
          compact={compact || embedded}
          className={!compact && chrome.timeline ? (embedded ? 'bottom-44' : 'bottom-40') : undefined}
        />
      )}
      {scenarioChrome && advancedView && !compact && !embedded && scene === 'globe' && (
        <MapIntelChrome scene={scene} />
      )}
      {/* A what-if wind dial and a persistence-baseline overlay are an
          analyst's tools; they read as clutter to anyone asking where the
          smoke is. The narrated story stays available to both. */}
      {scenarioChrome && !compact && !embedded && scene === 'corridor' && (
        advancedView ? (
          <MapScenarioPanel scene={scene} className="!right-20 !left-auto" />
        ) : (
          <MapStoryButton className="!right-20 !left-auto" />
        )
      )}
      {scenarioChrome && !compact && !embedded && <MapGrapBanner active={grapAlert} />}
      {scenarioChrome && !compact && <MapStoryCaption caption={mapStoryCaption} />}
      {!compact && !embedded && (
        <MapViewControls
          scene={scene}
          onSceneChange={goToScene}
          basemap={basemapFlavor}
          onBasemapChange={setBasemapFlavor}
          dayNight={dayNight}
          onDayNightChange={setDayNight}
          dimension3d={dimension3d}
          onDimension3dChange={(on) => {
            setDimension3d(on)
            applyView({ ...viewState, pitch: on ? 48 : 0 })
          }}
          showOrbit={showOrbit}
          onShowOrbitChange={setShowOrbit}
          className={
            scene === 'globe'
              ? '!bottom-auto top-[4.25rem] left-3 w-48 sm:top-[4rem]'
              : undefined
          }
        />
      )}
      {chrome.controls && (
        <MapControls
          scene={scene}
          onZoomToFire={zoomToFireCenter}
          onSelectLocation={goToLocation}
        />
      )}
      {chrome.legend && <MapLegend resolutionKm={resolutionKm} />}
      {(popupCell || popupFire) && (
        <MapPopup
          cell={popupCell}
          fire={popupFire}
          fires={fires}
          hourOffset={hourOffset}
          onClose={closePopup}
        />
      )}
      {/* Sits above the timeline panel, which previously covered it entirely. */}
      {offlineBasemap && (
        <div className="absolute bottom-32 left-4 z-10 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-300">
          Offline basemap — environmental layers unaffected
        </div>
      )}
      {chrome.timeline && <MapTimeline />}
    </div>
  )

  // Page wrappers use transforms for route transitions, and a transformed
  // ancestor becomes the containing block for `fixed` — so full screen only
  // truly covers the viewport from a portal on <body>.
  return expanded ? createPortal(content, document.body) : content
}
