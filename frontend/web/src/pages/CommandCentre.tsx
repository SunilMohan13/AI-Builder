import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Network } from 'lucide-react'
import { getCitizenReports, getFires, getGrid, getIncident, getPlumes, getWind } from '../api/regions'
import type { Feature, FireCluster, GridCell, WindVector } from '../api/regionTypes'
import { LiveFailureBanner, NotConfigured, QueryError, notConfigured } from '../components/common/Banners'
import { IncidentPanel } from '../components/incident/IncidentPanel'
import { MapLayerPanel } from '../components/map/MapLayerPanel'
import { loadBasemapTheme, saveBasemapTheme, type BasemapTheme } from '../components/map/basemapStyle'
import { RegionMap, type LayerToggles, type MapSelection } from '../components/map/RegionMap'
import { SelectionCard } from '../components/map/SelectionCard'
import { useRegion } from '../context/RegionContext'
import { useRegionClock } from '../hooks/useRegionClock'
import { useRegionIncidents } from '../hooks/useRegionEvents'
import { useRegionQuery } from '../hooks/useRegionQuery'
import { formatDateTime, humanise, relativeTime } from '../utils/format'
import { incidentFocus, incidentPlumeIds } from '../utils/incident'

type Point = { type: 'Point'; coordinates: [number, number] }

/** Live grid rows are H3 polygons without lat/lon on the properties. The ring centre is the cell. */
function cellFromFeature(feature: Feature<GridCell>): GridCell {
  const props = feature.properties
  if (Number.isFinite(props.lat) && Number.isFinite(props.lon)) return props
  const geometry = feature.geometry as { type?: string; coordinates?: unknown }
  if (geometry.type === 'Point' && Array.isArray(geometry.coordinates)) {
    const [lon, lat] = geometry.coordinates as number[]
    if (Number.isFinite(lon) && Number.isFinite(lat)) return { ...props, lon, lat }
  }
  if (geometry.type === 'Polygon' && Array.isArray(geometry.coordinates)) {
    const ring = (geometry.coordinates as number[][][])[0] ?? []
    const open =
      ring.length > 1 &&
      ring[0][0] === ring[ring.length - 1][0] &&
      ring[0][1] === ring[ring.length - 1][1]
        ? ring.slice(0, -1)
        : ring
    if (open.length > 0) {
      const lon = open.reduce((sum, point) => sum + point[0], 0) / open.length
      const lat = open.reduce((sum, point) => sum + point[1], 0) / open.length
      return { ...props, lon, lat }
    }
  }
  return props
}

/** A count, or "—" while loading or when its endpoint reports not configured. */
function Kpi({
  label,
  value,
  hint,
  body,
}: {
  label: string
  value: number | null
  hint: string
  body: Parameters<typeof notConfigured>[0]
}) {
  const missing = notConfigured(body)
  const title = missing ? `${hint}. Not configured: ${missing.reason ?? 'no snapshot for this region'}` : hint
  return (
    <div className="rounded-md border border-border bg-bg-panel/80 px-3 py-1.5" title={title}>
      <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">{label}</p>
      <p className="font-mono text-lg leading-tight">{value === null || missing ? '—' : value}</p>
    </div>
  )
}

function IncidentList({ onOpen }: { onOpen: (id: string) => void }) {
  const incidents = useRegionIncidents()
  const { now } = useRegionClock()
  const items = incidents.data?.items ?? []
  return (
    <aside className="flex h-full w-[22rem] max-w-full shrink-0 flex-col overflow-y-auto border-l border-border bg-bg-elevated/95">
      <div className="px-4 py-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">Open incidents</p>
        <p className="text-[11px] text-text-secondary">
          Linked anomalies, events, plumes and reports from the latest cycle.
        </p>
      </div>
      <div className="px-4">
        <QueryError error={incidents.error} what="Incidents" />
        <NotConfigured of={incidents.data} />
      </div>
      {items.map((i) => (
        <button
          key={i.incident_id}
          type="button"
          onClick={() => onOpen(i.incident_id)}
          className="flex gap-3 border-t border-border px-4 py-3 text-left hover:bg-bg-panel"
        >
          <Network className="mt-0.5 h-4 w-4 shrink-0 text-intel" />
          <div>
            <p className="text-sm">Root: {humanise(i.root_kind)}</p>
            <p className="break-all font-mono text-[11px] text-text-muted">{i.incident_id}</p>
            <p className="text-[10px] text-text-muted">
              {i.node_count} nodes · {i.edge_count} edges · updated {relativeTime(i.last_updated, now)}
            </p>
          </div>
        </button>
      ))}
      {incidents.data && items.length === 0 && !incidents.data.status && (
        <p className="px-4 py-3 text-xs text-text-muted">No open incidents in this region.</p>
      )}
    </aside>
  )
}

