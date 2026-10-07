import type { FieldStatus } from '../../api/regionTypes'

/** The API's reason for a missing field, if it gave one. */
export function reasonFor(status: FieldStatus[] | undefined, field: string): string | null {
  return status?.find((s) => s.field === field)?.reason ?? null
}

/** "—" for a value the API did not send, always with why. */
export function Missing({ reason, inline = false }: { reason: string | null; inline?: boolean }) {
  const why = reason ?? 'not sent by the API'
  return (
    <span title={why} className="text-text-muted">
      —{inline ? null : <span className="ml-1 text-[11px]">({why})</span>}
    </span>
  )
}

/** A value, or "—" with its reason. */
export function Value({
  value,
  unit,
  reason,
  decimals = 1,
}: {
  value: number | string | null | undefined
  unit?: string
  reason?: string | null
  decimals?: number
}) {
  if (value === null || value === undefined || value === '') return <Missing reason={reason ?? null} />
  const text =
    typeof value === 'number'
      ? value.toLocaleString('en-GB', { maximumFractionDigits: decimals })
      : value
  return (
    <span className="font-mono">
      {text}
      {unit ? <span className="ml-0.5 text-text-muted">{unit}</span> : null}
    </span>
  )
}
