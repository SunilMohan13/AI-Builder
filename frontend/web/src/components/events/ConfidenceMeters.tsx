import { motion } from 'framer-motion'
import { cn } from '../../utils/cn'

export function ConfidenceMeters({
  items,
  className,
}: {
  items: { label: string; value: number }[]
  className?: string
}) {
  return (
    <div className={cn('grid grid-cols-2 gap-px bg-border/70 sm:grid-cols-4', className)}>
      {items.map((item, i) => (
        <motion.div
          key={item.label}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05 }}
          className="bg-bg-panel/95 px-4 py-3"
        >
          <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">{item.label}</p>
          <p className="mt-1 font-mono text-3xl font-semibold tabular-nums tracking-tight text-text-primary">
            {Math.round(item.value)}
            <span className="ml-0.5 text-base font-medium text-text-secondary">%</span>
          </p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
            <motion.div
              className="h-full rounded-full bg-emerald-400"
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(item.value, 100)}%` }}
              transition={{ duration: 0.7, delay: 0.1 + i * 0.05 }}
            />
          </div>
        </motion.div>
      ))}
    </div>
  )
}
