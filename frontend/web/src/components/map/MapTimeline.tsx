import { useEffect, useRef, useState } from 'react'
import { useApp } from '../../context/AppContext'

const MIN = -2
const MAX = 48

/** Sparse ticks, positioned by their real value so they track the thumb. */
const marks = [-2, 0, 6, 12, 24, 36, 48]

const percent = (v: number) => ((v - MIN) / (MAX - MIN)) * 100

export function MapTimeline() {
  const { hourOffset, setHourOffset } = useApp()

  // The thumb tracks the pointer immediately, but the committed hour is
  // debounced: each distinct hour regenerates a large grid snapshot, and
  // committing every intermediate value during a drag exhausted memory.
  const [dragging, setDragging] = useState<number | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shown = dragging ?? hourOffset

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const commit = (value: number) => {
    setDragging(value)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      setHourOffset(value)
      setDragging(null)
    }, 110)
  }

  const label =
    shown === 0 ? 'Current' : shown > 0 ? `+${shown}h forecast` : `${shown}h ago`

  return (
    <div className="absolute bottom-4 left-4 right-4 z-10 rounded-lg border border-border bg-bg-panel/90 px-4 py-3 backdrop-blur">
      <div className="mb-2 flex items-baseline justify-between text-xs">
        <span className="text-text-muted">Observed</span>
        <span className="font-mono font-medium text-intel">{label}</span>
        <span className="text-text-muted">Predicted +48h</span>
      </div>

      <div className="relative">
        <input
          type="range"
          min={MIN}
          max={MAX}
          step={1}
          value={shown}
          onChange={(e) => commit(Number(e.target.value))}
          className="w-full accent-cyan-400"
          aria-label="Timeline hour offset"
          aria-valuetext={label}
        />
        {/* Boundary between measured history and model output. */}
        <span
          aria-hidden
          className="pointer-events-none absolute -top-0.5 h-4 w-px bg-intel/50"
          style={{ left: `${percent(0)}%` }}
        />
      </div>

      <div className="relative mt-1 h-4">
        {marks.map((m) => (
          <span
            key={m}
            className="absolute -translate-x-1/2 text-[10px] text-text-muted"
            style={{ left: `${percent(m)}%` }}
          >
            {m === 0 ? 'Now' : `${m > 0 ? '+' : ''}${m}h`}
          </span>
        ))}
      </div>
    </div>
  )
}
