import { AlertTriangle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ScientificBadge } from '../common/Badge'

export function MapGrapBanner({ active }: { active: boolean }) {
  if (!active) return null

  return (
    <div
      className="pointer-events-auto absolute left-1/2 top-[4.5rem] z-[26] flex max-w-md -translate-x-1/2 items-start gap-2 rounded-lg border border-violet-400/35 bg-violet-950/80 px-3 py-2 shadow-lg backdrop-blur sm:top-[4.25rem]"
      role="status"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
      <div className="min-w-0 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-violet-100">GRAP advisory watch</span>
          <ScientificBadge label="RECOMMENDED" />
        </div>
        <p className="mt-0.5 text-text-muted">
          Projected plume intersects Delhi NCR footprint · consider Stage II measures (mock).
        </p>
        <Link to="/risk" className="mt-1 inline-block text-[10px] font-medium text-intel hover:underline">
          View population risk →
        </Link>
      </div>
    </div>
  )
}
