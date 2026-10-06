import { cn } from '../../utils/cn'
import type { ScientificLabel } from '../../types'

const labelStyles: Record<ScientificLabel, string> = {
  OBSERVED: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  INFERRED: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  PREDICTED: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  RECOMMENDED: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
}

export function ScientificBadge({ label }: { label: ScientificLabel }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
        labelStyles[label],
      )}
    >
      {label}
    </span>
  )
}

export function StatusBadge({
  children,
  variant = 'default',
}: {
  children: React.ReactNode
  variant?: 'default' | 'live' | 'severe' | 'success' | 'warning'
}) {
  const styles = {
    default: 'bg-slate-500/20 text-slate-300 border-slate-500/30',
    live: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30 glow-live',
    severe: 'bg-red-500/20 text-red-300 border-red-500/30',
    success: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    warning: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  }
  return (
    <span className={cn('inline-flex rounded border px-2 py-0.5 text-xs font-medium', styles[variant])}>
      {children}
    </span>
  )
}
