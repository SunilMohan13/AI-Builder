import { Link } from 'react-router-dom'
import { AlertTriangle, Users, Wind } from 'lucide-react'
import type { PollutionEvent } from '../../types'
import { ScientificBadge, StatusBadge } from '../common/Badge'
import { formatPopulation } from '../../utils/format'
import { useDataMode } from '../../context/DataModeContext'

interface ActionBriefProps {
  event: PollutionEvent
}

const briefActions = [
  {
    id: 'health',
    label: 'Public health advisory',
    detail: 'Issue NCR advisory within 6h · schools consider outdoor restrictions',
    kind: 'RECOMMENDED' as const,
    confidence: 91,
  },
  {
    id: 'verify',
    label: 'Ground verification',
    detail: 'Deploy teams to Punjab stubble corridor · corroborate FIRMS clusters',
    kind: 'RECOMMENDED' as const,
    confidence: 88,
  },
  {
    id: 'transport',
    label: 'Cross-state coordination',
    detail: 'NH-44 monitoring · shared plume bulletin with Haryana & Delhi GRAP desk',
    kind: 'RECOMMENDED' as const,
    confidence: 85,
  },
]

export function ActionBrief({ event }: ActionBriefProps) {
  const { mode } = useDataMode()
  const scriptedHero = mode === 'demo' && event.provenance?.mode !== 'live'

  return (
    <div
      className="rounded-lg border border-cyan-500/25 bg-gradient-to-br from-bg-panel via-bg-panel to-cyan-950/20 p-4 shadow-[0_0_32px_rgba(34,211,238,0.06)]"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-cyan-300/90">
            Operator action brief
          </p>
          <h2 className="mt-1 text-lg font-semibold">{event.title}</h2>
          <p className="text-sm text-text-secondary">{event.region}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge variant={event.severity === 'SEVERE' ? 'severe' : 'warning'}>
            {event.severity}
          </StatusBadge>
          <ScientificBadge label="RECOMMENDED" />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="flex items-start gap-2 rounded-md border border-border/80 bg-black/20 p-3">
          <Users className="mt-0.5 h-4 w-4 shrink-0 text-orange-400" />
          <div>
            <p className="text-[10px] uppercase tracking-wider text-text-muted">Exposure</p>
            <p className="font-mono text-lg font-semibold">
              {event.provenance?.unavailable?.includes('populationAtRisk')
                ? '\u2014'
                : formatPopulation(event.populationAtRisk)}
            </p>
            <p className="text-xs text-text-muted">
              {event.provenance?.unavailable?.includes('populationAtRisk')
                ? 'headcount not exposed by the API'
                : 'in projected plume path'}
            </p>
          </div>
        </div>
        <div className="flex items-start gap-2 rounded-md border border-border/80 bg-black/20 p-3">
          <Wind className="mt-0.5 h-4 w-4 shrink-0 text-intel" />
          <div>
            <p className="text-[10px] uppercase tracking-wider text-text-muted">Transport</p>
            {/* Demo-only: these are scripted figures for the Punjab episode.
                Rendering them in Live put an invented wind speed and a
                fabricated "89% forecast conf." under a Live header. */}
            {scriptedHero ? (
              <>
                <p className="text-sm font-medium">NW → SE · ~14–22 km/h</p>
                <p className="text-xs text-text-muted">IMD alignment · INFERRED</p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-text-muted">&mdash;</p>
                <p className="text-xs text-text-muted">
                  Transport summary is not on the event contract. Ask Copilot for wind.
                </p>
              </>
            )}
          </div>
        </div>
        <div className="flex items-start gap-2 rounded-md border border-border/80 bg-black/20 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <div>
            <p className="text-[10px] uppercase tracking-wider text-text-muted">Peak window</p>
            {scriptedHero ? (
              <>
                <p className="text-sm font-medium">+3 to +6 hours</p>
                <p className="text-xs text-text-muted">PREDICTED · 89% forecast conf.</p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-text-muted">&mdash;</p>
                <p className="text-xs text-text-muted">
                  No peak window on this event. The forecast chart shows the horizon.
                </p>
              </>
            )}
          </div>
        </div>
      </div>

      {scriptedHero || event.recommendedActions.length > 0 ? (
        <ul className="mt-4 space-y-2">
          {(scriptedHero
            ? briefActions
            : event.recommendedActions.map((a, i) => ({
                id: `ra-${i}`,
                label: a.length > 48 ? `${a.slice(0, 45)}…` : a,
                detail: a,
                kind: 'RECOMMENDED' as const,
                confidence: 80,
              }))
          ).map((item) => (
            <li
              key={item.id}
              className="flex flex-wrap items-baseline justify-between gap-2 rounded-md border border-border/60 px-3 py-2 text-sm"
            >
              <div>
                <span className="font-medium text-text-primary">{item.label}</span>
                <p className="text-xs text-text-muted">{item.detail}</p>
              </div>
              <span className="font-mono text-[10px] text-cyan-300/80">
                {item.kind} · {item.confidence}%
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Live events do not carry an authored action list. Ask Copilot to retrieve the
          evidence-grounded recommendations for this id.
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          to="/forecast"
          className="rounded-md bg-intel/20 px-3 py-1.5 text-xs font-medium text-intel hover:bg-intel/30"
        >
          Open forecast
        </Link>
        <Link
          to={scriptedHero ? '/citizen?highlight=cr_5' : '/citizen'}
          className="rounded-md border border-border px-3 py-1.5 text-xs text-text-secondary hover:text-intel"
        >
          Citizen corroboration
        </Link>
        <Link
          to="/copilot"
          className="rounded-md border border-border px-3 py-1.5 text-xs text-text-secondary hover:text-intel"
        >
          Ask Copilot
        </Link>
      </div>
    </div>
  )
}
