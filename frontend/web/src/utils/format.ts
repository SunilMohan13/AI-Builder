export function formatNumber(n: number, decimals = 0): string {
  return n.toLocaleString('en-IN', { maximumFractionDigits: decimals })
}

function parsedInstant(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const when = new Date(iso)
  return Number.isNaN(when.getTime()) ? null : when
}

export function formatTimeIST(iso: string): string {
  const when = parsedInstant(iso)
  if (!when) return '—'
  return when.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

export function formatDateTimeIST(iso: string): string {
  const when = parsedInstant(iso)
  if (!when) return '—'
  return when.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

/**
 * Human freshness.
 *
 * Null means the source genuinely does not report it — the API's source
 * registry carries no telemetry — so it reads "unknown" rather than a
 * fabricated or sentinel number.
 */
export function formatFreshness(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return 'unknown'
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h} hr ${m} min` : `${h} hr`
}

export function formatPopulation(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

/**
 * Render an ISO timestamp as an age, e.g. "2 min ago".
 *
 * The notification drawer shows when an alert fired. An absolute clock time
 * reads as "is this current?"; an age answers that directly.
 */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 0) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}
