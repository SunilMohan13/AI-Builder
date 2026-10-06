import { useEffect, useState } from 'react'
import { Play, Sparkles, Square } from 'lucide-react'
import { ScientificBadge } from '../common/Badge'
import { explainEvent } from '../../services/copilotService'
import { KM_PER_DEG_LAT } from '../../utils/geo'
import { cn } from '../../utils/cn'
import type { CopilotMessage } from '../../types'

export type DetectScenario = 'now' | 'windShift' | 'contain' | 'grap'

export const DETECT_SCENARIOS: { id: DetectScenario; label: string }[] = [
  { id: 'now', label: 'Now' },
  { id: 'windShift', label: 'Wind +28°' },
  { id: 'contain', label: 'Contain fires' },
  { id: 'grap', label: 'GRAP NCR' },
]

interface NamedPoint {
  name: string
  lat: number
  lon: number
}

/** Rotate a point around origin by degrees (east-north plane). PREDICTED geometry only. */
export function rotateAround(
  origin: { lat: number; lon: number },
  point: { lat: number; lon: number },
  deg: number,
): { lat: number; lon: number } {
  const theta = (deg * Math.PI) / 180
  const lonScale = KM_PER_DEG_LAT * Math.cos((origin.lat * Math.PI) / 180)
  const east = (point.lon - origin.lon) * lonScale
  const north = (point.lat - origin.lat) * KM_PER_DEG_LAT
  const eastR = east * Math.cos(theta) - north * Math.sin(theta)
  const northR = east * Math.sin(theta) + north * Math.cos(theta)
  return {
    lat: origin.lat + northR / KM_PER_DEG_LAT,
    lon: origin.lon + eastR / lonScale,
  }
}

export function applyDetectScenario(
  origin: { lat: number; lon: number },
  dest: NamedPoint,
  scenario: DetectScenario,
): NamedPoint {
  if (scenario === 'windShift') {
    const rotated = rotateAround(origin, dest, 28)
    return { name: 'Shifted intercept', lat: rotated.lat, lon: rotated.lon }
  }
  if (scenario === 'contain') {
    return {
      name: 'Contained front',
      lat: origin.lat + (dest.lat - origin.lat) * 0.42,
      lon: origin.lon + (dest.lon - origin.lon) * 0.42,
    }
  }
  return dest
}

export const DETECT_HORIZONS = [0, 3, 6, 12] as const
export type DetectHorizon = (typeof DETECT_HORIZONS)[number]

export function applyHorizon(
  origin: { lat: number; lon: number },
  dest: NamedPoint,
  hours: DetectHorizon,
): NamedPoint {
  const t = Math.max(0.08, Math.min(hours / 12, 1))
  return {
    name: hours >= 12 ? dest.name : hours === 0 ? 'Near-source puff' : `Plume front +${hours}h`,
    lat: origin.lat + (dest.lat - origin.lat) * t,
    lon: origin.lon + (dest.lon - origin.lon) * t,
  }
}

export function horizonRibbonScale(hours: DetectHorizon): number {
  return 0.55 + (hours / 12) * 0.7
}

export function scenarioRibbonKm(scenario: DetectScenario): number {
  if (scenario === 'contain') return 9
  if (scenario === 'windShift') return 14
  return 16
}

export function scenarioCaption(
  scenario: DetectScenario,
  towardNcr: boolean,
  hours: DetectHorizon = 12,
): string {
  if (scenario === 'windShift') return `Predicted · wind-shift · +${hours}h`
  if (scenario === 'contain') return `Predicted · contained · +${hours}h`
  if (scenario === 'grap') return 'Recommended · GRAP Stage III NCR'
  if (hours === 0) return 'Predicted · near-source puff'
  if (towardNcr) return `Predicted · +${hours}h toward Delhi NCR`
  return `Predicted · +${hours}h downwind`
}

export function scenarioNote(scenario: DetectScenario): string {
  if (scenario === 'windShift') {
    return 'What-if: transport bearing +28°. Geometry only — not a new model run.'
  }
  if (scenario === 'contain') {
    return 'What-if: source intensity cut. Plume does not claim the fires are extinguished.'
  }
  if (scenario === 'grap') {
    return 'Recommended operational overlay for NCR. Not an issued government order.'
  }
  return 'Baseline predicted advection. Timeline is a forecast, not observed smoke.'
}

