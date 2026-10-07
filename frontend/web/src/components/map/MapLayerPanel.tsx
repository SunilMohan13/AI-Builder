import type { AqiStandard } from '../../api/regionTypes'
import { RAMP_STOPS_UGM3, rampCss } from '../../utils/concentration'
import type { LayerToggles } from './RegionMap'

const LAYER_LABELS: { key: keyof LayerToggles; label: string; swatch: string }[] = [
  { key: 'cells', label: 'PM2.5 cells (1 km, H3 r8)', swatch: 'bg-teal-400' },
  { key: 'fires', label: 'Fire clusters (FIRMS)', swatch: 'bg-orange-500' },
  { key: 'wind', label: 'Wind (10 m)', swatch: 'bg-slate-200' },
  { key: 'plumes', label: 'Plume P50 / P90 (simulated)', swatch: 'bg-violet-400' },
  { key: 'citizen', label: 'Citizen reports', swatch: 'bg-fuchsia-500' },
]

export function MapLayerPanel({
  layers,
  onToggle,
  standard,
  horizons,
  horizonIndex,
  onHorizon,
}: {
  layers: LayerToggles
  onToggle: (key: keyof LayerToggles) => void
  standard: AqiStandard | null
  horizons: number[]
  horizonIndex: number
  onHorizon: (index: number) => void
}) {
  return (
    <div className="w-64 space-y-3 rounded-lg border border-border bg-bg-panel/90 p-3 text-xs backdrop-blur">
      <div>
        <p className="mb-1 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">Layers</p>
        {LAYER_LABELS.map(({ key, label, swatch }) => (
          <label key={key} className="flex cursor-pointer items-center gap-2 py-0.5">
            <input type="checkbox" checked={layers[key]} onChange={() => onToggle(key)} />
            <span className={`h-2 w-2 rounded-sm ${swatch}`} aria-hidden />
            <span className="text-text-secondary">{label}</span>
          </label>
        ))}
      </div>

      {layers.plumes && horizons.length > 0 && (
        <div>
          <p className="mb-1 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">
            Plume horizon: +{horizons[horizonIndex]} h
          </p>
          <input
            type="range"
            min={0}
            max={horizons.length - 1}
            value={horizonIndex}
            onChange={(e) => onHorizon(Number(e.target.value))}
            className="w-full"
            aria-label="Plume horizon"
          />
          <p className="text-[10px] text-text-muted">
            Dark: P50 cells; light: P90. Predicted smoke transport — experimental.
          </p>
        </div>
      )}

      <div>
        <p className="mb-1 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">
          Cell colour · hourly PM2.5 µg/m³
        </p>
        <div className="flex h-2 overflow-hidden rounded">
          {RAMP_STOPS_UGM3.map((stop) => (
            <span key={stop} className="flex-1" style={{ background: rampCss(stop) }} />
          ))}
        </div>
        <div className="mt-0.5 flex justify-between font-mono text-[9px] text-text-muted">
          {RAMP_STOPS_UGM3.map((stop) => (
            <span key={stop}>{stop}</span>
          ))}
        </div>
        <p className="mt-1 text-[10px] text-text-muted">
          A display ramp, not an AQI band. Grey cells have no served value.
        </p>
      </div>

      <div>
        <p className="mb-1 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">
          Air-quality standard
        </p>
        {standard ? (
          <>
            <p className="text-text-primary">{standard.name}</p>
            {standard.status === 'confirmed' ? (
              <>
                <p className="text-[10px] text-text-muted">
                  {standard.averaging ? `${standard.averaging} mean` : 'averaging —'} · bands shown
                  per cell only when the API sends one
                </p>
                <ul className="mt-1 space-y-0.5">
                  {standard.bands.map((b) => (
                    <li key={b.key} className="flex justify-between font-mono text-[10px] text-text-secondary">
                      <span>{b.label}</span>
                      <span>
                        {b.low}–{b.high ?? '+'}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-[10px] text-amber-300/90">
                Unconfirmed: {standard.reason ?? 'band table not yet confirmed'}. No bands are shown.
              </p>
            )}
          </>
        ) : (
          <p className="text-text-muted">— (region not loaded)</p>
        )}
      </div>
    </div>
  )
}
