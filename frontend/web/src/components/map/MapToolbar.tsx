import { Camera, Crosshair, Globe2, Maximize2, Minimize2, Minus, Plus } from 'lucide-react'
import { cn } from '../../utils/cn'
import type { MapScene } from './MapViewControls'

interface MapToolbarProps {
  scene?: MapScene
  onToggleScene?: () => void
  zoom: number
  minZoom: number
  maxZoom: number
  onZoomIn: () => void
  onZoomOut: () => void
  onReset: () => void
  expanded: boolean
  onToggleExpand: () => void
  onExportSnapshot?: () => void
}

const button =
  'flex h-8 w-8 items-center justify-center text-text-secondary transition-colors ' +
  'hover:bg-bg-elevated hover:text-intel disabled:cursor-not-allowed disabled:opacity-35 ' +
  'disabled:hover:bg-transparent disabled:hover:text-text-secondary'

export function MapToolbar({
  scene,
  onToggleScene,
  zoom,
  minZoom,
  maxZoom,
  onZoomIn,
  onZoomOut,
  onReset,
  expanded,
  onToggleExpand,
  onExportSnapshot,
}: MapToolbarProps) {
  return (
    <div className="absolute right-4 top-4 z-20 flex flex-col items-end gap-2">
      <div className="flex flex-col overflow-hidden rounded-md border border-border bg-bg-panel/90 backdrop-blur">
        <button
          type="button"
          onClick={onZoomIn}
          disabled={zoom >= maxZoom}
          className={button}
          title="Zoom in"
          aria-label="Zoom in"
        >
          <Plus size={15} />
        </button>
        <div className="h-px bg-border" />
        <button
          type="button"
          onClick={onZoomOut}
          disabled={zoom <= minZoom}
          className={button}
          title="Zoom out"
          aria-label="Zoom out"
        >
          <Minus size={15} />
        </button>
        {onToggleScene && (
          <>
            <div className="h-px bg-border" />
            <button
              type="button"
              onClick={onToggleScene}
              className={cn(button, scene === 'globe' && 'text-cyan-300')}
              title={scene === 'globe' ? 'Switch to corridor map' : 'Switch to rotatable globe'}
              aria-label="Toggle globe view"
              aria-pressed={scene === 'globe'}
            >
              <Globe2 size={14} />
            </button>
          </>
        )}
        <div className="h-px bg-border" />
        <button
          type="button"
          onClick={onReset}
          className={button}
          title="Reset view"
          aria-label="Reset view"
        >
          <Crosshair size={14} />
        </button>
        {onExportSnapshot && (
          <>
            <div className="h-px bg-border" />
            <button
              type="button"
              onClick={onExportSnapshot}
              className={button}
              title="Export map snapshot"
              aria-label="Export map snapshot"
            >
              <Camera size={14} />
            </button>
          </>
        )}
        <div className="h-px bg-border" />
        <button
          type="button"
          onClick={onToggleExpand}
          className={button}
          title={expanded ? 'Exit full screen (Esc)' : 'Full screen'}
          aria-label={expanded ? 'Exit full screen' : 'Expand map to full screen'}
          aria-pressed={expanded}
        >
          {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>
      <span className="rounded border border-border bg-bg-panel/80 px-1.5 py-0.5 font-mono text-[10px] text-text-muted backdrop-blur">
        z{zoom.toFixed(1)}
      </span>
    </div>
  )
}
