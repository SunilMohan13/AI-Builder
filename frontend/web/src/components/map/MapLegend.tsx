import { getPollutionSwatch } from '../../utils/aqi'
import { useDataMode } from '../../context/DataModeContext'
import { useViewLevel } from '../../context/ViewLevelContext'

const bands = [
  { label: 'Good', max: 30, sample: 18 },
  { label: 'Moderate', max: 60, sample: 45 },
  { label: 'Poor', max: 90, sample: 75 },
  { label: 'Very Poor', max: 120, sample: 105 },
  { label: 'Severe', max: null, sample: 190 },
]

const gradient = `linear-gradient(to right, ${[0, 25, 45, 65, 95, 130, 200, 280]
  .map((v, i, arr) => `${getPollutionSwatch(v)} ${(i / (arr.length - 1)) * 100}%`)
  .join(', ')})`

export function MapLegend({ resolutionKm }: { resolutionKm: number }) {
  const { mode } = useDataMode()
  const { advanced } = useViewLevel()
  // Plume, persistence baseline and exposure ribbon are scripted scenario
  // layers. Live never draws them, so live must not caption them either.
  const scenarioLayers = mode === 'demo'

  return (
    <div className="absolute bottom-32 right-4 z-10 hidden w-52 rounded-lg border border-border bg-bg-panel/85 p-3 backdrop-blur-md sm:block">
      <p className="text-[10px] font-medium uppercase tracking-wider text-text-muted">
        PM2.5 µg/m³
      </p>

      <div
        aria-hidden
        className="mt-2 h-2 w-full rounded-full ring-1 ring-inset ring-white/10"
        style={{ background: gradient }}
      />
      <div className="mt-1 flex justify-between text-[9px] font-mono text-text-muted">
        <span>0</span>
        <span>60</span>
        <span>120</span>
        <span>280+</span>
      </div>

      <ul className="mt-2 space-y-0.5">
        {bands.map((band) => (
          <li key={band.label} className="flex items-center gap-2 text-[11px]">
            <span
              aria-hidden
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: getPollutionSwatch(band.sample) }}
            />
            <span className="text-text-secondary">{band.label}</span>
            <span className="ml-auto font-mono text-text-muted">
              {band.max ? `≤${band.max}` : '120+'}
            </span>
          </li>
        ))}
      </ul>

      {scenarioLayers && (
        <>
          <div className="mt-2 flex items-center gap-2 border-t border-border pt-2 text-[11px]">
            <span
              aria-hidden
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: 'rgba(255, 200, 150, 0.85)' }}
            />
            <span className="text-text-secondary">Model plume (cyan)</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[11px]">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-slate-400/80" />
            <span className="text-text-secondary">Baseline persistence</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[11px]">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-amber-400/90" />
            <span className="text-text-secondary">Exposure ribbon</span>
          </div>
        </>
      )}

      {advanced && (
        <p className="mt-2 text-[10px] text-text-muted">
          Grid{' '}
          {resolutionKm <= 1.01 ? '1 km (native)' : `${resolutionKm.toFixed(0)} km (downsampled)`}
        </p>
      )}
    </div>
  )
}
