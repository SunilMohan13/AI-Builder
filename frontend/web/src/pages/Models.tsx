import { getEvaluation, getModels } from '../api/regions'
import type { EvaluationRun } from '../api/regionTypes'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { LiveFailureBanner, QueryError } from '../components/common/Banners'
import { Missing, reasonFor } from '../components/common/Missing'
import { LoadingState } from '../components/common/States'
import { useRegionQuery } from '../hooks/useRegionQuery'
import { humanise } from '../utils/format'

function RunCard({ run }: { run: EvaluationRun }) {
  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">{humanise(run.family)}</p>
          <p className="font-mono text-[11px] text-text-muted">
            {run.model_version} · run {run.run_id}
          </p>
        </div>
        <span className={run.passed ? 'text-emerald-300' : 'text-amber-300'}>
          {run.passed ? 'passed the gate' : 'did not pass the gate'}
        </span>
      </CardHeader>
      <CardBody className="p-0">
        <table className="w-full text-xs">
          <thead className="text-left text-text-muted">
            <tr>
              <th className="px-4 py-1">Split</th>
              <th>Group</th>
              <th>Subject</th>
              <th>Metric</th>
              <th>Value</th>
              <th className="pr-4">Gate</th>
            </tr>
          </thead>
          <tbody>
            {run.metrics.map((m, i) => (
              <tr key={i} className="border-t border-border/60">
                <td className="px-4 py-1">{m.strategy ?? '—'}</td>
                <td>{m.group ?? '—'}</td>
                <td>{m.subject ?? '—'}</td>
                <td className="font-mono">{m.metric ?? '—'}</td>
                <td className="font-mono">{m.value === null ? '—' : m.value}</td>
                <td className={`pr-4 ${m.passed ? 'text-emerald-300' : 'text-text-muted'}`}>{m.passed ? 'pass' : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  )
}

export function Models() {
  const models = useRegionQuery('models', getModels)
  const evaluation = useRegionQuery('ml-evaluation', getEvaluation)
  const runs = evaluation.data?.items ?? []

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Models</h1>
        <p className="text-sm text-text-secondary">
          What the latest cycle served for this region, and what each training run measured on
          held-out time, space or season splits. A model that did not beat its baseline is not
          promoted; the baseline serves and is labelled degraded.
        </p>
      </div>
      <LiveFailureBanner />

      <Card>
        <CardHeader>
          <p className="text-sm font-medium">Served this cycle</p>
        </CardHeader>
        <CardBody className="p-0">
          {models.isLoading && <LoadingState message="Loading served models…" />}
          <QueryError error={models.error} what="Models" />
          {models.data && models.data.items.length === 0 && (
            <div className="px-4 py-3 text-xs">
              <Missing reason={reasonFor(models.data.field_status, 'items')} />
            </div>
          )}
          {models.data && models.data.items.length > 0 && (
            <table className="w-full text-xs">
              <thead className="text-left text-text-muted">
                <tr>
                  <th className="px-4 py-1">Family</th>
                  <th>Version</th>
                  <th>Features</th>
                  <th>Status</th>
                  <th className="pr-4">Calibrated</th>
                </tr>
              </thead>
              <tbody>
                {models.data.items.map((m) => (
                  <tr key={m.family} className="border-t border-border/60 align-top">
                    <td className="px-4 py-1.5">{humanise(m.family)}</td>
                    <td className="font-mono">{m.model_version}</td>
                    <td className="font-mono">{m.feature_version ?? <Missing reason="a baseline uses no feature set" inline />}</td>
                    <td className={m.degraded ? 'text-amber-300/90' : 'text-emerald-300'}>
                      {m.degraded ? `degraded: ${m.degraded_reason ?? 'reason not given'}` : 'promoted'}
                    </td>
                    <td className="pr-4">{m.calibrated ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>

      <div className="space-y-3">
        <h2 className="text-sm font-medium">Evaluation runs</h2>
        {evaluation.isLoading && <LoadingState message="Loading evaluation…" />}
        <QueryError error={evaluation.error} what="Evaluation" />
        {evaluation.data && runs.length === 0 && (
          <p className="text-xs">
            <Missing reason={reasonFor(evaluation.data.field_status, 'items')} />
          </p>
        )}
        {runs.map((run) => (
          <RunCard key={`${run.family}-${run.run_id}`} run={run} />
        ))}
      </div>
    </div>
  )
}
