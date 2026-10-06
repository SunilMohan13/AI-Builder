import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { useApp } from '../../context/AppContext'
import { useHeroEventId } from '../../hooks/useHeroEventId'
import { heroEventPath } from '../../utils/heroEvent'

export function CommandPalette() {
  const { commandPaletteOpen, setCommandPaletteOpen } = useApp()

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setCommandPaletteOpen(true)
      }
      if (e.key === 'Escape') setCommandPaletteOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setCommandPaletteOpen])

  // Remounting on open resets query/selection without effects.
  if (!commandPaletteOpen) return null
  return <PaletteDialog onClose={() => setCommandPaletteOpen(false)} />
}

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const heroEventId = useHeroEventId()
  const commands = useMemo(
    () => [
      { label: 'Go to Overview', route: '/', keywords: 'home dashboard kpi briefing' },
      { label: 'Open Live Map', route: '/map', keywords: 'geospatial grid fire plume corridor' },
      { label: 'Investigate Event', route: heroEventPath(heroEventId), keywords: 'incident detect punjab' },
      { label: 'Open Forecast', route: '/forecast', keywords: 'predicted plume horizon' },
      { label: 'Open Risk', route: '/risk', keywords: 'population exposure' },
      { label: 'Open Evidence', route: '/evidence', keywords: 'graph provenance' },
      { label: 'Open Sources', route: '/sources', keywords: 'health connector freshness' },
      { label: 'Ask Copilot', route: '/copilot', keywords: 'ai question explain' },
      { label: 'Open Citizen Reports', route: '/citizen', keywords: 'crowdsource photo' },
    ],
    [heroEventId],
  )

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return commands
    return commands.filter((c) => c.label.toLowerCase().includes(q) || c.keywords.includes(q))
  }, [query, commands])

  const activeIndex = hoverIndex !== null && hoverIndex < results.length ? hoverIndex : 0

  const run = (route: string) => {
    navigate(route)
    onClose()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHoverIndex((activeIndex + 1) % results.length)
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHoverIndex((activeIndex - 1 + results.length) % results.length)
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      run(results[activeIndex].route)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[18vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label="Command palette"
        className="w-full max-w-lg rounded-lg border border-border bg-bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Search className="h-4 w-4 text-text-muted" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setHoverIndex(null)
            }}
            onKeyDown={onKeyDown}
            placeholder="Search commands..."
            aria-label="Search commands"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-text-muted"
          />
          <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted">
            esc
          </kbd>
        </div>
        <ul className="max-h-72 overflow-y-auto py-2">
          {results.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-text-muted">
              No commands match “{query}”
            </li>
          )}
          {results.map((cmd, i) => (
            <li key={cmd.route}>
              <button
                type="button"
                onMouseEnter={() => setHoverIndex(i)}
                className={`w-full px-4 py-2 text-left text-sm transition-colors ${
                  i === activeIndex
                    ? 'bg-bg-elevated text-text-primary'
                    : 'text-text-secondary hover:bg-bg-elevated hover:text-text-primary'
                }`}
                onClick={() => run(cmd.route)}
              >
                {cmd.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
