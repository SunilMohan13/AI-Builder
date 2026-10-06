import { hashNoise } from '../../utils/seededRandom'

/** Deterministic per-source quality trace, so the sparkline never flickers. */
function trace(seed: string, points: number, quality: number): number[] {
  const base = seed.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)
  return Array.from({ length: points }, (_, i) => {
    const drift = (hashNoise(base, i) - 0.5) * 8
    return Math.max(40, Math.min(100, quality + drift))
  })
}

export function Sparkline({
  seed,
  quality,
  points = 16,
  width = 72,
  height = 20,
  color = '#22d3ee',
}: {
  seed: string
  quality: number
  points?: number
  width?: number
  height?: number
  color?: string
}) {
  const values = trace(seed, points, quality)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1

  const path = values
    .map((v, i) => {
      const x = (i / (points - 1)) * width
      const y = height - ((v - min) / span) * height
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Quality trend, currently ${quality} percent`}
    >
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  )
}
