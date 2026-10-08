import { Link } from 'react-router-dom'
import { Bot, X } from 'lucide-react'
import { getCitizenReports, getIncident, getPlumes, getSourceLikelihood } from '../../api/regions'
import type { Incident, Plume } from '../../api/regionTypes'
import { useRegion } from '../../context/RegionContext'
import { useRegionClock } from '../../hooks/useRegionClock'
import { useRegionLink } from '../../hooks/useRegionLink'
import { useRegionQuery } from '../../hooks/useRegionQuery'
import { formatDateTime, humanise, relativeTime } from '../../utils/format'
import {
  incidentCells,
  incidentEventIds,
  incidentPlumeIds,
  nodeFacts,
  nodeTitle,
  nodeValues,
  timeline,
} from '../../utils/incident'
import { QueryError } from '../common/Banners'
import { Missing, reasonFor } from '../common/Missing'
import { ProvenanceBadge } from '../common/ProvenanceBadge'
import { LoadingState } from '../common/States'
import { EdgeLegend, IncidentGraph } from './IncidentGraph'
import { LikelihoodRanking } from './LikelihoodRanking'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-border px-4 py-3">
      <h3 className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">{title}</h3>
      {children}
    </section>
  )
}

function PlumeSummary({ plume }: { plume: Plume }) {
  const last = plume.horizons.at(-1)
  return (
    <div className="rounded border border-border p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <ProvenanceBadge value={plume.provenance_class} />
        <span className="text-text-primary">
          {plume.direction === 'forward' ? 'Forward' : 'Back trajectory'} · {plume.label}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-text-muted">
        {plume.model_version} · from {humanise(plume.origin.kind)} · {plume.horizons.length} horizons
        {last ? ` to +${last.horizon_hours} h` : ''}
      </p>
      {plume.degraded && (
        <p className="mt-1 text-[11px] text-amber-300/90">
          Degraded: {plume.degraded_reasons.map(humanise).join('; ')}
        </p>
      )}
      {plume.direction === 'backward' && (
        <p className="mt-1 text-[11px] text-text-secondary">
          The likely source region of this air, not proof of what caused it.
        </p>
      )}
    </div>
  )
}