export function DetectDecisionLab({
  scenario,
  onScenario,
  horizon,
  onHorizon,
  eventId,
  className,
}: {
  scenario: DetectScenario
  onScenario: (next: DetectScenario) => void
  horizon: DetectHorizon
  onHorizon: (hours: DetectHorizon) => void
  /** The event this panel is describing. Explain is scoped to it. */
  eventId: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [answer, setAnswer] = useState<CopilotMessage | null>(null)
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    if (!playing) return
    const seq: DetectHorizon[] = [0, 3, 6, 12]
    let i = 0
    onHorizon(0)
    const id = window.setInterval(() => {
      i += 1
      if (i >= seq.length) {
        setPlaying(false)
        return
      }
      onHorizon(seq[i] ?? 12)
    }, 1400)
    return () => window.clearInterval(id)
    // Replay from Now each time Play is pressed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing])

  const explain = async () => {
    setOpen(true)
    if (answer || loading) return
    setLoading(true)
    try {
      // Scoped to the open event. This used to send a fixed question to
      // /copilot/query, which described whichever event the backend
      // happened to return first.
      const response = await explainEvent(eventId)
      setAnswer(response)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={cn('pointer-events-auto flex max-w-xl flex-col gap-2', className)}>
      <div className="rounded-lg border border-cyan-500/20 bg-bg-panel/90 p-2.5 backdrop-blur">
        <div className="flex items-center justify-between gap-2 px-1">
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-amber-200/80">
            Predicted horizon
          </p>
          <button
            type="button"
            onClick={() => setPlaying((v) => !v)}
            className="inline-flex items-center gap-1 rounded border border-intel/30 bg-intel/10 px-2 py-0.5 text-[11px] text-intel hover:bg-intel/20"
          >
            {playing ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {playing ? 'Stop' : 'Play 12h'}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {DETECT_HORIZONS.map((hours) => (
            <button
              key={hours}
              type="button"
              onClick={() => {
                setPlaying(false)
                onHorizon(hours)
              }}
              aria-pressed={horizon === hours}
              className={cn(
                'rounded px-2.5 py-1 text-[11px] transition-colors',
                horizon === hours
                  ? 'bg-amber-400/20 text-amber-100'
                  : 'text-text-muted hover:text-text-secondary',
              )}
            >
              {hours === 0 ? 'Now' : `+${hours}h`}
            </button>
          ))}
        </div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-amber-400/80 transition-[width] duration-500"
            style={{ width: `${(horizon / 12) * 100}%` }}
          />
        </div>
        <p className="mt-2 px-1 font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
          What-if
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {DETECT_SCENARIOS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onScenario(item.id)}
              aria-pressed={scenario === item.id}
              className={cn(
                'rounded px-2 py-1 text-[11px] transition-colors',
                scenario === item.id
                  ? 'bg-intel/20 text-intel'
                  : 'text-text-muted hover:text-text-secondary',
              )}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void explain()}
            className="inline-flex items-center gap-1 rounded border border-intel/30 bg-intel/10 px-2 py-1 text-[11px] text-intel hover:bg-intel/20"
          >
            <Sparkles className="h-3 w-3" />
            Explain
          </button>
        </div>
        <p className="mt-1.5 px-1 text-[10px] leading-snug text-text-muted">{scenarioNote(scenario)}</p>
      </div>

      {open ? (
        <div className="max-h-48 overflow-auto rounded-lg border border-intel/25 bg-bg-panel/95 p-3 backdrop-blur">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <ScientificBadge label="PREDICTED" />
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-text-muted">
                ML numbers · Copilot explains
              </span>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-[11px] text-text-muted hover:text-text-secondary"
            >
              Close
            </button>
          </div>
          {loading ? (
            <p className="text-xs text-text-muted">Retrieving evidence…</p>
          ) : (
            <p className="whitespace-pre-line text-xs text-text-secondary">{answer?.content}</p>
          )}
          {answer?.citations ? (
            <div className="mt-2 flex flex-wrap gap-2 border-t border-border pt-2">
              {answer.citations.map((c) => (
                <span key={c.source} className="font-mono text-[10px] text-intel">
                  {c.source} · {c.time}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
