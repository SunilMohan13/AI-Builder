import { ShieldCheck } from 'lucide-react'
import { getBandLabel } from '../../utils/aqi'

/**
 * What to do about the number.
 *
 * Every screen could say how bad the air was; none said what to do, and the
 * operator action brief sat behind a collapsed panel two clicks into the
 * event page. This is the standing public-health reading of a PM2.5 band —
 * it is derived from the band alone, not from a model, and it carries no
 * event-specific recommendation, which is why it is never labelled
 * RECOMMENDED or given a confidence.
 */
const GUIDANCE: { max: number; everyone: string; sensitive: string }[] = [
  { max: 30, everyone: 'Normal activity is fine.', sensitive: 'No precautions needed.' },
  {
    max: 60,
    everyone: 'Normal activity is fine.',
    sensitive: 'Unusually sensitive people may notice irritation on long exertion.',
  },
  {
    max: 90,
    everyone: 'Consider shortening prolonged outdoor exertion.',
    sensitive: 'Children, older adults and people with asthma or heart conditions should limit long outdoor exertion.',
  },
  {
    max: 120,
    everyone: 'Reduce prolonged or heavy outdoor exertion.',
    sensitive: 'Avoid prolonged outdoor exertion. Keep reliever medication to hand.',
  },
  {
    max: Number.POSITIVE_INFINITY,
    everyone: 'Avoid outdoor exertion. Keep windows closed where outdoor air is worse than indoor.',
    sensitive: 'Stay indoors. Seek medical advice if breathing becomes difficult.',
  },
]

export function HealthGuidance({ pm25 }: { pm25: number | null | undefined }) {
  if (pm25 == null) {
    return (
      <p className="text-[11px] text-text-muted">
        No current PM2.5 reading, so no health guidance can be given.
      </p>
    )
  }

  const band = GUIDANCE.find((g) => pm25 <= g.max) ?? GUIDANCE[GUIDANCE.length - 1]

  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 text-[11px] text-text-secondary">
        <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-emerald-400/80" aria-hidden />
        At {getBandLabel(pm25).toLowerCase()} levels:
      </p>
      <div>
        <p className="text-[10px] uppercase tracking-wider text-text-muted">Everyone</p>
        <p className="text-[11px] text-text-primary">{band.everyone}</p>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-wider text-text-muted">Sensitive groups</p>
        <p className="text-[11px] text-text-primary">{band.sensitive}</p>
      </div>
      <p className="text-[10px] text-text-muted">
        Standing guidance for this PM2.5 band, not a prediction for this event.
      </p>
    </div>
  )
}
