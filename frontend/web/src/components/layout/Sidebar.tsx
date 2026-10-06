import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Map,
  AlertTriangle,
  TrendingUp,
  Users,
  FileSearch,
  Database,
  Bot,
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react'
import { cn } from '../../utils/cn'
import { useApp } from '../../context/AppContext'
import { useHeroEventId } from '../../hooks/useHeroEventId'

export function Sidebar() {
  const { sidebarCollapsed, setSidebarCollapsed, mobileNavOpen, setMobileNavOpen } = useApp()
  const heroEventId = useHeroEventId()

  // Grouped by the question each screen answers. Nine equal-weight links
  // gave no clue which to open first, and left Forecast (where is it going)
  // sitting between Events and Risk as if it were the same kind of thing.
  const navGroups: {
    heading: string
    items: {
      to: string
      label: string
      hint?: string
      icon: typeof LayoutDashboard
      end?: boolean
    }[]
  }[] = [
    {
      heading: 'Now',
      items: [
        { to: '/', label: 'Overview', hint: 'How bad is it', icon: LayoutDashboard, end: true },
        { to: '/map', label: 'Live Map', hint: 'Where is it', icon: Map },
      ],
    },
    {
      heading: 'Next',
      items: [
        { to: '/forecast', label: 'Forecast', hint: 'Where it is heading', icon: TrendingUp },
        { to: '/risk', label: 'Exposure', hint: 'Who is affected', icon: Users },
      ],
    },
    {
      heading: 'Why',
      items: [
        {
          to: heroEventId ? `/events/${heroEventId}` : '/events',
          label: 'Events',
          hint: 'What caused it',
          icon: AlertTriangle,
        },
        { to: '/evidence', label: 'Evidence', hint: 'What we fused', icon: FileSearch },
        { to: '/copilot', label: 'Ask AeroPulse', hint: 'Questions', icon: Bot },
      ],
    },
    {
      heading: 'Inputs',
      items: [
        { to: '/citizen', label: 'Citizen reports', hint: 'Photos from the ground', icon: MessageSquare },
        { to: '/sources', label: 'Data sources', hint: 'Feeds and models', icon: Database },
      ],
    },
  ]

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-intel',
      isActive
        ? 'bg-intel/10 text-intel'
        : 'text-text-secondary hover:bg-bg-panel hover:text-text-primary',
    )

  const nav = (showLabels: boolean) => (
    <nav className="flex-1 overflow-y-auto p-2" aria-label="Primary">
      {navGroups.map((group) => (
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
                to={to}
                end={end}
                onClick={() => setMobileNavOpen(false)}
                className={linkClass}
                title={showLabels ? undefined : `${label}${hint ? ` · ${hint}` : ''}`}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {showLabels ? (
                  <span className="flex min-w-0 flex-col leading-tight">
                    <span>{label}</span>
                    {hint ? <span className="text-[10px] text-text-muted">{hint}</span> : null}
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
      {/* Desktop rail */}
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
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-bg-panel hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-intel"
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? (
              <ChevronRight className="h-4 w-4" aria-hidden />
            ) : (
              <ChevronLeft className="h-4 w-4" aria-hidden />
            )}
            {!sidebarCollapsed && <span>Collapse</span>}
          </button>
          {/* A "Settings" entry used to sit here and navigate to /sources,
              which is a second, mislabelled door onto a page already in the
              nav. There is no settings screen, so there is no link. */}
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-50 flex bg-black/50 md:hidden"
          onClick={() => setMobileNavOpen(false)}
        >
          <div
            className="flex h-full w-60 flex-col border-r border-border bg-bg-elevated"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <span className="font-semibold">Navigation</span>
              <button
                type="button"
                onClick={() => setMobileNavOpen(false)}
                aria-label="Close navigation"
                className="text-text-muted hover:text-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {nav(true)}
          </div>
        </div>
      )}
    </>
  )
}
