import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getIncident } from '../api/regions'
import type { GraphNode, Incident } from '../api/regionTypes'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { LiveFailureBanner, NotConfigured, QueryError } from '../components/common/Banners'
import { ProvenanceBadge } from '../components/common/ProvenanceBadge'
import { EmptyState, LoadingState } from '../components/common/States'
import { EdgeLegend, IncidentGraph } from '../components/incident/IncidentGraph'
import { useRegionClock } from '../hooks/useRegionClock'
import { useRegionIncidents } from '../hooks/useRegionEvents'
import { useRegionQuery } from '../hooks/useRegionQuery'
import { formatDateTime, humanise } from '../utils/format'
import { nodeFacts, nodeRef, nodeTitle, nodeValues } from '../utils/incident'

function NodeDetail({ incident, node }: { incident: Incident; node: GraphNode }) {
  const { timeZone } = useRegionClock()
  const edges = incident.edges.filter((e) => e.src === node.node_id || e.dst === node.node_id)
  const titleOf = (id: string) => {
    const other = incident.nodes.find((n) => n.node_id === id)
    return other ? nodeTitle(other) : nodeRef(id)
  }
  return (
    <div className="space-y-3 text-xs">
      <div>
        <p className="text-sm font-medium">{nodeTitle(node)}</p>
        <p className="break-all font-mono text-[10px] text-text-muted">{node.node_id}</p>
        <p className="text-[11px] text-text-muted">
          Valid from {formatDateTime(node.valid_from, timeZone)}
          {node.valid_to ? ` to ${formatDateTime(node.valid_to, timeZone)}` : ''}
        </p>
      </div>
      {nodeValues(node).length > 0 && (
        <table className="w-full">
          <tbody>
            {nodeValues(node).map(({ key, value }) => (
              <tr key={key} className="border-t border-border/60">
                <td className="py-1 pr-2 text-text-secondary">{humanise(key)}</td>
                <td className="py-1 pr-2 font-mono">
                  {value.value === null ? '—' : String(value.value)}
                  {value.unit ? ` ${value.unit}` : ''}
                </td>
                <td className="py-1">
                  <ProvenanceBadge value={value.provenance_class} />
                </td>
                <td className="py-1 pl-2 text-text-muted">{value.source_id ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {nodeFacts(node).length > 0 && (
        <p className="text-text-secondary">
          {nodeFacts(node)
            .map((f) => `${humanise(f.key)}: ${f.value}`)
            .join(' · ')}
        </p>
      )}
      <div>
        <p className="mb-1 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">Edges</p>
        <ul className="space-y-1">
          {edges.map((e) => (
            <li key={e.edge_id} className="flex flex-wrap items-center gap-1.5">
              <ProvenanceBadge value={e.provenance_class} />
              <span>
                {e.src === node.node_id ? (
                  <>
                    {humanise(e.kind)} → {titleOf(e.dst)}
                  </>
                ) : (
                  <>
                    {titleOf(e.src)} → {humanise(e.kind)}
                  </>
                )}
              </span>
              <span className="text-text-muted">({e.producer})</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function IncidentEvidence({ incidentId }: { incidentId: string }) {
  const incident = useRegionQuery('incident', (t) => getIncident(t, incidentId), { key: [incidentId] })
  const [selected, setSelected] = useState<string | null>(null)
  if (incident.isLoading) return <LoadingState message="Loading incident graph…" />
  if (!incident.data) return <QueryError error={incident.error} what="Incident" />
  const node =
    incident.data.nodes.find((n) => n.node_id === selected) ??
    incident.data.nodes.find((n) => n.kind === 'incident') ??
    null
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <Card>
        <CardHeader>
          <p className="text-sm font-medium">
            {incident.data.nodes.length} nodes · {incident.data.edges.length} edges
          </p>
          <EdgeLegend />
        </CardHeader>
        <CardBody>
          <IncidentGraph
            incident={incident.data}
            selectedId={node?.node_id ?? null}
            onSelect={(n) => setSelected(n.node_id)}
            size={420}
          />
        </CardBody>
      </Card>
      <Card>
        <CardBody>{node && <NodeDetail incident={incident.data} node={node} />}</CardBody>
      </Card>
    </div>
  )
}

export function Evidence() {
  const incidents = useRegionIncidents()
  const [params, setParams] = useSearchParams()
  const items = incidents.data?.items ?? []
  const requested = params.get('incident')
  const incidentId = items.some((i) => i.incident_id === requested) ? requested : (items[0]?.incident_id ?? null)

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Evidence</h1>
          <p className="text-sm text-text-secondary">
            The intelligence graph behind each incident. Every node and edge states its provenance.
          </p>
        </div>
        {items.length > 1 && (
          <select
            value={incidentId ?? ''}
            onChange={(e) =>
              setParams((p) => {
                const next = new URLSearchParams(p)
                next.set('incident', e.target.value)
                return next
              })
            }
            className="rounded border border-border bg-bg-panel px-2 py-1 font-mono text-xs"
          >
            {items.map((i) => (
              <option key={i.incident_id} value={i.incident_id}>
                {i.incident_id} · {i.root_kind}
              </option>
            ))}
          </select>
        )}
      </div>
      <LiveFailureBanner />
      <NotConfigured of={incidents.data} />
      <QueryError error={incidents.error} what="Incidents" />
      {incidents.isLoading && <LoadingState message="Loading incidents…" />}
      {incidentId ? (
        <IncidentEvidence key={incidentId} incidentId={incidentId} />
      ) : (
        incidents.data &&
        !incidents.data.status && (
          <EmptyState title="No open incidents" description="The latest cycle linked no evidence into an incident." />
        )
      )}
    </div>
  )
}
