import { motion } from 'framer-motion'
import { cn } from '../../utils/cn'
import type { SourceLikelihood } from '../../types'

type Band = 'HIGH' | 'MED' | 'LOW'

function bandFor(probability: number): Band {
  if (probability >= 60) return 'HIGH'
  if (probability >= 30) return 'MED'
  return 'LOW'
}

const BAND_STYLES: Record<Band, { bar: string; label: string; track: string }> = {
  HIGH: {
    bar: 'bg-gradient-to-r from-orange-600 via-orange-500 to-red-500',
    label: 'text-red-400',
    track: 'bg-white/10',
  },
  MED: {
    bar: 'bg-gradient-to-r from-amber-700 via-amber-500 to-yellow-400',
    label: 'text-amber-300',
    track: 'bg-white/10',
  },
  LOW: {
    bar: 'bg-gradient-to-r from-teal-700 to-cyan-400',
    label: 'text-emerald-400',
    track: 'bg-white/10',
  },
}

export function SourceLikelihoodBars({
  items,
  className,
}: {
  items: SourceLikelihood[]
  className?: string
}) {
  return (
    <div className={cn('space-y-3', className)}>
      <p className="text-[11px] leading-snug text-text-muted">
        Source likelihood is probabilistic, not proof of causality.
      </p>
      {items.map((item, i) => {
        const band = bandFor(item.probability)
        const style = BAND_STYLES[band]
        return (
          <motion.div
            key={item.source}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.06 }}
            className="space-y-1.5"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[13px] text-text-primary">{item.source}</span>
              <span className={cn('font-mono text-[11px] font-semibold tracking-wide', style.label)}>
                {band}
              </span>
            </div>
            <div className={cn('h-2 overflow-hidden rounded-sm', style.track)}>
              <motion.div
                className={cn('h-full rounded-sm', style.bar)}
                initial={{ width: 0 }}
                animate={{ width: `${item.probability}%` }}
                transition={{ duration: 0.65, delay: i * 0.06 }}
              />
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
