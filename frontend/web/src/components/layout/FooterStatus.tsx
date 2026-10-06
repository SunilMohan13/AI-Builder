import { useQuery } from '@tanstack/react-query'
import { useApp } from '../../context/AppContext'
import { useDataMode } from '../../context/DataModeContext'
import { AdvancedOnly } from '../../context/ViewLevelContext'
import { fetchSources } from '../../services/sourceService'
import { formatDateTimeIST, formatFreshness } from '../../utils/format'

/**
 * The status line previously printed "Data freshness: 2 min · Models:
 * Production" as literals, in both modes. It read as a live system claim
 * while being a constant, which is the exact failure the mode split exists
 * to prevent. Freshness is now derived, or absent.
 */
export function FooterStatus() {
  const { lastLiveUpdate } = useApp()
  const { mode } = useDataMode()
  const { data: sources = [] } = useQuery({
    queryKey: ['sources', mode],
    queryFn: fetchSources,
    staleTime: 30_000,
  })

  const measured = sources
    .map((s) => s.freshnessMinutes)
    .filter((m): m is number => m !== null)
  const freshest = measured.length > 0 ? Math.min(...measured) : null

  return (
    <footer className="flex h-8 shrink-0 items-center justify-between border-t border-border bg-bg-elevated/80 px-4 text-[11px] text-text-muted">
      <span>
        AeroPulse
        {mode === 'demo' ? ' · demo walkthrough' : ' · connected to the AeroPulse API'}
      </span>
      <div className="flex gap-4">
        <span>
          Freshest source:{' '}
          {freshest === null ? (
            <span title="No source reported a measured ingestion time.">not reported</span>
          ) : (
            formatFreshness(freshest)
          )}
        </span>
        <AdvancedOnly>
          <span>Screen refreshed {formatDateTimeIST(lastLiveUpdate.toISOString())} IST</span>
        </AdvancedOnly>
      </div>
    </footer>
  )
}
