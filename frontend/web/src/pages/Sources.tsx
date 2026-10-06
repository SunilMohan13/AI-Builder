import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { StatusBadge } from '../components/common/Badge'
import { fetchSources } from '../services/sourceService'
import type { SourceHealth } from '../types'
import { formatFreshness, formatDateTimeIST } from '../utils/format'
import { ErrorState } from '../components/common/States'
import { Sparkline } from '../components/charts/Sparkline'
import { useDataMode } from '../context/DataModeContext'
import { FallbackBanner, ModeContextNote } from '../components/common/Provenance'
import { AdvancedOnly } from '../context/ViewLevelContext'
import { ModelRegistryPanel } from '../components/events/ModelRegistryPanel'

function statusVariant(status: SourceHealth['status']) {
  if (status === 'Healthy') return 'success' as const
  if (status === 'Delayed') return 'warning' as const
  // `Registered` is a configuration fact, not a green light. Neutral, so it
  // cannot be misread as a measured all-clear.
  if (status === 'Registered') return 'default' as const
  return 'severe' as const
}

export function Sources() {
  const { mode } = useDataMode()
  const { data: sources = [] } = useQuery({ queryKey: ['sources', mode], queryFn: fetchSources })
  const [selected, setSelected] = useState<SourceHealth | null>(null)

  const hasTelemetry = sources.some(
    (s) => s.freshnessMinutes !== null || s.latencySec !== null || s.recordsToday !== null,
  )
  const delayed = sources.find((s) => s.status === 'Delayed')

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Source Health</h1>
        <p className="text-sm text-text-secondary">Data ingestion observability</p>
        <ModeContextNote className="pt-1" />
        {mode === 'live' && !hasTelemetry && (
          <p className="pt-1 text-xs text-amber-400/80">
            These sources are configured, but no connector run has been persisted yet — so
            freshness and latency read as unknown rather than as a guess.
          </p>
        )}
        {mode === 'live' && hasTelemetry && (
          <p className="pt-1 text-xs text-text-muted">
            Freshness and latency come from the last connector run stored in{' '}
            <code className="font-mono">source_health</code>.
          </p>
        )}
      </div>

      <FallbackBanner />

      {delayed && (
        <ErrorState
          title="Source temporarily unavailable"
          description={`${delayed.name} data is delayed by ${formatFreshness(delayed.freshnessMinutes)}. Predictions continue using available evidence.`}
          action={`Open ${delayed.name} detail`}
          onAction={() => setSelected(delayed)}
        />
      )}

      <Card>
        <CardHeader>
          <span className="text-sm font-medium">Data Sources</span>
        </CardHeader>
        <CardBody className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-4 py-3 font-medium">Source</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Freshness</th>
                <th className="px-4 py-3 font-medium">Quality</th>
                <th className="px-4 py-3 font-medium">Trend</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr
                  key={s.id}
                  tabIndex={0}
                  role="button"
                  aria-label={`View ${s.name} connector detail`}
                  className="cursor-pointer border-b border-border/50 hover:bg-bg-elevated focus:outline-none focus-visible:bg-bg-elevated focus-visible:ring-1 focus-visible:ring-intel"
                  onClick={() => setSelected(s)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelected(s)
                    }
                  }}
                >
                  <td className="px-4 py-3 font-medium">{s.name}</td>
                  <td className="px-4 py-3">
                    <StatusBadge variant={statusVariant(s.status)}>● {s.status}</StatusBadge>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{formatFreshness(s.freshnessMinutes)}</td>
                  <td className="px-4 py-3 font-mono">
                    {s.quality === null ? <span className="text-text-muted">&mdash;</span> : `${s.quality}%`}
                  </td>
                  <td className="px-4 py-3">
                    {/* The sparkline is generated from the quality score. With
                        no quality there is no trend, and drawing one anyway
                        invents a history the source never reported. */}
                    {s.quality === null ? (
                      <span className="text-text-muted">&mdash;</span>
                    ) : (
                      <Sparkline
                        seed={s.id}
                        quality={s.quality}
                        color={s.status === 'Healthy' ? '#22d3ee' : '#f97316'}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>

      {/* Artifact ids, promotion gates and R² are engineering and judging
          material, not operator material. */}
      <AdvancedOnly>
        <ModelRegistryPanel />
      </AdvancedOnly>

      {selected && (
        <div className="fixed inset-x-0 bottom-0 z-40 max-h-[70vh] overflow-y-auto border-t border-border bg-bg-panel shadow-2xl sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-80 sm:border-l sm:border-t-0">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="font-semibold">{selected.name}</h2>
            <button type="button" onClick={() => setSelected(null)} aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-4 p-4 text-sm">
            <div className="flex justify-between">
              <span className="text-text-muted">Records today</span>
              <span className="font-mono">
                {selected.recordsToday === null
                  ? '\u2014'
                  : selected.recordsToday.toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Last ingestion</span>
              <span>
                {selected.lastIngestion ? formatDateTimeIST(selected.lastIngestion) : '\u2014'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Latency</span>
              <span className="font-mono">
                {selected.latencySec === null ? '\u2014' : `${selected.latencySec} sec`}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Error rate</span>
              <span className="font-mono">
                {selected.errorRate === null ? '\u2014' : `${selected.errorRate}%`}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Quality</span>
              <span className="font-mono">
                {selected.quality === null ? '\u2014' : `${selected.quality}%`}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Connector</span>
              <span className="text-xs text-intel">{selected.connector}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
