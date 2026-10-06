import { useState } from 'react'
import { ChevronDown, Layers } from 'lucide-react'
import { cn } from '../../utils/cn'
import { useApp } from '../../context/AppContext'
import { useViewLevel } from '../../context/ViewLevelContext'
import type { MapLayerVisibility } from '../../types'
import type { BasemapFlavor } from './mapAtmosphere'

export type MapScene = 'globe' | 'corridor'

interface MapViewControlsProps {
  scene: MapScene
  onSceneChange: (scene: MapScene) => void
  basemap: BasemapFlavor
  onBasemapChange: (flavor: BasemapFlavor) => void
  dayNight: boolean
  onDayNightChange: (on: boolean) => void
  dimension3d: boolean
  onDimension3dChange: (on: boolean) => void
  showOrbit: boolean
  onShowOrbitChange: (on: boolean) => void
  className?: string
}

const chip =
  'rounded px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors'

/**
 * Data layers, in the order a reader needs them: what is in the air, what is
 * burning, where the wind is taking it, where it will be, then the two
 * context layers. `wind` and `forecast` answer "where is it moving", which
 * is a deliberate second question — hence off by default.
 */
const layerOptions: {
  key: keyof MapLayerVisibility
  label: string
  hint: string
  advancedOnly?: boolean
}[] = [
  { key: 'pollution', label: 'Air quality', hint: 'Measured PM2.5 by area' },
  { key: 'fires', label: 'Fires', hint: 'Satellite fire detections' },
  { key: 'wind', label: 'Wind', hint: 'Direction and speed' },
  { key: 'forecast', label: 'Predicted plume', hint: 'Where the smoke is heading' },
  { key: 'population', label: 'Population', hint: 'Who is underneath it' },
  { key: 'industry', label: 'Industry', hint: 'Known emitters', advancedOnly: true },
]

/**
 * The single map control surface.
 *
 * Scene, basemap and data layers used to live in three separate floating
 * panels, one of which sat underneath the globe/corridor pill and hid its
 * last two toggles. One panel, one place to look.
 */
export function MapViewControls({
  scene,
  onSceneChange,
  basemap,
  onBasemapChange,
  dayNight,
  onDayNightChange,
  dimension3d,
  onDimension3dChange,
  showOrbit,
  onShowOrbitChange,
  className,
}: MapViewControlsProps) {
  const { layers, toggleLayer } = useApp()
  const { advanced } = useViewLevel()
  const [open, setOpen] = useState(true)

  const visibleLayers = layerOptions.filter((o) => advanced || !o.advancedOnly)
  const activeCount = visibleLayers.filter((o) => layers[o.key]).length

  return (
    <div
      className={cn(
        'pointer-events-auto absolute bottom-[8.5rem] left-4 z-20 w-56 rounded-lg border border-cyan-500/20 bg-black/75 backdrop-blur-md shadow-[0_0_24px_rgba(34,211,238,0.12)] sm:bottom-36',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <Layers className="h-3.5 w-3.5 text-cyan-400/90" aria-hidden />
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-cyan-400/90">
          Layers
        </span>
        <span className="font-mono text-[9px] text-text-muted">
          {activeCount}/{visibleLayers.length}
        </span>
        <ChevronDown
          className={cn(
            'ml-auto h-3.5 w-3.5 text-text-muted transition-transform',
            !open && '-rotate-90',
          )}
          aria-hidden
        />
      </button>

      {!open ? null : (
        <div className="px-3 pb-3">
          <ul className="space-y-0.5">
            {visibleLayers.map(({ key, label, hint }) => (
              <li key={key}>
                <label
                  title={hint}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded px-1 py-1 text-[11px] text-text-secondary hover:bg-white/5"
                >
                  <span>{label}</span>
                  <input
                    type="checkbox"
                    checked={layers[key]}
                    onChange={() => toggleLayer(key)}
                    className="accent-cyan-400"
                  />
                </label>
              </li>
            ))}
          </ul>

          <div className="mt-2 flex flex-wrap gap-1 border-t border-border/80 pt-2">
            <button
              type="button"
              className={cn(
                chip,
                scene === 'globe'
                  ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-400/40'
                  : 'text-text-muted hover:text-text-secondary',
              )}
              onClick={() => onSceneChange('globe')}
            >
              Globe
            </button>
            <button
              type="button"
              className={cn(
                chip,
                scene === 'corridor'
                  ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-400/40'
                  : 'text-text-muted hover:text-text-secondary',
              )}
              onClick={() => onSceneChange('corridor')}
            >
              Corridor
            </button>
          </div>

          <div className="mt-2 flex flex-wrap gap-1 border-t border-border/80 pt-2">
            <button
              type="button"
              className={cn(
                chip,
                basemap === 'intel'
                  ? 'bg-slate-700/50 text-text-primary ring-1 ring-border'
                  : 'text-text-muted hover:text-text-secondary',
              )}
              onClick={() => onBasemapChange('intel')}
            >
              Map
            </button>
            <button
              type="button"
              className={cn(
                chip,
                basemap === 'satellite'
                  ? 'bg-slate-700/50 text-text-primary ring-1 ring-border'
                  : 'text-text-muted hover:text-text-secondary',
              )}
              onClick={() => onBasemapChange('satellite')}
            >
              Sat
            </button>
            <button
              type="button"
              className={cn(
                chip,
                dimension3d
                  ? 'bg-slate-700/50 text-text-primary ring-1 ring-border'
                  : 'text-text-muted hover:text-text-secondary',
              )}
              onClick={() => onDimension3dChange(!dimension3d)}
            >
              3D
            </button>
            <button
              type="button"
              className={cn(
                chip,
                !dimension3d
                  ? 'bg-slate-700/50 text-text-primary ring-1 ring-border'
                  : 'text-text-muted hover:text-text-secondary',
              )}
              onClick={() => onDimension3dChange(false)}
            >
              2D
            </button>
          </div>

          {advanced && (
            <>
              <label className="mt-2 flex cursor-pointer items-center justify-between gap-2 border-t border-border/80 pt-2 text-[11px] text-text-secondary">
                <span>Day / night cycle</span>
                <input
                  type="checkbox"
                  checked={dayNight}
                  onChange={(e) => onDayNightChange(e.target.checked)}
                  className="accent-cyan-400"
                />
              </label>
              <label className="mt-1.5 flex cursor-pointer items-center justify-between gap-2 text-[11px] text-text-secondary">
                <span>Orbital shell</span>
                <input
                  type="checkbox"
                  checked={showOrbit}
                  onChange={(e) => onShowOrbitChange(e.target.checked)}
                  className="accent-cyan-400"
                />
              </label>
            </>
          )}
        </div>
      )}
    </div>
  )
}
