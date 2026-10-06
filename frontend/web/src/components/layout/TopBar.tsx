import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Command, Play, Pause, Menu } from 'lucide-react'
import { StatusBadge } from '../common/Badge'
import { useApp } from '../../context/AppContext'
import { useDataMode } from '../../context/DataModeContext'
import { DataModeToggle } from './DataModeToggle'
import { ViewLevelToggle } from './ViewLevelToggle'
import { AdvancedOnly } from '../../context/ViewLevelContext'
import { formatDateTimeIST } from '../../utils/format'

export function TopBar() {
  const {
    livePaused,
    setLivePaused,
    lastLiveUpdate,
    setCommandPaletteOpen,
    setNotificationsOpen,
    notifications,
    startDemo,
    startJudgeTour,
    demoRunning,
    demoPaused,
    pauseDemo,
    exitDemo,
    setMobileNavOpen,
  } = useApp()
  const { mode } = useDataMode()
  const navigate = useNavigate()
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const secondsAgo = Math.max(0, Math.floor((now.getTime() - lastLiveUpdate.getTime()) / 1000))

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-bg-elevated/90 px-4 backdrop-blur-sm">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => setMobileNavOpen(true)}
          aria-label="Open navigation"
          className="rounded-md p-1.5 text-text-secondary hover:bg-bg-panel hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-intel md:hidden"
        >
          <Menu className="h-4 w-4" />
        </button>
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-intel/20">
            <span className="text-sm font-bold text-intel">AP</span>
          </div>
          <span className="text-lg font-semibold tracking-tight">AeroPulse</span>
        </div>
        <StatusBadge variant={mode === 'live' ? 'live' : 'default'}>
          {mode === 'live' ? '● Live API' : '● Demo'}
        </StatusBadge>
        <span className="hidden text-sm text-text-secondary md:inline">
          Punjab–Haryana–Delhi NCR
        </span>
      </div>

      <div className="flex items-center gap-3">
        <DataModeToggle />
        <ViewLevelToggle />

        <span className="hidden font-mono text-sm text-text-secondary sm:inline">
          {formatDateTimeIST(now.toISOString())} IST
        </span>

        <button
          type="button"
          onClick={() => setLivePaused(!livePaused)}
          className="hidden items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-text-secondary hover:border-border-subtle sm:flex"
        >
          {livePaused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
          {livePaused ? 'Resume' : `Updated ${secondsAgo}s ago`}
        </button>

        {!demoRunning ? (
          <div className="flex gap-1">
            <button
              type="button"
              onClick={startJudgeTour}
              className="rounded-md bg-intel/25 px-3 py-1.5 text-xs font-medium text-intel hover:bg-intel/35"
            >
              Guided tour
            </button>
            <AdvancedOnly>
              <button
                type="button"
                onClick={() => {
                  navigate('/map')
                  startDemo()
                }}
                className="hidden rounded-md border border-border px-2 py-1.5 text-xs text-text-muted hover:text-text-secondary sm:inline"
              >
                Map story
              </button>
            </AdvancedOnly>
          </div>
        ) : (
          <div className="flex gap-1">
            <button
              type="button"
              onClick={pauseDemo}
              className="rounded-md border border-border px-2 py-1 text-xs text-text-secondary hover:text-text-primary"
            >
              {demoPaused ? 'Resume' : 'Pause'}
            </button>
            <button
              type="button"
              onClick={exitDemo}
              className="rounded-md border border-border px-2 py-1 text-xs text-text-secondary hover:text-text-primary"
            >
              Exit
            </button>
          </div>
        )}

        <button
          type="button"
          onClick={() => setCommandPaletteOpen(true)}
          className="flex items-center gap-1 rounded-md border border-border px-2 py-1.5 text-xs text-text-muted hover:border-border-subtle hover:text-text-secondary"
          aria-label="Open command palette"
        >
          <Command className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">⌘K</span>
        </button>

        <button
          type="button"
          onClick={() => setNotificationsOpen(true)}
          className="relative rounded-md p-2 text-text-secondary hover:bg-bg-panel hover:text-text-primary"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          {notifications.length > 0 && (
            <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-intel" />
          )}
        </button>

        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-border text-xs font-medium">
          OP
        </div>
      </div>
    </header>
  )
}
