import { Bell, Command, Globe2, Menu } from 'lucide-react'
import { StatusBadge } from '../common/Badge'
import { useApp } from '../../context/AppContext'
import { useDataMode } from '../../context/DataModeContext'
import { useRegion } from '../../context/RegionContext'
import { useRegionClock } from '../../hooks/useRegionClock'
import { useRegionEvents } from '../../hooks/useRegionEvents'
import { formatDateTime } from '../../utils/format'
import { DataModeToggle } from './DataModeToggle'

function RegionSelect() {
  const { regions, regionId, setRegion, loading } = useRegion()
  if (loading) return <span className="text-xs text-text-muted">Loading regions…</span>
  if (regions.length === 0) {
    return <span className="text-xs text-amber-300">No regions (the region list did not load)</span>
  }
  return (
    <label className="flex items-center gap-1.5 text-sm">
      <Globe2 className="h-4 w-4 text-text-muted" aria-hidden />
      <span className="sr-only">Region</span>
      <select
        value={regionId ?? ''}
        onChange={(e) => setRegion(e.target.value)}
        className="rounded-md border border-border bg-bg-panel px-2 py-1 text-sm text-text-primary"
      >
        {regions.map((r) => (
          <option key={r.region_id} value={r.region_id}>
            {r.display_name}
            {r.snapshot ? '' : ' — no cycle yet'}
          </option>
        ))}
      </select>
    </label>
  )
}

function RegionClock() {
  const { now, timeZone, frozen } = useRegionClock()
  return (
    <span
      className="hidden font-mono text-xs text-text-secondary sm:inline"
      title={frozen ? 'Demo shows the moment the recording was made.' : `Local time in ${timeZone}`}
    >
      {frozen ? 'recorded ' : ''}
      {formatDateTime(now.toISOString(), timeZone)}
    </span>
  )
}

export function TopBar() {
  const { setCommandPaletteOpen, setNotificationsOpen, setMobileNavOpen } = useApp()
  const { mode } = useDataMode()
  const { data: events } = useRegionEvents()
  const open = events?.items.length ?? 0

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-bg-elevated/90 px-4 backdrop-blur-sm">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={() => setMobileNavOpen(true)}
          aria-label="Open navigation"
          className="rounded-md p-1.5 text-text-secondary hover:bg-bg-panel hover:text-text-primary md:hidden"
        >
          <Menu className="h-4 w-4" />
        </button>
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-intel/20">
            <span className="text-sm font-bold text-intel">AP</span>
          </div>
          <span className="hidden text-lg font-semibold tracking-tight sm:inline">AeroPulse</span>
        </div>
        <StatusBadge variant={mode === 'live' ? 'live' : 'default'}>
          {mode === 'live' ? '● Live API' : '● Demo recording'}
        </StatusBadge>
        <RegionSelect />
      </div>

      <div className="flex items-center gap-3">
        <RegionClock />
        <DataModeToggle />
        <button
          type="button"
          onClick={() => setCommandPaletteOpen(true)}
          className="flex items-center gap-1 rounded-md border border-border px-2 py-1.5 text-xs text-text-muted hover:text-text-secondary"
          aria-label="Open command palette"
        >
          <Command className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">⌘K</span>
        </button>
        <button
          type="button"
          onClick={() => setNotificationsOpen(true)}
          className="relative rounded-md p-2 text-text-secondary hover:bg-bg-panel hover:text-text-primary"
          aria-label={`Open events (${open})`}
        >
          <Bell className="h-4 w-4" />
          {open > 0 && (
            <span className="absolute -right-0.5 -top-0.5 rounded-full bg-intel px-1 text-[9px] font-semibold text-bg-base">
              {open}
            </span>
          )}
        </button>
      </div>
    </header>
  )
}
