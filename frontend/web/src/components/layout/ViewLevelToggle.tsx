import { Eye, Wrench } from 'lucide-react'
import { useViewLevel } from '../../context/ViewLevelContext'
import { cn } from '../../utils/cn'

const btn =
  'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors'

/**
 * Simple / Advanced switch.
 *
 * Advanced is additive: it reveals confidence decomposition, model versions,
 * event ids and the endpoints behind a screen. It never hides anything a
 * simple view shows, so a user cannot lose information by switching.
 */
export function ViewLevelToggle() {
  const { level, setLevel } = useViewLevel()

  return (
    <div
      role="group"
      aria-label="Detail level"
      className="hidden items-center rounded-md border border-border bg-bg-panel p-0.5 lg:flex"
    >
      <button
        type="button"
        onClick={() => setLevel('customer')}
        aria-pressed={level === 'customer'}
        title="Plain language. What is happening and what to do."
        className={cn(
          btn,
          level === 'customer'
            ? 'bg-intel/25 text-intel'
            : 'text-text-muted hover:text-text-secondary',
        )}
      >
        <Eye className="h-3.5 w-3.5" />
        Simple
      </button>
      <button
        type="button"
        onClick={() => setLevel('advanced')}
        aria-pressed={level === 'advanced'}
        title="Adds confidence breakdown, model versions, event ids and source endpoints."
        className={cn(
          btn,
          level === 'advanced'
            ? 'bg-amber-500/20 text-amber-300'
            : 'text-text-muted hover:text-text-secondary',
        )}
      >
        <Wrench className="h-3.5 w-3.5" />
        Advanced
      </button>
    </div>
  )
}
