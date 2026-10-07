import { NavLink } from 'react-router-dom'
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  Database,
  FileSearch,
  Map,
  MessageSquare,
  TrendingUp,
  X,
} from 'lucide-react'
import { cn } from '../../utils/cn'
import { useApp } from '../../context/AppContext'
import { useRegionLink } from '../../hooks/useRegionLink'

type Item = { to: string; label: string; hint: string; icon: typeof Map; end?: boolean }

/** Grouped by the question each screen answers. */
const NAV: { heading: string; items: Item[] }[] = [
  {
    heading: 'Now',
    items: [
      { to: '/', label: 'Command centre', hint: 'Map and incidents', icon: Map, end: true },
      { to: '/events', label: 'Events', hint: 'What the rules detected', icon: AlertTriangle },
    ],
  },
  {
    heading: 'Next',
    items: [{ to: '/forecast', label: 'Forecast', hint: 'PM2.5 and 24 h hazard', icon: TrendingUp }],
  },
  {
    heading: 'Why',
    items: [
      { to: '/evidence', label: 'Evidence', hint: 'Incident graph', icon: FileSearch },
      { to: '/copilot', label: 'Ask AeroPulse', hint: 'Questions', icon: Bot },
    ],
  },
  {
    heading: 'Inputs',
    items: [
      { to: '/citizen', label: 'Citizen reports', hint: 'Photos from the ground', icon: MessageSquare },
      { to: '/sources', label: 'Data sources', hint: 'Connector health', icon: Database },
      { to: '/models', label: 'Models', hint: 'Served versions and evaluation', icon: BrainCircuit },
    ],
  },
]

export function Sidebar() {
  const { sidebarCollapsed, setSidebarCollapsed, mobileNavOpen, setMobileNavOpen } = useApp()
  const link = useRegionLink()

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors',
      isActive ? 'bg-intel/10 text-intel' : 'text-text-secondary hover:bg-bg-panel hover:text-text-primary',
    )

  const nav = (showLabels: boolean) => (
    <nav className="flex-1 overflow-y-auto p-2" aria-label="Primary">
      {NAV.map((group) => (
        <div key={group.heading} className="mb-2">
          {showLabels ? (
            <p className="px-3 pb-1 pt-2 font-mono text-[9px] uppercase tracking-[0.18em] text-text-muted">
              {group.heading}
            </p>
          ) : (
            <div className="mx-3 my-2 border-t border-border" aria-hidden />
          )}
          <div className="space-y-0.5">
            {group.items.map(({ to, label, hint, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={link(to)}
                end={end}
                onClick={() => setMobileNavOpen(false)}
                className={linkClass}
                title={showLabels ? undefined : `${label} · ${hint}`}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {showLabels ? (
                  <span className="flex min-w-0 flex-col leading-tight">
                    <span>{label}</span>
                    <span className="text-[10px] text-text-muted">{hint}</span>
                  </span>
                ) : (
                  <span className="sr-only">{label}</span>
                )}
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  )

  return (
    <>
      <aside
        className={cn(
          'hidden shrink-0 flex-col border-r border-border bg-bg-elevated/95 transition-all duration-200 md:flex',
          sidebarCollapsed ? 'w-16' : 'w-52',
        )}
      >
        {nav(!sidebarCollapsed)}
        <div className="border-t border-border p-2">
          <button
            type="button"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-bg-panel hover:text-text-primary"
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            {!sidebarCollapsed && <span>Collapse</span>}
          </button>
        </div>
      </aside>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 flex bg-black/50 md:hidden" onClick={() => setMobileNavOpen(false)}>
          <div
            className="flex h-full w-60 flex-col border-r border-border bg-bg-elevated"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <span className="font-semibold">Navigation</span>
              <button type="button" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation">
                <X className="h-4 w-4 text-text-muted" />
              </button>
            </div>
            {nav(true)}
          </div>
        </div>
      )}
    </>
  )
}
