import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Network, X } from 'lucide-react'
import { useApp } from '../../context/AppContext'
import { useRegion } from '../../context/RegionContext'
import { useRegionEvents, useRegionIncidents } from '../../hooks/useRegionEvents'
import { useRegionClock } from '../../hooks/useRegionClock'
import { useRegionLink } from '../../hooks/useRegionLink'
import { relativeTime } from '../../utils/format'
import { notConfigured } from '../common/Banners'

/**
 * What is open in the selected region: incidents and the events behind them.
 * Read from the region's latest cycle; there is no push delivery yet.
 */
export function NotificationDrawer() {
  const { notificationsOpen, setNotificationsOpen } = useApp()
  if (!notificationsOpen) return null
  return <Drawer onClose={() => setNotificationsOpen(false)} />
}

function Drawer({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const link = useRegionLink()
  const { region } = useRegion()
  const { now } = useRegionClock()
  const events = useRegionEvents()
  const incidents = useRegionIncidents()
  const go = (path: string) => {
    navigate(path)
    onClose()
  }
  const unconfigured = notConfigured(events.data)

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="h-full w-96 max-w-full overflow-y-auto border-l border-border bg-bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 className="font-semibold">Open in {region?.display_name ?? 'this region'}</h2>
            <p className="text-[11px] text-text-muted">From the latest cycle; no push alerts yet.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4 text-text-muted" />
          </button>
        </div>

        {unconfigured && (
          <p className="px-4 py-6 text-sm text-text-muted">
            Not configured: {unconfigured.reason ?? 'no cycle has run for this region'}.
          </p>
        )}
        {events.error ? (
          <p className="px-4 py-6 text-sm text-amber-300">Events did not load.</p>
        ) : null}

        {(incidents.data?.items ?? []).map((i) => (
          <button
            key={i.incident_id}
            type="button"
            onClick={() => go(link('/', { incident: i.incident_id }))}
            className="flex w-full gap-3 border-b border-border px-4 py-3 text-left hover:bg-bg-elevated"
          >
            <Network className="mt-0.5 h-4 w-4 shrink-0 text-intel" />
            <div>
              <p className="text-sm font-medium">Incident · {i.root_kind}</p>
              <p className="font-mono text-[11px] text-text-secondary">{i.incident_id}</p>
              <p className="mt-1 text-[10px] text-text-muted">
                {i.node_count} linked nodes · updated {relativeTime(i.last_updated, now)}
              </p>
            </div>
          </button>
        ))}

        {(events.data?.items ?? []).map((e) => (
          <button
            key={e.event_id}
            type="button"
            onClick={() => go(link(`/events/${e.event_id}`))}
            className="flex w-full gap-3 border-b border-border px-4 py-3 text-left hover:bg-bg-elevated"
          >
            <AlertTriangle
              className={`mt-0.5 h-4 w-4 shrink-0 ${e.severity === 'HIGH' || e.severity === 'SEVERE' ? 'text-red-400' : 'text-amber-300'}`}
            />
            <div>
              <p className="text-sm font-medium">
                {e.severity} · {e.status}
              </p>
              <p className="font-mono text-[11px] text-text-secondary">{e.event_id}</p>
              <p className="mt-1 text-[10px] text-text-muted">
                updated {relativeTime(e.updated_at, now)}
              </p>
            </div>
          </button>
        ))}

        {!unconfigured && events.data && events.data.items.length === 0 && (
          <p className="px-4 py-6 text-sm text-text-muted">No open events in this region.</p>
        )}
      </div>
    </div>
  )
}
