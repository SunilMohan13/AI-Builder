import { Link, useParams } from 'react-router-dom'
import { getEvent } from '../api/regions'
import type { PollutionEvent } from '../api/regionTypes'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { LiveFailureBanner, NotConfigured, QueryError } from '../components/common/Banners'
import { Value } from '../components/common/Missing'
import { ProvenanceBadge } from '../components/common/ProvenanceBadge'
import { LoadingState } from '../components/common/States'
import { useRegionClock } from '../hooks/useRegionClock'
import { useRegionEvents, useRegionIncidents } from '../hooks/useRegionEvents'
import { useRegionLink } from '../hooks/useRegionLink'
import { useRegionQuery } from '../hooks/useRegionQuery'
import { formatDateTime } from '../utils/format'

const SEVERITY_STYLE: Record<string, string> = {
  LOW: 'text-emerald-300',
  MEDIUM: 'text-amber-300',
  HIGH: 'text-orange-400',
  SEVERE: 'text-red-400',
}

const CONFIDENCES: [keyof PollutionEvent, string][] = [
  ['detection_confidence', 'Detection'],
  ['source_confidence', 'Source'],
  ['forecast_confidence', 'Forecast'],
  ['impact_confidence', 'Impact'],
  ['overall_confidence', 'Overall'],
  ['sensor_coverage', 'Sensor coverage'],
]

function useIncidentFor(eventId: string): string | null {
  const incidents = useRegionIncidents()
  return (
    incidents.data?.items.find((i) => i.node_ids.some((n) => n.endsWith(`:${eventId}`)))?.incident_id ?? null
  )
}

function EventDetail({ eventId }: { eventId: string }) {
  const { timeZone } = useRegionClock()
  const link = useRegionLink()
  const event = useRegionQuery('event', (t, rid) => getEvent(t, rid, eventId), { key: [eventId] })
  const incidentId = useIncidentFor(eventId)

  if (event.isLoading) return <LoadingState message="Loading event…" />
  if (event.error || !event.data) return <QueryError error={event.error} what="Event" />
  const e = event.data
  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-mono text-xs text-text-muted">{e.event_id}</p>
          <p className={`text-lg font-semibold ${SEVERITY_STYLE[e.severity] ?? ''}`}>
            {e.severity} · {e.status}
          </p>
        </div>
        <ProvenanceBadge value="heuristic" />
      </CardHeader>
      <CardBody className="space-y-4 text-sm">
        <p className="text-xs text-text-secondary">
          Detected by deterministic rules over measured inputs. Confidences are rule outputs on a
          0–1 scale, not calibrated probabilities.
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {CONFIDENCES.map(([key, label]) => (
            <div key={key} className="rounded border border-border px-2 py-1">
              <p className="text-[10px] text-text-muted">{label}</p>
              <Value value={e[key] as number | null} decimals={4} reason="the rule produced no value" />
            </div>
          ))}
        </div>
        <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-text-muted">Pollutants</dt>
          <dd>{e.pollutants.join(', ') || '—'}</dd>
          <dt className="text-text-muted">Cells</dt>
          <dd className="font-mono">{e.grid_ids.join(', ') || '—'}</dd>
          <dt className="text-text-muted">Models</dt>
          <dd className="font-mono">{e.model_versions.join(', ') || '—'}</dd>
          <dt className="text-text-muted">Evidence</dt>
          <dd className="font-mono">{e.evidence_ids.length} records</dd>
          <dt className="text-text-muted">Created</dt>
          <dd>{formatDateTime(e.created_at, timeZone)}</dd>
          <dt className="text-text-muted">Updated</dt>
          <dd>{formatDateTime(e.updated_at, timeZone)}</dd>
        </dl>
        {incidentId ? (
          <Link to={link('/', { incident: incidentId })} className="text-xs text-intel hover:underline">
            Open its incident on the map →
          </Link>
        ) : (
          <p className="text-xs text-text-muted">— (no incident groups this event)</p>
        )}
      </CardBody>
    </Card>
  )
}

export function Events() {
  const { eventId } = useParams()
  const link = useRegionLink()
  const { timeZone } = useRegionClock()
  const events = useRegionEvents()

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Events</h1>
        <p className="text-sm text-text-secondary">
          What the deterministic event rules detected in the latest cycle.
        </p>
      </div>
      <LiveFailureBanner />
      <NotConfigured of={events.data} />
      <QueryError error={events.error} what="Events" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Card>
          <CardBody className="p-0">
            {events.isLoading && <LoadingState message="Loading events…" />}
            <ul className="divide-y divide-border">
              {(events.data?.items ?? []).map((e) => (
                <li key={e.event_id}>
                  <Link
                    to={link(`/events/${e.event_id}`)}
                    className={`block px-4 py-3 hover:bg-bg-elevated ${e.event_id === eventId ? 'bg-intel/5' : ''}`}
                  >
                    <div className="flex justify-between gap-2 text-sm">
                      <span className={SEVERITY_STYLE[e.severity] ?? ''}>
                        {e.severity} · {e.status}
                      </span>
                      <span className="text-[11px] text-text-muted">{formatDateTime(e.updated_at, timeZone)}</span>
                    </div>
                    <p className="font-mono text-[11px] text-text-muted">{e.event_id}</p>
                  </Link>
                </li>
              ))}
            </ul>
            {events.data && events.data.items.length === 0 && (
              <p className="px-4 py-6 text-sm text-text-muted">No open events.</p>
            )}
          </CardBody>
        </Card>
        {eventId ? (
          <EventDetail eventId={eventId} />
        ) : (
          <p className="text-sm text-text-muted">Select an event to see its evidence.</p>
        )}
      </div>
    </div>
  )
}
