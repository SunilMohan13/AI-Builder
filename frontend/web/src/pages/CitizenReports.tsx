import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { getCitizenReport, getCitizenReports } from '../api/regions'
import type { CitizenReportDetail } from '../api/regionTypes'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { LiveFailureBanner, QueryError } from '../components/common/Banners'
import { Missing } from '../components/common/Missing'
import { ProvenanceBadge } from '../components/common/ProvenanceBadge'
import { LoadingState } from '../components/common/States'
import { CitizenUploadForm } from '../components/citizen/CitizenUploadForm'
import { useRegion } from '../context/RegionContext'
import { useRegionClock } from '../hooks/useRegionClock'
import { useRegionQuery } from '../hooks/useRegionQuery'
import { formatDateTime, humanise } from '../utils/format'

function ReportDetail({ report }: { report: CitizenReportDetail }) {
  const { timeZone } = useRegionClock()
  const analysis = report.analysis ?? null
  const obs = analysis?.observation ?? null
  const corroboration = analysis?.corroboration ?? null
  const geo = analysis?.geo_trust ?? null
  return (
    <div className="space-y-4 text-xs">
      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1">
        <dt className="text-text-muted">Status</dt>
        <dd>{report.status}</dd>
        <dt className="text-text-muted">Created</dt>
        <dd>{formatDateTime(report.created_at, timeZone)}</dd>
        <dt className="text-text-muted">Reported as</dt>
        <dd>{report.observation_type}</dd>
        <dt className="text-text-muted">Notes</dt>
        <dd>{report.notes ?? '—'}</dd>
        <dt className="text-text-muted">Moderation</dt>
        <dd>
          {report.moderation}
          {report.moderated_class ? ` · set to ${report.moderated_class}` : ''}
        </dd>
        <dt className="text-text-muted">Decision</dt>
        <dd>{analysis ? humanise(analysis.decision) : <Missing reason="not analysed yet" />}</dd>
      </dl>

      <section>
        <p className="mb-1 flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">
          What the photo shows <ProvenanceBadge value={obs?.provenance_class ?? 'ai_observation'} />
        </p>
        {obs ? (
          <div className="space-y-1">
            <p>
              <span className="font-medium">{humanise(obs.visual_class)}</span> · certainty {obs.visual_certainty} ·
              image quality {obs.image_quality}
            </p>
            <p className="text-text-secondary">{obs.scene_summary}</p>
            <p className="text-text-muted">
              Likely source type: {humanise(obs.likely_source_type)}
              {obs.possible_confusers.length ? ` · could be confused with ${obs.possible_confusers.join(', ')}` : ''}
            </p>
            <p className="text-[10px] text-text-muted">
              Observer {obs.observer_version}. An AI observation of one photo; it counts only when corroborated.
            </p>
          </div>
        ) : (
          <Missing reason="no visual observation (not analysed, or the observer was unavailable)" />
        )}
      </section>

      <section>
        <p className="mb-1 flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">
          Corroboration {corroboration && <ProvenanceBadge value={corroboration.provenance_class} />}
        </p>
        {corroboration ? (
          <>
            <p>
              Level <span className="font-medium">{corroboration.level}</span> · score {corroboration.score} ·{' '}
              {corroboration.method_version}
            </p>
            <table className="mt-1 w-full">
              <tbody>
                {corroboration.signals.map((s) => (
                  <tr key={s.signal} className="border-t border-border/60 align-top">
                    <td className={`py-1 pr-2 ${s.supports ? 'text-emerald-300' : 'text-text-muted'}`}>
                      {s.supports ? '✓' : '·'} {humanise(s.signal)}
                    </td>
                    <td className="py-1 pr-2 font-mono text-text-muted">w {s.weight}</td>
                    <td className="py-1 text-text-secondary">{s.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <Missing reason="not corroborated yet" />
        )}
      </section>

      <section>
        <p className="mb-1 font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">Location trust</p>
        {geo ? (
          <p>
            {geo.level} · score {geo.score} ·{' '}
            {Object.entries(geo.components)
              .map(([k, v]) => `${humanise(k)} ${v}`)
              .join(' · ')}
          </p>
        ) : (
          <Missing reason="not assessed yet" />
        )}
      </section>
      {analysis && analysis.degraded_reasons.length > 0 && (
        <p className="text-amber-300/90">Degraded: {analysis.degraded_reasons.map(humanise).join('; ')}</p>
      )}
    </div>
  )
}

export function CitizenReports() {
  const { region } = useRegion()
  const { timeZone } = useRegionClock()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const reports = useRegionQuery('citizen', getCitizenReports, { refetchMs: 30_000 })
  const items = reports.data?.items ?? []
  const selected = params.get('report') ?? items[0]?.report_id ?? null
  const detail = useRegionQuery('citizen-report', (t) => getCitizenReport(t, selected!), {
    key: [selected],
    enabled: selected !== null,
  })

  const choose = (id: string) =>
    setParams((p) => {
      const next = new URLSearchParams(p)
      next.set('report', id)
      return next
    })

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Citizen reports</h1>
        <p className="text-sm text-text-secondary">
          Photos from the ground. A vision model describes each photo; deterministic checks decide
          whether stations, fires and wind back it up. Operators moderate before anything is public.
        </p>
      </div>
      <LiveFailureBanner />
      {region && (
        <CitizenUploadForm
          key={region.region_id}
          region={region}
          onSubmitted={(id) => {
            void queryClient.invalidateQueries({ queryKey: ['citizen'] })
            choose(id)
          }}
        />
      )}
      <QueryError error={reports.error} what="Reports" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <Card>
          <CardHeader>
            <p className="text-sm font-medium">
              {reports.data ? `${reports.data.total} report(s), last ${reports.data.days} days` : 'Reports'}
            </p>
          </CardHeader>
          <CardBody className="p-0">
            {reports.isLoading && <LoadingState message="Loading reports…" />}
            <ul className="divide-y divide-border">
              {items.map((r) => (
                <li key={r.report_id}>
                  <button
                    type="button"
                    onClick={() => choose(r.report_id)}
                    className={`w-full px-4 py-3 text-left text-xs hover:bg-bg-elevated ${r.report_id === selected ? 'bg-intel/5' : ''}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{r.visual_class ? humanise(r.visual_class) : '—'}</span>
                      <ProvenanceBadge value={r.visual_class_provenance} />
                      <span className="text-text-muted">{r.status}</span>
                    </div>
                    <p className="mt-0.5 text-text-muted">
                      corroboration {r.corroboration ?? '—'} · moderation {r.moderation ?? '—'} ·{' '}
                      {formatDateTime(r.created_at, timeZone)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
            {reports.data && items.length === 0 && (
              <p className="px-4 py-6 text-sm text-text-muted">No reports in this region yet.</p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <p className="break-all font-mono text-xs text-text-muted">{selected ?? 'No report selected'}</p>
          </CardHeader>
          <CardBody>
            {detail.isLoading && <LoadingState message="Loading report…" />}
            <QueryError error={detail.error} what="Report" />
            {detail.data && <ReportDetail report={detail.data} />}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
