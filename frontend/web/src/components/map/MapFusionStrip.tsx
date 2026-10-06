import { useQuery } from '@tanstack/react-query'
import { fetchSources } from '../../services/sourceService'
import { formatFreshness } from '../../utils/format'
import { cn } from '../../utils/cn'
import { useDataMode } from '../../context/DataModeContext'

interface MapFusionStripProps {
  className?: string
}

/** Live-style connector freshness + fusion agreement for the map chrome. */
export function MapFusionStrip({ className }: MapFusionStripProps) {
  const { mode } = useDataMode()
  const { data: sources = [] } = useQuery({
    queryKey: ['sources', mode],
    queryFn: fetchSources,
    staleTime: 15_000,
  })

  // Previously `min(healthy, 4)` and captioned "agree". Nothing here
  // compares sources, so it reported an agreement it had not computed.
  // It now says what it actually counted: sources that are reporting.
  const reporting = sources.filter(
    (s) => s.status === 'Healthy' || s.status === 'Delayed' || s.status === 'Registered',
  ).length

  return (
    <div
      className={cn(
        'pointer-events-none absolute inset-x-0 top-0 z-[22] flex justify-center px-2 pt-2 sm:pt-3',
        className,
      )}
    >
      <div
        className="flex max-w-full flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-full border border-cyan-500/20 bg-black/70 px-3 py-1.5 font-mono text-[9px] uppercase tracking-wide text-cyan-100/90 backdrop-blur-md sm:text-[10px]"
        aria-live="polite"
      >
        <span className="text-emerald-400/95">
          {reporting}/{sources.length || 0} sources reporting
        </span>
        <span className="hidden text-border sm:inline">|</span>
        {sources.slice(0, 5).map((s) => (
          <span key={s.id} className="text-text-muted">
            <span
              className={
                s.status === 'Healthy' || s.status === 'Delayed' || s.status === 'Registered'
                  ? 'text-emerald-400/90'
                  : 'text-amber-400/90'
              }
            >
              {s.name}
            </span>
            {' '}
            {formatFreshness(s.freshnessMinutes)}
          </span>
        ))}
      </div>
    </div>
  )
}