function Body({ incident }: { incident: Incident }) {
  const { region } = useRegion()
  const { now, timeZone } = useRegionClock()
  const link = useRegionLink()
  const plumes = useRegionQuery('plumes', getPlumes)
  const likelihood = useRegionQuery('likelihood', getSourceLikelihood)
  const reports = useRegionQuery('citizen', getCitizenReports)

  const plumeIds = incidentPlumeIds(incident)
  const cells = incidentCells(incident)
  const ownPlumes = (plumes.data?.items ?? []).filter((p) => plumeIds.has(p.plume_id))
  const ownLikelihood = (likelihood.data?.items ?? []).filter((l) => cells.has(l.grid_id))
  const ownReports = (reports.data?.items ?? []).filter((r) => r.incident_id === incident.incident_id)
  const arrivals = ownPlumes.filter((p) => p.direction === 'forward').flatMap((p) => p.arrivals)
  const snapshotStatus = region?.snapshot_field_status

  return (
    <>
      <Section title="Timeline">
        <ol className="space-y-2">
          {timeline(incident).map((node) => (
            <li key={node.node_id} className="text-xs">
              <div className="flex justify-between gap-2">
                <span className="text-text-primary">{nodeTitle(node)}</span>
                <span className="shrink-0 text-[10px] text-text-muted">
                  {formatDateTime(node.valid_from, timeZone)}
                </span>
              </div>
              {nodeValues(node).map(({ key, value }) => (
                <p key={key} className="flex flex-wrap items-center gap-1.5 text-[11px] text-text-secondary">
                  {humanise(key)}:{' '}
                  <span className="font-mono">
                    {value.value === null ? '—' : String(value.value)}
                    {value.unit ? ` ${value.unit}` : ''}
                  </span>
                  <ProvenanceBadge value={value.provenance_class} />
                  {value.source_id ? <span className="text-text-muted">{value.source_id}</span> : null}
                </p>
              ))}
              {nodeFacts(node).length > 0 && (
                <p className="text-[11px] text-text-muted">
                  {nodeFacts(node)
                    .map((f) => `${humanise(f.key)} ${f.value}`)
                    .join(' · ')}
                </p>
              )}
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Smoke transport">
        <QueryError error={plumes.error} what="Plumes" />
        {ownPlumes.length === 0 && !plumes.isLoading ? (
          <Missing reason="no plume is linked to this incident" />
        ) : (
          <div className="space-y-2">
            {ownPlumes.map((p) => (
              <PlumeSummary key={p.plume_id} plume={p} />
            ))}
          </div>
        )}
      </Section>

      <Section title="Places reached">
        {arrivals.length === 0 ? (
          <Missing reason={reasonFor(snapshotStatus, 'plumes.arrivals') ?? 'no place was reached'} />
        ) : (
          <ul className="space-y-1 text-xs">
            {arrivals.map((a, i) => (
              <li key={`${a.place_id}:${a.eta_hours_median ?? ''}:${i}`} className="flex justify-between">
                <span>{a.name}</span>
                <span className="font-mono text-text-muted">
                  share of members {a.probability} (simulated) · ETA{' '}
                  {a.eta_hours_median === null ? '—' : `${a.eta_hours_median} h`}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-[10px] text-text-muted">
          Exposure:{' '}
          {reasonFor(snapshotStatus, 'plumes.exposure') ? (
            <Missing reason={reasonFor(snapshotStatus, 'plumes.exposure')} />
          ) : (
            'see the plume detail'
          )}
        </p>
      </Section>

      <Section title="Source likelihood">
        <QueryError error={likelihood.error} what="Source likelihood" />
        {ownLikelihood.length === 0 && !likelihood.isLoading ? (
          <Missing reason="no source likelihood was served for this incident's cells" />
        ) : (
          <div className="space-y-3">
            {ownLikelihood.map((entry, i) => (
              <LikelihoodRanking
                key={`${entry.grid_id}:${entry.valid_at}:${i}`}
                entry={entry}
                hazards={region?.hazards ?? []}
              />
            ))}
          </div>
        )}
      </Section>

      <Section title="Citizen reports">
        {ownReports.length === 0 ? (
          <Missing reason="no report has been linked to this incident" />
        ) : (
          <ul className="space-y-1 text-xs">
            {ownReports.map((r) => (
              <li key={r.report_id} className="flex flex-wrap items-center gap-2">
                <Link to={link('/citizen', { report: r.report_id })} className="font-mono text-intel hover:underline">
                  {r.report_id}
                </Link>
                <span>{r.visual_class ?? '—'}</span>
                <ProvenanceBadge value={r.visual_class_provenance} />
                <span className="text-text-muted">corroboration {r.corroboration ?? '—'}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Graph">
        <IncidentGraph incident={incident} size={260} />
        <EdgeLegend />
        <Link to={link('/evidence', { incident: incident.incident_id })} className="mt-2 inline-block text-xs text-intel hover:underline">
          Open in Evidence →
        </Link>
      </Section>

      <Section title="Events">
        <ul className="space-y-1 text-xs">
          {incidentEventIds(incident).map((id) => (
            <li key={id}>
              <Link to={link(`/events/${id}`)} className="font-mono text-intel hover:underline">
                {id}
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[10px] text-text-muted">Updated {relativeTime(incident.last_updated, now)}</p>
      </Section>
    </>
  )
}

export function IncidentPanel({ incidentId, onClose }: { incidentId: string; onClose: () => void }) {
  const link = useRegionLink()
  const { timeZone } = useRegionClock()
  const incident = useRegionQuery('incident', (t) => getIncident(t, incidentId), { key: [incidentId] })

  return (
    <aside className="flex h-full w-[22rem] max-w-full shrink-0 flex-col overflow-y-auto border-l border-border bg-bg-elevated/95">
      <div className="flex items-start justify-between gap-2 px-4 py-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">Incident</p>
          <p className="break-all font-mono text-xs text-text-primary">{incidentId}</p>
          {incident.data && (
            <p className="mt-1 text-[11px] text-text-secondary">
              Root: {humanise(incident.data.root_kind)} · since{' '}
              {formatDateTime(incident.data.first_seen, timeZone)}
            </p>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label="Close incident" className="text-text-muted hover:text-text-primary">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="px-4 pb-3">
        <Link
          to={link('/copilot', { incident: incidentId })}
          className="inline-flex items-center gap-1.5 rounded-md border border-intel/30 bg-intel/10 px-3 py-1.5 text-xs text-intel hover:bg-intel/20"
        >
          <Bot className="h-3.5 w-3.5" /> Ask AeroPulse about this incident
        </Link>
      </div>
      {incident.isLoading && <LoadingState message="Loading incident…" />}
      <div className="px-4">
        <QueryError error={incident.error} what="Incident" />
      </div>
      {incident.data && <Body incident={incident.data} />}
    </aside>
  )
}
