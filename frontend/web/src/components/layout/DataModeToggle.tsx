import { Database, Radio, AlertTriangle, Loader2 } from 'lucide-react'
import { useDataMode } from '../../context/DataModeContext'
import { cn } from '../../utils/cn'

/**
 * Demo / Live switch.
 *
 * Live is disabled, not merely unselected, when the backend is unreachable
 * or no token is configured. The toggle cannot be clicked into a Live
 * header that then paints demo numbers.
 */
export function DataModeToggle() {
  const { mode, setMode, blocker, blockerMessage, checking } = useDataMode()
  const liveDisabled = blocker !== null

  return (
    <div className="flex items-center gap-1.5">
      <div
        role="group"
        aria-label="Data source"
        className="flex items-center rounded-md border border-border bg-bg-panel p-0.5"
      >
        <button
          type="button"
          onClick={() => setMode('demo')}
          aria-pressed={mode === 'demo'}
          title="Scripted Punjab → Delhi episode. Works offline."
          className={cn(
            'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors',
            mode === 'demo'
              ? 'bg-intel/25 text-intel'
              : 'text-text-muted hover:text-text-secondary',
          )}
        >
          <Database className="h-3.5 w-3.5" />
          Demo
        </button>
        <button
          type="button"
          onClick={() => !liveDisabled && setMode('live')}
          aria-pressed={mode === 'live'}
          disabled={liveDisabled}
          title={blockerMessage ?? 'Read from the AeroPulse API'}
          className={cn(
            'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors',
            mode === 'live'
              ? 'bg-emerald-500/20 text-emerald-300'
              : 'text-text-muted hover:text-text-secondary',
            liveDisabled && 'cursor-not-allowed opacity-40 hover:text-text-muted',
          )}
        >
          {checking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Radio className="h-3.5 w-3.5" />
          )}
          Live
        </button>
      </div>

      {liveDisabled && (
        <span
          title={blockerMessage ?? undefined}
          className="hidden items-center gap-1 text-[11px] text-amber-400/80 lg:flex"
        >
          <AlertTriangle className="h-3 w-3" />
          {blocker === 'no-token' ? 'no token' : 'API offline'}
        </span>
      )}
    </div>
  )
}
