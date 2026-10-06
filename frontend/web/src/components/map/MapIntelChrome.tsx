import { cn } from '../../utils/cn'
import type { MapScene } from './MapViewControls'

const TICKER = [
  'CPCB · Delhi AQI band POOR · freshness 12m',
  'FIRMS · 14 thermal anomalies Punjab–Haryana · confidence medium',
  'IMD · W-NW winds 8–12 km/h toward NCR',
  'CAMS · transported smoke signal ↑ Indo-Gangetic',
  'MOCK · Corridor forecast +6h PM2.5 ↑ 18%',
  'SENSOR · 6/7 connectors online · Kafka lag nominal',
]

interface MapIntelChromeProps {
  scene: MapScene
  className?: string
}

/** Lightweight globe HUD — navigation lives in the app sidebar + map controls. */
export function MapIntelChrome({ scene, className }: MapIntelChromeProps) {
  if (scene !== 'globe') return null

  return (
    <div className={cn('pointer-events-none absolute inset-0 z-[25]', className)}>
      <div
        className="absolute inset-x-0 top-0 flex items-center justify-between border-b border-cyan-500/20 bg-gradient-to-b from-black/80 to-transparent px-3 py-1.5 backdrop-blur-sm"
        aria-hidden
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-cyan-300/90">
          Global monitoring view
        </p>
        <span className="flex items-center gap-1.5 font-mono text-[9px] text-emerald-400/90">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
          LIVE MOCK
        </span>
      </div>

      <div
        className="absolute inset-x-0 bottom-[4.75rem] overflow-hidden border-t border-cyan-500/15 bg-black/70 py-1 backdrop-blur-sm sm:bottom-[5.25rem]"
        aria-hidden
      >
        <div className="aero-intel-ticker flex whitespace-nowrap font-mono text-[10px] text-cyan-100/85">
          {TICKER.map((line) => (
            <span key={line} className="mx-8 shrink-0">
              <span className="text-orange-400/90">▸</span> {line}
            </span>
          ))}
          {TICKER.map((line) => (
            <span key={`${line}-dup`} className="mx-8 shrink-0" aria-hidden>
              <span className="text-orange-400/90">▸</span> {line}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
