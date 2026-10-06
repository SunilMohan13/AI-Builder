import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ShieldAlert, TrendingUp } from 'lucide-react'
import { Card, CardBody, CardHeader } from '../common/Card'
import { ScientificBadge, StatusBadge } from '../common/Badge'
import { CalibrationNote, ProvenanceBadge } from '../common/Provenance'
import { fetchHazard, fetchPeakForecast, HAZARD_THRESHOLD } from '../../services/hazardService'
import { useDataMode } from '../../context/DataModeContext'
import { useViewLevel } from '../../context/ViewLevelContext'
import { cn } from '../../utils/cn'

/**
 * 24-hour hazard and peak outlook.
 *
 * Surfaces `hazard.v1` and `peak_forecast.v1`. Both currently answer from a
 * deterministic persistence rule because their trained models are withheld
 * by the promotion gate, and this component says so on the face of it
 * rather than in a tooltip: a hazard number that looks like a model output
 * when it is a persistence ramp is the mislabelling that matters most here.
 */
export function HazardOutlook({ className }: { className?: string }) {
  const { mode } = useDataMode()
  const { advanced } = useViewLevel()
  const { data: hazard } = useQuery({ queryKey: ['hazard', mode], queryFn: fetchHazard })
  const { data: peak } = useQuery({ queryKey: ['peak', mode], queryFn: fetchPeakForecast })

  const hazardCells = hazard?.cells ?? []
  const peakCells = peak?.cells ?? []
  const atRisk = hazardCells.filter((c) => c.hazardScore >= 0.5).length
  const exceeding = peakCells.filter((c) => c.exceedsThreshold).length
  const topPeak = peakCells[0]
  const degraded = hazard?.provenance?.degraded ?? true
  const calibrated = hazardCells[0]?.calibrated ?? false
  const hazardByCell = new Map(hazardCells.map((c) => [c.gridId, c.hazardScore]))

  return (
    <Card className={className}>
      <CardHeader className="flex flex-wrap items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-medium">24-Hour Hazard Outlook</span>
        <ScientificBadge label="PREDICTED" />
        <ProvenanceBadge
          provenance={{
            mode,
            degraded,
            modelVersion: hazard?.provenance?.model_version,
            note: hazard?.provenance?.reason,
          }}
        />
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <Tile
            label={advanced ? 'Cells at hazard' : 'Areas at hazard'}
            value={atRisk}
            sublabel={`of ${hazardCells.length} scored`}
            tone={atRisk > 0 ? 'warn' : 'calm'}
          />
          <Tile
            label={`Peak > ${HAZARD_THRESHOLD}`}
            value={exceeding}
            sublabel={advanced ? 'cells in 24 h' : 'areas in 24 h'}
            tone={exceeding > 0 ? 'warn' : 'calm'}
          />
          {/* Scoped explicitly: the Forecast card above reports the Delhi NCR
              trajectory peak, and an unqualified "highest peak" next to it
              reads as the same quantity disagreeing with itself. */}
          <Tile
            label="Worst single area"
            value={topPeak ? Math.round(topPeak.peakPm25) : '—'}
            sublabel="µg/m³ projected · any area"
            tone={topPeak && topPeak.exceedsThreshold ? 'warn' : 'calm'}
          />
        </div>

        {advanced && peakCells.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-text-secondary">
              Worst projected cells, next 24 h
            </p>
            {/* Ranked by projected peak rather than hazard score: the score
                saturates at 1.00 for every cell already above the threshold,
                so ranking by it would list five identical rows. */}
            {peakCells.slice(0, 5).map((cell) => {
              const score = hazardByCell.get(cell.gridId) ?? 0
              return (
                <div
                  key={cell.gridId}
                  className="flex items-center justify-between rounded border border-border px-3 py-1.5"
                >
                  <span className="font-mono text-xs text-text-muted">
                    {cell.gridId.slice(0, 10)}…
                  </span>
                  <div className="flex items-center gap-3">
                    {cell.observedPm25 !== null && (
                      <span
                        className="font-mono text-xs text-text-muted"
                        title="Observed now"
                      >
                        {Math.round(cell.observedPm25)}
                      </span>
                    )}
                    <span
                      className={cn(
                        'font-mono text-xs font-semibold',
                        cell.exceedsThreshold ? 'text-red-400' : 'text-text-secondary',
                      )}
                      title="Projected 24 h peak"
                    >
                      → {Math.round(cell.peakPm25)} µg/m³
                    </span>
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          score >= 0.66
                            ? 'bg-red-500'
                            : score >= 0.33
                              ? 'bg-amber-400'
                              : 'bg-emerald-500',
                        )}
                        style={{ width: `${Math.round(score * 100)}%` }}
                      />
                    </div>
                    <span className="w-9 text-right font-mono text-xs">{score.toFixed(2)}</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {!advanced && (
          <p className="text-xs text-text-secondary">
            An area counts as at hazard when its projected 24-hour peak crosses{' '}
            {HAZARD_THRESHOLD} µg/m³, the CPCB &ldquo;Very Poor&rdquo; breakpoint.
            {degraded ? ' This outlook comes from a persistence rule, not a trained model.' : ''}
          </p>
        )}

        {advanced && (
        <div className="space-y-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-amber-200">
            <AlertTriangle className="h-3.5 w-3.5" />
            How to read these numbers
          </p>
          <ul className="space-y-1 text-[11px] text-amber-200/80">
            <li>
              The score is a <strong>ranking</strong>, not a probability.{' '}
              <CalibrationNote calibrated={calibrated} /> — 0.80 does not mean an 80% chance. It
              saturates at 1.00 once a cell is already above the threshold, which is why cells are
              ranked by projected peak instead.
            </li>
            <li>
              Threshold is <strong>{HAZARD_THRESHOLD} µg/m³</strong>, the CPCB &ldquo;Very
              Poor&rdquo; breakpoint. One threshold, so two hazard figures can never disagree.
            </li>
            {degraded && (
              <li>
                {hazard?.provenance?.reason ??
                  'Served by a deterministic persistence rule; no hazard model is promoted.'}
              </li>
            )}
          </ul>
        </div>
        )}
      </CardBody>
    </Card>
  )
}

function Tile({
  label,
  value,
  sublabel,
  tone,
}: {
  label: string
  value: number | string
  sublabel: string
  tone: 'warn' | 'calm'
}) {
  return (
    <div className="rounded border border-border p-3">
      <p className="text-[10px] uppercase tracking-wider text-text-muted">{label}</p>
      <p
        className={cn(
          'font-mono text-2xl font-bold',
          tone === 'warn' ? 'text-amber-300' : 'text-text-primary',
        )}
      >
        {value}
      </p>
      <p className="text-[10px] text-text-muted">{sublabel}</p>
    </div>
  )
}

/** Compact hazard KPI for the Overview. */
export function HazardKpi() {
  const { mode } = useDataMode()
  const { data: hazard } = useQuery({ queryKey: ['hazard', mode], queryFn: fetchHazard })
  const cells = hazard?.cells ?? []
  const atRisk = cells.filter((c) => c.hazardScore >= 0.5).length

  return (
    <div>
      <div className="flex items-center gap-1.5">
        <p className="text-xs text-text-muted">24h Hazard</p>
        <TrendingUp className="h-3 w-3 text-amber-400" />
      </div>
      <p className="font-mono text-3xl font-bold">{atRisk}</p>
      <div className="flex items-center gap-1.5">
        <p className="text-[10px] text-text-muted">cells at risk</p>
        <StatusBadge variant="warning">
          {hazard?.provenance?.degraded === false ? 'model' : 'baseline'}
        </StatusBadge>
      </div>
    </div>
  )
}
