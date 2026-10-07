import { cellToLatLng } from 'h3-js'
import type { GraphNode, GraphValue, Incident } from '../api/regionTypes'

/** Node ids are `kind:region:ref`; the reference is everything after the kind and region. */
export function nodeRef(nodeId: string): string {
  return nodeId.split(':').at(-1) ?? nodeId
}

const H3_R8 = /\b88[0-9a-f]{13}\b/g

export function incidentPlumeIds(incident: Incident): Set<string> {
  return new Set(incident.nodes.filter((n) => n.kind === 'plume').map((n) => nodeRef(n.node_id)))
}

export function incidentEventIds(incident: Incident): string[] {
  return incident.nodes.filter((n) => n.kind === 'pollution_event').map((n) => nodeRef(n.node_id))
}

/** 1 km cells named by the incident's anomaly, station and event nodes. */
export function incidentCells(incident: Incident): Set<string> {
  const cells = new Set<string>()
  for (const node of incident.nodes) for (const match of node.node_id.matchAll(H3_R8)) cells.add(match[0])
  return cells
}

/** Mean centre of the incident's 1 km cells as `[lon, lat]`, or null when it names none. */
export function incidentFocus(incident: Incident): [number, number] | null {
  const points = [...incidentCells(incident)].map((cell) => cellToLatLng(cell))
  if (points.length === 0) return null
  const lat = points.reduce((s, [la]) => s + la, 0) / points.length
  const lon = points.reduce((s, [, lo]) => s + lo, 0) / points.length
  return [lon, lat]
}

function isGraphValue(v: unknown): v is GraphValue {
  return typeof v === 'object' && v !== null && 'value' in v && 'provenance_class' in v
}

/** The node's typed values (value, unit, provenance), in attribute order. */
export function nodeValues(node: GraphNode): { key: string; value: GraphValue }[] {
  return Object.entries(node.attributes)
    .filter((entry): entry is [string, GraphValue] => isGraphValue(entry[1]))
    .map(([key, value]) => ({ key, value }))
}

/** Plain (untyped) attributes such as `severity` or `direction`. */
export function nodeFacts(node: GraphNode): { key: string; value: string }[] {
  return Object.entries(node.attributes)
    .filter(([, v]) => !isGraphValue(v) && v !== null && typeof v !== 'object')
    .map(([key, v]) => ({ key, value: String(v) }))
}

export const NODE_KIND_LABELS: Record<string, string> = {
  incident: 'Incident',
  anomaly: 'Anomaly',
  cell: 'Cell',
  station: 'Station',
  plume: 'Plume',
  pollution_event: 'Event',
  wind_run: 'Wind run',
  fire_cluster: 'Fire cluster',
  citizen_report: 'Citizen report',
  satellite_signal: 'Satellite signal',
  place: 'Place',
}

export function nodeTitle(node: GraphNode): string {
  return `${NODE_KIND_LABELS[node.kind] ?? node.kind} · ${nodeRef(node.node_id)}`
}

/** Nodes in the order they became valid, the incident itself first. */
export function timeline(incident: Incident): GraphNode[] {
  return [...incident.nodes].sort((a, b) => {
    if (a.kind === 'incident') return -1
    if (b.kind === 'incident') return 1
    return a.valid_from < b.valid_from ? -1 : a.valid_from > b.valid_from ? 1 : a.kind.localeCompare(b.kind)
  })
}
