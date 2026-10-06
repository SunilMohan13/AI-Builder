import { Info } from 'lucide-react'
import { useDataMode } from '../../context/DataModeContext'

/**
 * Marks a screen that stays on demo data even while the app is in live mode.
 *
 * Unused. Citizen reports and the evidence graph are live; keep this component
 * only if a future screen is genuinely demo-only while the header says Live.
 */
export function DemoOnlyNotice({ reason }: { reason: string }) {
  const { mode } = useDataMode()
  if (mode !== 'live') return null

  return (
    <div className="flex items-start gap-2 rounded-md border border-intel/30 bg-intel/10 px-3 py-2 text-xs text-intel">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <p>
        <span className="font-medium">This screen is showing demo data.</span> {reason}
      </p>
    </div>
  )
}

/**
 * Marks a screen that *is* live but whose data is thinner than the demo's.
 *
 * Distinct from `DemoOnlyNotice`: the numbers here are real, so the notice
 * explains what is missing behind them rather than warning that nothing is.
 * Conflating the two would tell a reader that live data is demo data.
 */
export function LiveCaveatNotice({ reason }: { reason: string }) {
  const { mode } = useDataMode()
  if (mode !== 'live') return null

  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <p>
        <span className="font-medium">Live, with a gap.</span> {reason}
      </p>
    </div>
  )
}
