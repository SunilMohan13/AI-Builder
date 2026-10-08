/**
 * Formatting in the selected region's timezone. No locale or zone is assumed:
 * every caller passes the region's IANA timezone from its pack.
 */

function parsedInstant(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const when = new Date(iso)
  return Number.isNaN(when.getTime()) ? null : when
}

/** Short zone name in that zone, e.g. "IST", "SGT", "AEST". */
export function zoneAbbreviation(timeZone: string, at: Date = new Date()): string {
  const part = new Intl.DateTimeFormat('en-GB', { timeZone, timeZoneName: 'short' })
    .formatToParts(at)
    .find((p) => p.type === 'timeZoneName')
  return part?.value ?? timeZone
}

export function formatDateTime(iso: string | null | undefined, timeZone: string): string {
  const when = parsedInstant(iso)
  if (!when) return '—'
  const text = when.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone,
  })
  return `${text} ${zoneAbbreviation(timeZone, when)}`
}

/** "12 min ago", measured from `now` (the recording's clock in Demo). */
export function relativeTime(iso: string | null | undefined, now: Date): string {
  const then = parsedInstant(iso)
  if (!then) return '—'
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000)
  if (seconds < 0) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

export function humanise(key: string | null | undefined): string {
  if (!key) return '—'
  return key.replace(/_/g, ' ')
}
