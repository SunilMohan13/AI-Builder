import { AlertTriangle, Database, FlaskConical, Radio } from 'lucide-react'
import { useDataMode } from '../../context/DataModeContext'
import { useViewLevel } from '../../context/ViewLevelContext'
import type { DataProvenance } from '../../types'
import { cn } from '../../utils/cn'

/**
 * Provenance surfacing.
 *
 * The integration plan singles this out: "a hazard probability shown without
 * its confidence, or a baseline fallback shown as a model prediction, is the
 * failure mode that matters most in a public air-quality tool." These
 * components exist so that never requires a per-screen decision.
 */

/** Small inline marker: where this number came from. */
export function ProvenanceBadge({
  provenance,
  className,
}: {
  provenance?: DataProvenance
  className?: string
}) {
  const { mode } = useDataMode()
  const effective = provenance?.mode ?? mode

  if (effective === 'demo') {
    return (
      <span
        title="Scripted demo narrative — not a live measurement or model output."
        className={cn(
          'inline-flex items-center gap-1 rounded border border-intel/30 bg-intel/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-intel',
          className,
        )}
      >
        <Database className="h-2.5 w-2.5" />
        Demo
      </span>
    )
  }

  if (provenance?.degraded) {
    return (
      <span
        title={
          provenance.note ??
          `Deterministic fallback (${provenance.modelVersion ?? 'baseline'}) — no trained model is promoted for this.`
        }
        className={cn(
          'inline-flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-300',
          className,
        )}
      >
        <AlertTriangle className="h-2.5 w-2.5" />
        Baseline
      </span>
    )
  }

  return (
    <span
      title={provenance?.modelVersion ?? 'Live from the AeroPulse API'}
      className={cn(
        'inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-300',
        className,
      )}
    >
      <Radio className="h-2.5 w-2.5" />
      Live
    </span>
  )
}

/**
 * Marks a score that ranks correctly but is not a probability.
 *
 * An uncalibrated gradient-boosting score of 0.8 does not mean "80% chance".
 * Rendering it as a percentage without this would be the most consequential
 * mislabelling the app can produce.
 */
export function CalibrationNote({ calibrated }: { calibrated: boolean }) {
  if (calibrated) return null
  return (
    <span
      title="Uncalibrated score. It orders cells correctly, but its magnitude is not a probability and must not be read as a percentage."
      className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-amber-400/80"
    >
      <FlaskConical className="h-2.5 w-2.5" />
      uncalibrated
    </span>
  )
}

/** Renders a value, or an explicit dash when live cannot supply it. */
export function MaybeValue({
  value,
  unavailable,
  field,
  reason,
}: {
  value: React.ReactNode
  unavailable?: string[]
  field: string
  reason?: string
}) {
  if (unavailable?.includes(field)) {
    return (
      <span
        title={reason ?? `The API does not provide ${field}. Available in the demo narrative only.`}
        className="text-text-muted"
      >
        —
      </span>
    )
  }
  return <>{value}</>
}

/**
 * Banner shown when live mode is on and an API call failed.
 *
 * The failed endpoint is named. Demo values are not rendered in their place.
 */
export function FallbackBanner() {
  const { mode, fallbacks } = useDataMode()
  if (mode !== 'live' || fallbacks.length === 0) return null

  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="space-y-0.5">
        <p className="font-medium">
          Live request failed for {fallbacks.length} source{fallbacks.length === 1 ? '' : 's'} —
          demo data was not substituted
        </p>
        <ul className="text-amber-200/80">
          {fallbacks.map((f) => (
            <li key={f.endpoint}>
              <span className="font-mono">{f.endpoint}</span> — {f.reason}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/**
 * Standing explanation of what the current mode can and cannot show.
 *
 * Demo says it is scripted. Live says what the backend actually holds, so a
 * sparse screen reads as a true picture of the data rather than as a bug.
 */
export function ModeContextNote({ className }: { className?: string }) {
  const { mode, apiBase } = useDataMode()
  const { advanced } = useViewLevel()

  if (mode === 'demo') {
    return (
      <p className={cn('text-xs text-text-muted', className)}>
        <span className="font-medium text-intel">Demo</span> — a worked example of a Punjab
        stubble-burning episode drifting into Delhi NCR. Every figure is illustrative.
      </p>
    )
  }

  return (
    <p className={cn('text-xs text-text-muted', className)}>
      <span className="font-medium text-emerald-300">Live</span> — readings come from the
      AeroPulse API and TimescaleDB when the worker has persisted them. Demo values are not
      substituted. Empty charts and "—" mean the API had nothing for that field.
      {advanced ? (
        <>
          {' '}
          <span className="text-text-muted">
            API <span className="font-mono">{apiBase || '/api'}</span>. Connector mode and
            ingested sources determine whether figures are replay fixtures or live upstreams.
          </span>
        </>
      ) : null}
    </p>
  )
}

/**
 * Same episode, different question.
 *
 * Overview / Live Map / Events all read the Punjab–Delhi picture and must
 * not invent a second dataset. `question` is the plain thing this screen
 * answers and always renders. `serves` and `notThis` are the scoping notes
 * that kept three similar screens apart during development; they are
 * orientation for a reviewer, not for a citizen, so they stay in advanced.
 */
export function ScreenJobNote({
  question,
  serves,
  notThis,
}: {
  question: string
  serves: string
  notThis: string
}) {
  const { advanced } = useViewLevel()

  return (
    <p className="text-[11px] leading-snug text-text-secondary">
      <span className="font-medium text-text-primary">{question}</span>
      {advanced ? (
        <>
          <span className="text-text-muted"> · </span>
          {serves}
          <span className="text-text-muted"> · not </span>
          {notThis}
        </>
      ) : null}
    </p>
  )
}
