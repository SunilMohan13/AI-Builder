import { Film, Layers } from 'lucide-react'
import { useApp } from '../../context/AppContext'
import { cn } from '../../utils/cn'
import type { MapScene } from './MapViewControls'

interface MapScenarioPanelProps {
  scene: MapScene
  className?: string
}

/**
 * The narrated 60-second walkthrough, on its own.
 *
 * It is the clearest thing on the map for a first-time viewer, so it stays
 * out of the analyst panel that the rest of the scenario lab lives in.
 */
export function MapStoryButton({ className }: { className?: string }) {
  const { mapStoryRunning, startMapStory, stopMapStory } = useApp()

  return (
    <button
      type="button"
      onClick={mapStoryRunning ? stopMapStory : startMapStory}
      className={cn(
        'pointer-events-auto absolute left-4 top-[4.5rem] z-20 flex items-center gap-2 rounded-md border border-cyan-500/30 bg-black/70 px-3 py-1.5 text-[11px] font-medium text-cyan-200 backdrop-blur-md hover:bg-cyan-500/20 sm:top-[4.25rem]',
        className,
      )}
    >
      <Film size={14} aria-hidden />
      {mapStoryRunning ? 'Stop the story' : 'Play the 60s story'}
    </button>
  )
}

export function MapScenarioPanel({ scene, className }: MapScenarioPanelProps) {
  const {
    windBearingOffset,
    setWindBearingOffset,
    showBaselinePlume,
    setShowBaselinePlume,
    showGrapZone,
    setShowGrapZone,
    showExposureRibbon,
    setShowExposureRibbon,
    showFireSeasonGlobe,
    setShowFireSeasonGlobe,
    mapStoryRunning,
    startMapStory,
    stopMapStory,
  } = useApp()

  if (scene === 'globe') {
    return (
      <div
        className={cn(
          'pointer-events-auto absolute left-4 top-[4.5rem] z-20 w-52 rounded-lg border border-cyan-500/20 bg-black/70 p-3 backdrop-blur-md sm:top-[4.25rem]',
          className,
        )}
      >
        <p className="font-mono text-[9px] uppercase tracking-wider text-cyan-300/85">Globe layers</p>
        <label className="mt-2 flex cursor-pointer items-center justify-between text-[11px] text-text-secondary">
          <span>Fire season signal (mock)</span>
          <input
            type="checkbox"
            checked={showFireSeasonGlobe}
            onChange={(e) => setShowFireSeasonGlobe(e.target.checked)}
            className="accent-cyan-400"
          />
        </label>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'pointer-events-auto absolute left-4 top-[4.5rem] z-20 w-56 rounded-lg border border-cyan-500/20 bg-black/70 p-3 backdrop-blur-md sm:top-[4.25rem]',
        className,
      )}
    >
      <div className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-cyan-300/85">
        <Layers size={12} />
        Scenario lab
      </div>

      <label className="mt-3 block text-[10px] text-text-muted">
        What-if wind {windBearingOffset > 0 ? '+' : ''}
        {windBearingOffset}° · PREDICTED scenario
      </label>
      <input
        type="range"
        min={-30}
        max={30}
        step={5}
        value={windBearingOffset}
        onChange={(e) => setWindBearingOffset(Number(e.target.value))}
        className="mt-1 w-full accent-cyan-400"
        aria-label="Wind direction scenario offset"
      />

      <div className="mt-3 space-y-1.5 text-[11px] text-text-secondary">
        <label className="flex cursor-pointer justify-between gap-2">
          <span>Baseline plume (persistence)</span>
          <input
            type="checkbox"
            checked={showBaselinePlume}
            onChange={(e) => setShowBaselinePlume(e.target.checked)}
            className="accent-cyan-400"
          />
        </label>
        <label className="flex cursor-pointer justify-between gap-2">
          <span>GRAP NCR zone</span>
          <input
            type="checkbox"
            checked={showGrapZone}
            onChange={(e) => setShowGrapZone(e.target.checked)}
            className="accent-cyan-400"
          />
        </label>
        <label className="flex cursor-pointer justify-between gap-2">
          <span>Exposure ribbon</span>
          <input
            type="checkbox"
            checked={showExposureRibbon}
            onChange={(e) => setShowExposureRibbon(e.target.checked)}
            className="accent-cyan-400"
          />
        </label>
      </div>

      <button
        type="button"
        onClick={mapStoryRunning ? stopMapStory : startMapStory}
        className="mt-3 flex w-full items-center justify-center gap-2 rounded-md border border-cyan-500/30 bg-cyan-500/10 py-1.5 text-[11px] font-medium text-cyan-200 hover:bg-cyan-500/20"
      >
        <Film size={14} />
        {mapStoryRunning ? 'Stop map story' : 'Play 60s map story'}
      </button>
    </div>
  )
}
