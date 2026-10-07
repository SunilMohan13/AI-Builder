import type { ProvenanceClass } from '../../api/regionTypes'
import { cn } from '../../utils/cn'

/** One badge per provenance class (LLD APAC 4.2), so a value always says what it is. */
const CLASSES: Record<ProvenanceClass, { label: string; meaning: string; style: string }> = {
  measured: {
    label: 'Measured',
    meaning: 'A ground station or satellite detection.',
    style: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  },
  model_derived: {
    label: 'Model-derived',
    meaning: 'Atmospheric model output (e.g. CAMS, Open-Meteo), not a station reading.',
    style: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
  },
  predicted: {
    label: 'Predicted',
    meaning: 'An AeroPulse forecast or score; check the model version and whether it is degraded.',
    style: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  },
  simulated: {
    label: 'Simulated',
    meaning: 'A transport simulation (experimental), not an observation of smoke.',
    style: 'border-violet-500/40 bg-violet-500/10 text-violet-300',
  },
  heuristic: {
    label: 'Heuristic',
    meaning: 'Deterministic rules over measured inputs; scores rank, they are not probabilities.',
    style: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  },
  ai_observation: {
    label: 'AI observation',
    meaning: 'What a vision model saw in a photo. Counts only when corroborated.',
    style: 'border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300',
  },
  citizen: {
    label: 'Citizen',
    meaning: 'Reported by a member of the public.',
    style: 'border-slate-400/40 bg-slate-400/10 text-slate-300',
  },
}

export function ProvenanceBadge({
  value,
  className,
}: {
  value: ProvenanceClass | null | undefined
  className?: string
}) {
  if (!value) {
    return (
      <span
        title="The API did not state a provenance class for this value."
        className={cn('rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted', className)}
      >
        provenance —
      </span>
    )
  }
  const spec = CLASSES[value]
  return (
    <span
      title={spec.meaning}
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        spec.style,
        className,
      )}
    >
      {spec.label}
    </span>
  )
}
