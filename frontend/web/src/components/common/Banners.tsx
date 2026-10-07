import { AlertTriangle, Info } from 'lucide-react'
import type { DataSource, FieldStatus } from '../../api/regionTypes'
import { isNotRecorded } from '../../api/transport'
import { ApiError } from '../../api/client'
import { useDataMode } from '../../context/DataModeContext'
import { useRegion } from '../../context/RegionContext'

/** Endpoints that failed in Live this session. Live never shows recorded data instead. */
export function LiveFailureBanner() {
  const { mode, fallbacks } = useDataMode()
  if (mode !== 'live' || fallbacks.length === 0) return null
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>
        Live requests failing:{' '}
        {fallbacks.map((f) => `${f.endpoint} (${f.reason})`).join(', ')}. Nothing is substituted;
        the affected panels are empty.
      </span>
    </div>
  )
}

interface MaybeConfigured {
  data_source?: DataSource
  status?: string
  field_status?: FieldStatus[]
  region_id?: string
}

/** The not-configured reason in either shape the API uses, or `null` when data is served. */
export function notConfigured(body: MaybeConfigured | undefined | null): DataSource | null {
  if (!body) return null
  if (body.data_source?.kind === 'not_configured') return body.data_source
  if (body.status === 'not_configured') {
    return {
      kind: 'not_configured',
      region_id: body.region_id ?? '',
      reason: body.field_status?.[0]?.reason,
    }
  }
  return null
}

/** "Not configured" for a region with no cycle, with the API's reason and what the pack says. */
export function NotConfigured({ of }: { of: MaybeConfigured | undefined | null }) {
  const { region } = useRegion()
  const { mode } = useDataMode()
  const source = notConfigured(of)
  if (!source) return null
  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-bg-panel px-3 py-2 text-xs text-text-secondary">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-intel" />
      <span>
        <span className="font-medium text-text-primary">Not configured</span> —{' '}
        {source.reason ?? 'no cycle has written a snapshot for this region yet'}.
        {region ? ` ${region.display_name} is onboarded (pack v${region.pack_version}); ` : ' '}
        {mode === 'demo'
          ? 'the Demo recording has no cycle for it because no replay fixtures exist for this region.'
          : 'run a cycle for it to see data here.'}
      </span>
    </div>
  )
}

/** A query error, worded for the mode it happened in. */
export function QueryError({ error, what }: { error: unknown; what: string }) {
  if (!error) return null
  const reason = error instanceof ApiError ? error.reason : 'unexpected error'
  const demoGap = isNotRecorded(error)
  return (
    <div
      className={`rounded-md border px-3 py-2 text-xs ${
        demoGap
          ? 'border-border bg-bg-panel text-text-secondary'
          : 'border-amber-500/30 bg-amber-500/5 text-amber-200'
      }`}
    >
      {what}: {reason}
    </div>
  )
}
