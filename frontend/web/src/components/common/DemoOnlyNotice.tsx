import { Info } from 'lucide-react'
import { useDataMode } from '../../context/DataModeContext'

/**
 * Marks a screen that is live but whose data is thinner than the demo's.
 *
 * The numbers here are real, so the notice explains what is missing behind
 * them rather than warning that the screen is showing demo data.
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
