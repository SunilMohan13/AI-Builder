import { useMemo } from 'react'
import type { GraphNode, Incident, ProvenanceClass } from '../../api/regionTypes'
import { NODE_KIND_LABELS, nodeRef } from '../../utils/incident'

const NODE_COLOURS: Record<string, string> = {
  incident: '#22d3ee',
  anomaly: '#f59e0b',
  cell: '#64748b',
  station: '#34d399',
  plume: '#a78bfa',
  pollution_event: '#f87171',
  wind_run: '#e2e8f0',
  fire_cluster: '#f97316',
  citizen_report: '#d946ef',
  satellite_signal: '#38bdf8',
}

const EDGE_COLOURS: Record<ProvenanceClass, string> = {
  measured: '#34d399',
  model_derived: '#38bdf8',
  predicted: '#22d3ee',
  simulated: '#a78bfa',
  heuristic: '#f59e0b',
  ai_observation: '#d946ef',
  citizen: '#94a3b8',
}

/**
 * The incident's nodes on a ring around the incident, edges coloured by their
 * provenance class. Layout is deterministic: same graph, same picture.
 */
export function IncidentGraph({
  incident,
  selectedId,
  onSelect,
  size = 320,
}: {
  incident: Incident
  selectedId?: string | null
  onSelect?: (node: GraphNode) => void
  size?: number
}) {
  const positions = useMemo(() => {
    const centre = size / 2
    const radius = size * 0.36
    const others = incident.nodes
      .filter((n) => n.kind !== 'incident')
      .sort((a, b) => a.kind.localeCompare(b.kind) || a.node_id.localeCompare(b.node_id))
    const at = new Map<string, [number, number]>()
    for (const n of incident.nodes) if (n.kind === 'incident') at.set(n.node_id, [centre, centre])
    others.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(1, others.length) - Math.PI / 2
      at.set(n.node_id, [centre + radius * Math.cos(angle), centre + radius * Math.sin(angle)])
    })
    return at
  }, [incident.nodes, size])

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full" role="img" aria-label="Incident graph">
      {incident.edges.map((e) => {
        const a = positions.get(e.src)
        const b = positions.get(e.dst)
        if (!a || !b) return null
        const active = selectedId != null && (e.src === selectedId || e.dst === selectedId)
        return (
          <line
            key={e.edge_id}
            x1={a[0]}
            y1={a[1]}
            x2={b[0]}
            y2={b[1]}
            stroke={EDGE_COLOURS[e.provenance_class] ?? '#475569'}
            strokeOpacity={active ? 0.95 : 0.4}
            strokeWidth={active ? 2.5 : 1.2}
          >
            <title>
              {e.kind} ({e.provenance_class}) · {e.producer}
            </title>
          </line>
        )
      })}
      {incident.nodes.map((n) => {
        const p = positions.get(n.node_id)
        if (!p) return null
        const selected = n.node_id === selectedId
        const r = n.kind === 'incident' ? 14 : 9
        return (
          <g
            key={n.node_id}
            transform={`translate(${p[0]}, ${p[1]})`}
            className={onSelect ? 'cursor-pointer' : undefined}
            onClick={() => onSelect?.(n)}
            role={onSelect ? 'button' : undefined}
            tabIndex={onSelect ? 0 : undefined}
            onKeyDown={(ev) => {
              if (onSelect && (ev.key === 'Enter' || ev.key === ' ')) {
                ev.preventDefault()
                onSelect(n)
              }
            }}
          >
            <circle
              r={r}
              fill={NODE_COLOURS[n.kind] ?? '#94a3b8'}
              fillOpacity={0.85}
              stroke={selected ? '#f8fafc' : '#0f172a'}
              strokeWidth={selected ? 2.5 : 1.5}
            />
            <text y={r + 11} textAnchor="middle" fontSize={9} fill="#cbd5e1" className="select-none">
              {NODE_KIND_LABELS[n.kind] ?? n.kind}
            </text>
            <title>{`${n.kind} · ${nodeRef(n.node_id)}`}</title>
          </g>
        )
      })}
    </svg>
  )
}

export function EdgeLegend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-text-muted">
      {(Object.keys(EDGE_COLOURS) as ProvenanceClass[]).map((k) => (
        <span key={k} className="flex items-center gap-1">
          <span className="h-0.5 w-3" style={{ background: EDGE_COLOURS[k] }} aria-hidden />
          {k.replace('_', ' ')}
        </span>
      ))}
    </div>
  )
}
