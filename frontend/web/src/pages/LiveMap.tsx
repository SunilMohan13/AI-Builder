import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AeroMap } from '../components/map/AeroMap'
import { SceneToggle } from '../components/layout/SceneToggle'
import { useDataMode } from '../context/DataModeContext'
import { FallbackBanner, ScreenJobNote } from '../components/common/Provenance'
import { AdvancedOnly } from '../context/ViewLevelContext'
import { fetchAirQuality, fetchFires } from '../services/mapService'

export function LiveMap() {
  const { mode } = useDataMode()
  const [searchParams] = useSearchParams()
  const globe = searchParams.get('scene') === 'globe'
  const { data: cells = [] } = useQuery({
    queryKey: ['air-quality', mode, 'map-hud'],
    queryFn: () => fetchAirQuality(),
  })
  const { data: fires = [] } = useQuery({
    queryKey: ['fires', mode, 'map-hud'],
    queryFn: () => fetchFires(),
  })

  return (
    <div className="flex h-full flex-col bg-black">
      <div className="shrink-0 border-b border-cyan-500/20 bg-gradient-to-r from-black via-bg-panel/40 to-black px-4 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="font-mono text-xs uppercase tracking-[0.22em] text-cyan-300/95">
              Live command map
            </h1>
            <ScreenJobNote
              question="Where is the pollution, area by area?"
              serves={`${cells.length} grid cells · ${fires.length} fire detections · wind, plume, timeline, layer toggles`}
              notThis="the event catalog or Detect evidence / likelihood"
            />
            <AdvancedOnly>
              <p className="text-[11px]">
                {mode === 'demo' ? (
                  <span className="text-intel">Demo · scripted Punjab episode.</span>
                ) : (
                  <span className="text-emerald-300">
                    Live · GET /api/v1/map/air-quality · /map/fire · /map/weather
                  </span>
                )}
              </p>
            </AdvancedOnly>
          </div>
          <SceneToggle
            items={[
              { to: '/map', label: 'Corridor', active: !globe },
              { to: '/map?scene=globe', label: 'Globe', active: globe },
            ]}
          />
        </div>
        <FallbackBanner />
      </div>
      <div className="relative min-h-0 flex-1">
        <AeroMap
          initialScene={globe ? 'globe' : 'corridor'}
          sceneRequest={globe ? 'globe' : 'corridor'}
        />
      </div>
    </div>
  )
}
