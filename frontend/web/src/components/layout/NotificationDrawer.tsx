import { useNavigate } from 'react-router-dom'
import { Flame, Cloud, AlertTriangle, X } from 'lucide-react'
import { useApp } from '../../context/AppContext'

const iconMap = {
  fire: Flame,
  forecast: Cloud,
  warning: AlertTriangle,
}

export function NotificationDrawer() {
  const { notificationsOpen, setNotificationsOpen, notifications } = useApp()
  const navigate = useNavigate()

  if (!notificationsOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={() => setNotificationsOpen(false)}>
      <div
        className="h-full w-80 border-l border-border bg-bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="font-semibold">Alerts</h2>
          <button type="button" onClick={() => setNotificationsOpen(false)} aria-label="Close">
            <X className="h-4 w-4 text-text-muted" />
          </button>
        </div>
        {notifications.length === 0 && (
          <p className="px-4 py-6 text-sm text-text-muted">
            No alerts. AeroPulse has no alert delivery endpoint yet, so this stays empty in
            Live mode even while events are open — see the Events page for current detections.
          </p>
        )}
        <ul className="divide-y divide-border">
          {notifications.map((n) => {
            const Icon = iconMap[n.icon]
            return (
              <li key={n.id}>
                <button
                  type="button"
                  className="flex w-full gap-3 px-4 py-3 text-left hover:bg-bg-elevated"
                  onClick={() => {
                    navigate(n.route)
                    setNotificationsOpen(false)
                  }}
                >
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-intel" />
                  <div>
                    <p className="text-sm font-medium">{n.title}</p>
                    <p className="text-xs text-text-secondary">{n.message}</p>
                    <p className="mt-1 text-[10px] text-text-muted">{n.time}</p>
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
