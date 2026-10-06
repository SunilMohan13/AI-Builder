import { Link } from 'react-router-dom'
import { cn } from '../../utils/cn'

export function SceneToggle({
  items,
}: {
  items: { to: string; label: string; active: boolean }[]
}) {
  return (
    <div className="flex rounded border border-white/10 p-0.5" role="tablist" aria-label="Map view">
      {items.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          role="tab"
          aria-selected={item.active}
          className={cn(
            'px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider',
            item.active ? 'bg-intel/20 text-intel' : 'text-text-muted hover:text-text-primary',
          )}
        >
          {item.label}
        </Link>
      ))}
    </div>
  )
}
