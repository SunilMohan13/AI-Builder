import { useApp } from '../../context/AppContext'

const phaseMessages: Record<string, string> = {
  fire: '🔥 FIRE DETECTED',
  anomaly: 'PM2.5 ANOMALY DETECTED',
  wind: 'WIND ALIGNMENT CONFIRMED',
  plume: 'POLLUTION MOVEMENT FORECAST',
  confirmed: 'EVENT CONFIRMED — Confidence 94%',
  forecast: 'FORECAST PLUME ACTIVE',
  risk: 'POPULATION RISK — 2.4M',
  complete: 'SIMULATION COMPLETE',
}

export function DemoOverlay() {
  const { demoPhase, demoRunning, skipDemo, tourCaption, judgeTourRunning, stopJudgeTour } =
    useApp()

  if (!demoRunning && demoPhase !== 'complete') return null
  if (demoPhase === 'idle') return null

  const label = tourCaption ?? phaseMessages[demoPhase] ?? 'DEMO MODE'

  return (
    <div className="pointer-events-none absolute inset-x-0 top-16 z-30 flex justify-center px-4 sm:top-14">
      <div
        className="pointer-events-auto flex max-w-2xl items-center gap-3 rounded-lg border border-intel/40 bg-bg-panel/95 px-4 py-2 shadow-lg backdrop-blur"
      >
        <span className="text-center text-sm font-semibold text-intel">{label}</span>
        {demoRunning && (
          <button
            type="button"
            onClick={judgeTourRunning ? stopJudgeTour : skipDemo}
            className="shrink-0 text-xs text-text-muted hover:text-text-primary"
          >
            {judgeTourRunning ? 'Stop tour' : 'Skip'}
          </button>
        )}
      </div>
    </div>
  )
}
