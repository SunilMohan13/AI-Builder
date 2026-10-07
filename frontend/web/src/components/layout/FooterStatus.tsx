import { useDataMode } from '../../context/DataModeContext'
import { useRegion } from '../../context/RegionContext'
import { useRegionClock } from '../../hooks/useRegionClock'
import { formatDateTime, relativeTime } from '../../utils/format'

/** Cycle time and freshest source for the selected region, both as the API reported them. */
export function FooterStatus() {
  const { mode } = useDataMode()
  const { region } = useRegion()
  const { now, timeZone } = useRegionClock()
  const successes = (region?.sources ?? [])
    .map((s) => s.last_success_at)
    .filter((t): t is string => t !== null)
    .sort()
  const freshest = successes.at(-1) ?? null

  return (
    <footer className="flex h-8 shrink-0 items-center justify-between border-t border-border bg-bg-elevated/80 px-4 text-[11px] text-text-muted">
      <span>
        AeroPulse ·{' '}
        {mode === 'demo' ? 'Demo: a recording of the real API over one cycle' : 'Live: the AeroPulse API'}
      </span>
      <div className="flex gap-4">
        <span>
          Cycle:{' '}
          {region?.snapshot?.cycle_time ? (
            formatDateTime(region.snapshot.cycle_time, timeZone)
          ) : (
            <span title="No cycle has written a snapshot for this region.">— (no cycle yet)</span>
          )}
        </span>
        <span>
          Freshest source:{' '}
          {freshest ? (
            relativeTime(freshest, now)
          ) : (
            <span title="No source in this region reported a successful fetch.">— (none reported)</span>
          )}
        </span>
      </div>
    </footer>
  )
}
