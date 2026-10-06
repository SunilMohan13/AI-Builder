import { Link, useNavigate } from 'react-router-dom'
import { X, Bot } from 'lucide-react'
import type { GridCell, FireObservation } from '../../types'
import { ScientificBadge } from '../common/Badge'
import { formatNumber, formatTimeIST } from '../../utils/format'
import { getBandLabel } from '../../utils/aqi'
import { distanceKm } from '../../utils/geo'
import { toRegion } from '../../api/adapters'
import { useHeroEventId } from '../../hooks/useHeroEventId'
import { heroEventPath } from '../../utils/heroEvent'
import { copilotQuestionForCell, evidenceForCell } from './mapCellEvidence'
import { useApp } from '../../context/AppContext'
import { useDataMode } from '../../context/DataModeContext'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-text-secondary">{label}</span>
      <span className="font-mono font-medium">{value}</span>
    </div>
  )
}

export function MapPopup({
  cell,
  fire,
  fires = [],
  hourOffset = 0,
  onClose,
}: {
  cell: GridCell | null
  fire: FireObservation | null
  fires?: FireObservation[]
  hourOffset?: number
  onClose: () => void
}) {
  const navigate = useNavigate()
  const { setPendingCopilotQuestion } = useApp()
  const { mode } = useDataMode()
  const isDemo = mode === 'demo'
  const heroEventId = useHeroEventId()
  const nearbyFires = fire
    ? fires.filter((f) => f.id !== fire.id && distanceKm(fire.lat, fire.lon, f.lat, f.lon) < 25)
        .length
    : 0

  const cellEvidence = cell ? evidenceForCell(cell, hourOffset, { demo: isDemo }) : []

  const askCopilot = () => {
    if (!cell) return
    setPendingCopilotQuestion(copilotQuestionForCell(cell))
    navigate('/copilot')
    onClose()
  }

  return (
    <div className="absolute right-4 top-4 z-20 w-72 rounded-lg border border-cyan-500/25 bg-bg-panel/95 p-4 shadow-xl backdrop-blur">
      <div className="mb-3 flex items-start justify-between">
        <h3 className="font-semibold">{fire ? 'Fire Detected' : 'Grid intelligence'}</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="rounded text-text-muted hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-intel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {fire && (
        <div className="space-y-2 text-sm">
          <ScientificBadge label="OBSERVED" />
          <p className="text-xs text-text-muted">
            {toRegion(fire.lat, fire.lon)} · {formatTimeIST(fire.timestamp)} IST
          </p>
          <Row label="Fire Radiative Power" value={`${fire.frp.toFixed(0)} MW`} />
          <Row label="Confidence" value={`${Math.round(fire.confidence * 100)}%`} />
          <Row label="Nearby fires" value={String(nearbyFires)} />
          {/* "HIGH" was a constant, not a computed impact. Only the demo
              episode is scripted to justify it. */}
          {isDemo && (
            <div className="flex justify-between gap-4">
              <span className="text-text-secondary">Estimated impact</span>
              <span className="font-medium text-pollution-severe">HIGH</span>
            </div>
          )}
          <Link
            to={heroEventPath(heroEventId)}
            className="mt-3 block w-full rounded-md bg-intel/20 py-2 text-center text-xs font-medium text-intel hover:bg-intel/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-intel"
          >
            Investigate event
          </Link>
        </div>
      )}

      {cell && (
        <div className="space-y-3 text-sm">
          <ScientificBadge label="OBSERVED" />
          <Row label="PM2.5" value={`${cell.pm25} µg/m³`} />
          <Row label="AQI" value={`${cell.aqi} · ${getBandLabel(cell.pm25)}`} />
          <Row label="Population" value={formatNumber(cell.population)} />
          <div className="flex justify-between gap-4">
            <span className="text-text-secondary">Risk</span>
            <span className="font-medium">{cell.risk}</span>
          </div>

          <div className="rounded-md border border-border/70 bg-black/20 p-2">
            <p className="text-[10px] uppercase tracking-wider text-text-muted">Fused evidence</p>
            <ul className="mt-1.5 space-y-1.5">
              {cellEvidence.slice(0, 4).map((line) => (
                <li key={line.source} className="text-[11px] leading-snug">
                  <span className="text-cyan-300/90">{line.source}</span>
                  <span className="text-text-muted"> · {line.label}</span>
                  <p className="text-text-secondary">{line.text}</p>
                </li>
              ))}
            </ul>
          </div>

          <p className="text-[10px] text-text-muted">
            Sensitive groups: limit prolonged outdoor exertion when band is Poor or worse.
          </p>

          <button
            type="button"
            onClick={askCopilot}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-intel/20 py-2 text-xs font-medium text-intel hover:bg-intel/30"
          >
            <Bot size={14} />
            Explain this cell (Copilot)
          </button>
        </div>
      )}
    </div>
  )
}