export function CommandCentre() {
  const { region } = useRegion()
  const { timeZone } = useRegionClock()
  const [params, setParams] = useSearchParams()
  const incidentId = params.get('incident')
  const [layers, setLayers] = useState<LayerToggles>({
    cells: true,
    fires: true,
    wind: true,
    plumes: true,
    citizen: true,
  })
  const [horizonIndex, setHorizonIndex] = useState(0)
  const [selection, setSelection] = useState<MapSelection | null>(null)
  const [basemap, setBasemap] = useState<BasemapTheme>(loadBasemapTheme)

  const grid = useRegionQuery('grid', getGrid, { refetchMs: 60_000 })
  const fires = useRegionQuery('fires', getFires, { refetchMs: 60_000 })
  const wind = useRegionQuery('wind', getWind, { refetchMs: 60_000 })
  const plumes = useRegionQuery('plumes', getPlumes)
  const reports = useRegionQuery('citizen', getCitizenReports)
  const incident = useRegionQuery('incident', (t) => getIncident(t, incidentId!), {
    key: [incidentId],
    enabled: incidentId !== null,
  })

  const highlight = useMemo(
    () => (incident.data ? incidentPlumeIds(incident.data) : new Set<string>()),
    [incident.data],
  )
  const focus = useMemo(() => (incident.data ? incidentFocus(incident.data) : null), [incident.data])
  const cells = useMemo(
    () => (grid.data?.features ?? []).map((feature) => cellFromFeature(feature)),
    [grid.data],
  )
  const plumeItems = useMemo(() => plumes.data?.items ?? [], [plumes.data])
  const horizons = useMemo(
    () => plumeItems.reduce<number[]>((best, p) => (p.horizons.length > best.length ? p.horizons.map((h) => h.horizon_hours) : best), []),
    [plumeItems],
  )

  const openIncident = useCallback(
    (id: string | null) =>
      setParams((current) => {
        const next = new URLSearchParams(current)
        if (id) next.set('incident', id)
        else next.delete('incident')
        return next
      }),
    [setParams],
  )

  if (!region) return <div className="p-6 text-sm text-text-muted">Loading region…</div>

  const valued = cells.filter((c) => c.pm25 !== null).length

  return (
    <div className="flex h-full min-h-[560px] flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2">
        <div className="mr-auto">
          <h1 className="text-base font-semibold">{region.display_name}</h1>
          <p className="text-[11px] text-text-muted">
            {region.snapshot?.cycle_time
              ? `Cycle ${formatDateTime(region.snapshot.cycle_time, timeZone)} · pack v${region.pack_version}`
              : 'No cycle has run for this region yet'}
          </p>
        </div>
        <Kpi
          label="Cells with PM2.5"
          value={grid.data ? valued : null}
          hint="Served cells with an hourly value"
          body={grid.data}
        />
        <Kpi
          label="Fire clusters"
          value={fires.data ? fires.data.features.length : null}
          hint="FIRMS clusters in the latest cycle"
          body={fires.data}
        />
        <Kpi
          label="Plumes"
          value={plumes.data ? plumes.data.total : null}
          hint="Forward and backward simulations"
          body={plumes.data}
        />
        <Kpi
          label="Reports"
          value={reports.data ? reports.data.total : null}
          hint="Citizen reports, last 30 days"
          body={null}
        />
      </div>
      <div className="space-y-2 px-4 pt-2 empty:hidden">
        <LiveFailureBanner />
        <NotConfigured of={grid.data} />
        <QueryError error={grid.error} what="Map cells" />
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <RegionMap
            region={region}
            cells={cells}
            fires={(fires.data?.features ?? []) as Feature<FireCluster, Point>[]}
            wind={(wind.data?.features ?? []) as Feature<WindVector, Point>[]}
            plumes={plumeItems}
            horizonIndex={horizonIndex}
            reports={reports.data?.items ?? []}
            layers={layers}
            highlightPlumeIds={highlight}
            focus={focus}
            basemap={basemap}
            onSelect={setSelection}
          />
          <div className="absolute left-3 top-3">
            <MapLayerPanel
              layers={layers}
              onToggle={(key) => setLayers((l) => ({ ...l, [key]: !l[key] }))}
              basemap={basemap}
              onBasemap={(theme) => {
                setBasemap(theme)
                saveBasemapTheme(theme)
              }}
              standard={region.aqi_standard}
              horizons={horizons}
              horizonIndex={Math.min(horizonIndex, Math.max(0, horizons.length - 1))}
              onHorizon={setHorizonIndex}
            />
          </div>
          {selection && (
            <div className="absolute bottom-8 left-3">
              <SelectionCard selection={selection} standard={region.aqi_standard} onClose={() => setSelection(null)} />
            </div>
          )}
        </div>
        {incidentId ? (
          <IncidentPanel incidentId={incidentId} onClose={() => openIncident(null)} />
        ) : (
          <IncidentList onOpen={openIncident} />
        )}
      </div>
    </div>
  )
}
