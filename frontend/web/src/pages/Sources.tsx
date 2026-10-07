import { Card, CardBody, CardHeader } from '../components/common/Card'
import { LiveFailureBanner } from '../components/common/Banners'
import { Missing } from '../components/common/Missing'
import { LoadingState } from '../components/common/States'
import { useRegion } from '../context/RegionContext'
import { useRegionClock } from '../hooks/useRegionClock'
import { formatDateTime, humanise, relativeTime } from '../utils/format'

const STATE_STYLE: Record<string, string> = {
  healthy: 'text-emerald-300',
  degraded: 'text-amber-300',
  failing: 'text-red-400',
  not_configured: 'text-text-muted',
  disabled: 'text-text-muted',
}

const DOMAIN_HINT: Record<string, string> = {
  display: 'Shown on the map for this region',
  source: 'Read over the wider source domain (e.g. upwind fires, wind)',
}

export function Sources() {
  const { region } = useRegion()
  const { now, timeZone } = useRegionClock()
  const sources = region?.sources

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Data sources</h1>
        <p className="text-sm text-text-secondary">
          Connector health for {region?.display_name ?? 'this region'} as the latest cycle recorded
          it. A source with no key is “not configured” with zero records, never a fixture.
        </p>
      </div>
      <LiveFailureBanner />
      {region && (
        <Card>
          <CardHeader>
            <p className="text-sm font-medium">Region pack</p>
          </CardHeader>
          <CardBody className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            <p>
              <span className="text-text-muted">Pack version</span> {region.pack_version}
            </p>
            <p>
              <span className="text-text-muted">Ground truth</span> {humanise(region.ground_truth)}
            </p>
            <p>
              <span className="text-text-muted">Timezone</span> {region.timezone}
            </p>
            <p>
              <span className="text-text-muted">AQI standard</span> {region.aqi_standard.name} (
              {region.aqi_standard.status})
            </p>
            <p className="sm:col-span-2">
              <span className="text-text-muted">Hazards</span>{' '}
              {region.hazards.map((h) => h.display_name).join(' · ')}
            </p>
          </CardBody>
        </Card>
      )}
      {!sources && <LoadingState message="Loading source health…" />}
      {sources && sources.length === 0 && (
        <p className="text-sm text-text-muted">No sources are configured in this pack.</p>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(sources ?? []).map((s) => (
          <Card key={s.source_id}>
            <CardBody className="space-y-1 text-xs">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">{s.source_id}</p>
                <span className={STATE_STYLE[s.state] ?? 'text-text-secondary'}>{humanise(s.state)}</span>
              </div>
              <p className="text-text-muted" title={DOMAIN_HINT[s.domain]}>
                Domain: {s.domain}
                {s.enabled ? '' : ' · disabled'}
              </p>
              <p>
                Records this cycle: {s.records === null ? <Missing reason="not reported" inline /> : s.records}
              </p>
              <p>
                Last success:{' '}
                {s.last_success_at ? (
                  <span title={formatDateTime(s.last_success_at, timeZone)}>{relativeTime(s.last_success_at, now)}</span>
                ) : (
                  <Missing reason={s.reason ?? 'never succeeded'} />
                )}
              </p>
              {s.reason && s.last_success_at && <p className="text-amber-300/90">{s.reason}</p>}
              {s.secret_ref && (
                <p className="text-text-muted">
                  Key: <span className="font-mono">{s.secret_ref}</span> (a reference; values are never sent)
                </p>
              )}
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  )
}
