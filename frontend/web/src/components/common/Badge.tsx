import { cn } from '../../utils/cn'

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
