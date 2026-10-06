import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { StatusBadge, ScientificBadge } from '../components/common/Badge'
import { fetchCitizenStats, CITIZEN_LIVE_CAVEAT } from '../services/citizenService'
import { CitizenReportMap } from '../components/map/CitizenReportMap'
import { CitizenUploadForm } from '../components/events/CitizenUploadForm'
import type { CitizenReport } from '../types'
import { LiveCaveatNotice } from '../components/common/DemoOnlyNotice'
import { FallbackBanner } from '../components/common/Provenance'
import { useDataMode } from '../context/DataModeContext'

export function CitizenReports() {
  const { mode } = useDataMode()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const highlightId = searchParams.get('highlight')
  const { data } = useQuery({ queryKey: ['citizenStats', mode], queryFn: fetchCitizenStats })
  const [selected, setSelected] = useState<CitizenReport | null>(null)
  const [previews, setPreviews] = useState<Record<string, string>>({})

  const reports = data?.reports ?? []

  useEffect(() => {
    if (!highlightId || reports.length === 0) return
    const match = reports.find((r) => r.id === highlightId)
    if (match) setSelected(match)
  }, [highlightId, reports])

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Citizen Intelligence</h1>
        <p className="text-sm text-text-secondary">Crowdsourced environmental observations</p>
      </div>

      <LiveCaveatNotice reason={CITIZEN_LIVE_CAVEAT} />
      <FallbackBanner />

      <CitizenUploadForm
        onSubmitted={(report) => {
          if (report.photoUrl) {
            setPreviews((current) => ({ ...current, [report.id]: report.photoUrl! }))
          }
          setSelected(report)
          void queryClient.invalidateQueries({ queryKey: ['citizenStats', mode] })
        }}
      />

      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardBody className="text-center">
            <p className="font-mono text-2xl font-bold">{data?.totalToday ?? 0}</p>
            <p className="text-xs text-text-muted">reports today</p>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="text-center">
            <p className="font-mono text-2xl font-bold">{data?.awaiting ?? 0}</p>
            <p className="text-xs text-text-muted">awaiting verification</p>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="text-center">
            <p className="font-mono text-2xl font-bold">{data?.correlated ?? 0}</p>
            <p className="text-xs text-text-muted">correlated with events</p>
          </CardBody>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader>
          <span className="text-sm font-medium">Report Locations</span>
        </CardHeader>
        <CardBody className="h-[300px] p-0">
          <CitizenReportMap
            reports={reports}
            selectedId={selected?.id}
            onSelect={setSelected}
          />
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <span className="text-sm font-medium">Recent Reports</span>
          </CardHeader>
          <CardBody className="space-y-2">
            {reports.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setSelected(r)}
                className={`w-full rounded-md border p-3 text-left transition-colors ${
                  selected?.id === r.id || r.id === highlightId
                    ? 'border-intel/40 bg-intel/5 ring-1 ring-intel/30'
                    : 'border-border hover:bg-bg-elevated'
                }`}
              >
                <p className="text-sm font-medium">{r.type}</p>
                <p className="text-xs text-text-muted">
                  {r.location} · {new Date(r.reportedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                </p>
              </button>
            ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <span className="text-sm font-medium">Report Detail</span>
            <ScientificBadge label="OBSERVED" />
          </CardHeader>
          <CardBody>
            {selected ? (
              <div className="space-y-3 text-sm">
                {(previews[selected.id] || selected.photoUrl) && (
                  <img
                    src={previews[selected.id] || selected.photoUrl}
                    alt=""
                    className="h-40 w-full rounded-md object-cover"
                  />
                )}
                <div>
                  <p className="text-text-muted">Location</p>
                  <p className="font-medium">{selected.location}</p>
                </div>
                <div>
                  <p className="text-text-muted">Reported</p>
                  <p>
                    {new Date(selected.reportedAt).toLocaleTimeString('en-IN', {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                </div>
                <div>
                  <p className="text-text-muted">Type</p>
                  <p>{selected.type}</p>
                </div>
                <div>
                  <p className="text-text-muted">Classification</p>
                  <p>{selected.classification}</p>
                </div>
                {selected.mediaUri ? (
                  <div>
                    <p className="text-text-muted">Stored photo</p>
                    <p className="break-all font-mono text-[11px] text-text-secondary">{selected.mediaUri}</p>
                  </div>
                ) : null}
                {selected.relatedEventId ? (
                  <div>
                    <p className="text-text-muted">Linked event</p>
                    <p className="text-intel">
                      {selected.relatedEventId} · corroboration only
                    </p>
                  </div>
                ) : null}
                <div>
                  <p className="text-text-muted">Status</p>
                  <StatusBadge variant={selected.status === 'CORROBORATED' ? 'success' : 'warning'}>
                    {selected.status}
                  </StatusBadge>
                </div>
                <p className="text-xs text-text-muted">
                  Citizen reports corroborate events; a single photo alone does not create high-severity alerts.
                </p>
              </div>
            ) : (
              <p className="text-sm text-text-muted">Select a report to view details.</p>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
