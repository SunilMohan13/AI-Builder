import { useEffect, useState } from 'react'
import { useReducedMotion } from './useReducedMotion'

/**
 * Shared seconds-elapsed clock for map animations, throttled to `fps` so we
 * don't rebuild layers on every display frame. Returns a frozen value when the
 * user prefers reduced motion.
 */
export function useAnimationClock(fps = 24): number {
  const reducedMotion = useReducedMotion()
  const [time, setTime] = useState(0)

  useEffect(() => {
    if (reducedMotion) return

    let frame = 0
    const start = performance.now()
    let last = 0
    const interval = 1000 / fps

    const tick = (now: number) => {
      if (now - last >= interval) {
        last = now
        setTime((now - start) / 1000)
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [reducedMotion, fps])

  return reducedMotion ? 0 : time
}
