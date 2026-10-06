import { useEffect, useRef, useState } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

export function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(QUERY).matches,
  )
  useEffect(() => {
    const mq = window.matchMedia(QUERY)
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return reduced
}

/** Counts from the previous value to the new one; snaps when motion is reduced. */
export function useAnimatedNumber(target: number, duration = 800) {
  const [value, setValue] = useState(target)
  const valueRef = useRef(target)
  const reduced = useReducedMotion()

  useEffect(() => {
    valueRef.current = value
  }, [value])

  useEffect(() => {
    if (reduced) return
    const start = valueRef.current
    const diff = target - start
    if (diff === 0) return

    let frame = 0
    const startTime = performance.now()
    const tick = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1)
      const eased = 1 - (1 - progress) ** 3
      setValue(start + diff * eased)
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, duration, reduced])

  return reduced ? target : value
}
