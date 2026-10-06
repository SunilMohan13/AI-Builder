import { cn } from '../../utils/cn'
import { useAnimatedNumber } from '../../hooks/useReducedMotion'

export function KpiStat({
  label,
  value,
  unit,
  sublabel,
  trend,
  decimals = 0,
  className,
}: {
  label: string
  value: number
  unit?: string
  sublabel?: string
  trend?: 'up' | 'down'
  decimals?: number
  className?: string
}) {
  const animated = useAnimatedNumber(value)
  const display = decimals > 0 || !Number.isInteger(value) ? animated.toFixed(1) : Math.round(animated).toLocaleString('en-IN')

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <span className="text-xs font-medium uppercase tracking-wider text-text-muted">{label}</span>
      <div className="flex items-baseline gap-1.5">
        <span className="font-mono text-3xl font-bold tabular-nums text-text-primary">
          {display}
        </span>
        {unit && <span className="text-sm text-text-secondary">{unit}</span>}
        {trend && (
          <span className={cn('text-sm', trend === 'up' ? 'text-red-400' : 'text-emerald-400')}>
            {trend === 'up' ? '↑' : '↓'}
          </span>
        )}
      </div>
      {sublabel && <span className="text-xs text-text-secondary">{sublabel}</span>}
    </div>
  )
}
