import { useMemo, useState } from 'react'
import { searchLocations, type NamedLocation } from '../../utils/geo'
import type { MapScene } from './MapViewControls'

/**
 * Search and jump-to-fire. Layer toggles used to live here too, in a
 * centred strip that the globe/corridor pill overlapped; they now belong to
 * the single `MapViewControls` panel.
 */
export function MapControls({
  scene = 'corridor',
  onZoomToFire,
  onSelectLocation,
}: {
  scene?: MapScene
  onZoomToFire?: () => void
  onSelectLocation?: (location: NamedLocation) => void
}) {
  const [query, setQuery] = useState('')
  const results = useMemo(() => searchLocations(query), [query])

  const choose = (location: NamedLocation) => {
    onSelectLocation?.(location)
    setQuery('')
  }

  return (
    <>
      <div
        className={`absolute left-4 z-10 flex flex-col gap-1 ${
          scene === 'globe' ? 'top-14 sm:top-12' : 'top-4'
        }`}
      >
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && results[0]) choose(results[0])
            if (e.key === 'Escape') setQuery('')
          }}
          placeholder="Search location..."
          aria-label="Search location"
          className="w-40 rounded-md border border-cyan-500/20 bg-black/55 px-3 py-1.5 text-sm backdrop-blur placeholder:text-text-muted sm:w-48"
        />
        {results.length > 0 && (
          <ul className="w-40 overflow-hidden rounded-md border border-border bg-bg-panel/95 backdrop-blur sm:w-48">
            {results.map((location) => (
              <li key={location.name}>
                <button
                  type="button"
                  onClick={() => choose(location)}
                  className="w-full px-3 py-1.5 text-left text-xs text-text-secondary hover:bg-bg-elevated hover:text-text-primary"
                >
                  {location.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {onZoomToFire && (
        <button
          type="button"
          onClick={onZoomToFire}
          // Clears the zoom/expand toolbar pinned to the right edge.
          className={`absolute right-16 z-10 rounded-md border border-cyan-500/20 bg-black/55 px-3 py-1.5 text-xs text-text-secondary backdrop-blur hover:text-intel ${
            scene === 'globe' ? 'top-14 sm:top-12' : 'top-4'
          }`}
        >
          Zoom to Punjab fires
        </button>
      )}
    </>
  )
}
