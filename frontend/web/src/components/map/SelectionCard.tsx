import { X } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { AqiStandard } from '../../api/regionTypes'
import { useRegionClock } from '../../hooks/useRegionClock'
import { useRegionLink } from '../../hooks/useRegionLink'
import { formatDateTime, humanise } from '../../utils/format'
import { Missing, reasonFor, Value } from '../common/Missing'
import { ProvenanceBadge } from '../common/ProvenanceBadge'
import type { MapSelection } from './RegionMap'

/** What was clicked on the map, with every value's provenance and any missing field's reason. */
export function SelectionCard({
  selection,
  standard,
  onClose,
}: {
  selection: MapSelection
  standard: AqiStandard | null
  onClose: () => void
}) {
  const { timeZone } = useRegionClock()
  const link = useRegionLink()

  let title = ''
  let body: React.ReactNode = null
  if (selection.kind === 'cell') {
    const c = selection.cell
    title = `Cell ${c.grid_id}`
    body = (
      <>
        <p>
          PM2.5 (hourly):{' '}
          <Value value={c.pm25} unit="µg/m³" reason={reasonFor(c.field_status, 'pm25')} />
        </p>
        <p className="flex flex-wrap items-center gap-1.5">
          <ProvenanceBadge value={c.provenance_class} />
          <span className="text-text-muted">
            {c.pm25_source_id ?? '—'} · {formatDateTime(c.observed_at, timeZone)}
          </span>
        </p>
        <p>
          {standard?.name ?? 'AQI'} band:{' '}
          {c.aqi_band ? c.aqi_band.label : <Missing reason={reasonFor(c.field_status, 'aqi_band')} />}
        </p>
      </>
    )
  } else if (selection.kind === 'fire') {
    const f = selection.fire
    title = 'Fire cluster'
    body = (
      <>
        <p>
          FRP: <Value value={f.frp} unit="MW" reason="FIRMS sent no fire radiative power" /> ·{' '}
          {f.detection_count} detection(s)
        </p>
        <p className="flex flex-wrap items-center gap-1.5">
          <ProvenanceBadge value={f.provenance_class} />
          <span className="text-text-muted">
            {f.source_id} · seen {formatDateTime(f.observed_at, timeZone)}
          </span>
        </p>
        <p className="text-[10px] text-text-muted">
          A satellite overpass detection; no detection is not proof of no fire.
        </p>
      </>
    )
  } else if (selection.kind === 'report') {
    const r = selection.report
    title = 'Citizen report'
    body = (
      <>
        <p className="flex flex-wrap items-center gap-1.5">
          Visual class: {r.visual_class ?? <Missing reason={`status ${r.status}`} />}
          <ProvenanceBadge value={r.visual_class_provenance} />
        </p>
        <p>
          Corroboration: {r.corroboration ?? '—'} · location trust: {r.geo_trust ?? '—'}
        </p>
        <p className="text-text-muted">Moderation: {r.moderation ?? '—'}</p>
        <Link to={link('/citizen', { report: r.report_id })} className="text-intel hover:underline">
          Open report →
        </Link>
      </>
    )
  } else {
    const p = selection.plume
    title = p.direction === 'forward' ? 'Forward plume' : 'Back trajectory'
    body = (
      <>
        <p className="flex flex-wrap items-center gap-1.5">
          <ProvenanceBadge value={p.provenance_class} /> {p.label}
        </p>
        <p className="text-text-muted">
          {p.model_version} · origin {humanise(p.origin.kind)} {p.origin.ref_id ?? ''}
        </p>
        {p.degraded && (
          <p className="text-amber-300/90">Degraded: {p.degraded_reasons.map(humanise).join('; ')}</p>
        )}
      </>
    )
  }

  return (
    <div className="w-72 space-y-1 rounded-lg border border-border bg-bg-panel/95 p-3 text-xs backdrop-blur">
      <div className="flex items-start justify-between gap-2">
        <p className="break-all font-medium text-text-primary">{title}</p>
        <button type="button" onClick={onClose} aria-label="Close">
          <X className="h-3.5 w-3.5 text-text-muted" />
        </button>
      </div>
      {body}
    </div>
  )
}
