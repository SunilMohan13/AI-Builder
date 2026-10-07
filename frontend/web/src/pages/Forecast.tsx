import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getForecast, getGrid, getHazard } from '../api/regions'
import type { ForecastPoint, HazardPoint } from '../api/regionTypes'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { LiveFailureBanner, NotConfigured, QueryError } from '../components/common/Banners'
import { Missing, Value } from '../components/common/Missing'
import { ProvenanceBadge } from '../components/common/ProvenanceBadge'
import { LoadingState } from '../components/common/States'
import { useRegionClock } from '../hooks/useRegionClock'
import { useRegionQuery } from '../hooks/useRegionQuery'
import { formatDateTime } from '../utils/format'

const NO_QUANTILES = 'the served model gives a point forecast; quantile forecasts are not built yet'

function ModelLine({ p }: { p: { model_version: string; degraded: boolean; degraded_reason: string | null } }) {
  return (
    <p className="text-[11px] text-text-muted">
      Model <span className="font-mono">{p.model_version}</span>
      {p.degraded ? (
        <span className="text-amber-300/90"> · degraded: {p.degraded_reason ?? 'reason not given'}</span>
      ) : (
        ' · not degraded'
      )}
    </p>
  )
}

function HazardRow({ h }: { h: HazardPoint }) {
  return (
    <tr className="border-t border-border/60">
      <td className="py-1 pr-3 font-mono text-[11px]">{h.grid_id}</td>
      <td className="py-1 pr-3 font-mono">
        <Value value={h.score} decimals={2} reason="no hazard score served" />
        <span className="ml-1 text-[10px] text-text-muted">{h.calibrated ? 'probability' : 'rank'}</span>
      </td>
      <td className="py-1 pr-3">
        <Value value={h.threshold_ugm3} unit="µg/m³" reason="no exceedance threshold in the pack" />
      </td>
      <td className="py-1">{h.calibrated ? 'calibrated' : 'not calibrated'}</td>
    </tr>
  )
}

export function Forecast() {
  const { timeZone } = useRegionClock()
  const forecast = useRegionQuery('forecast', getForecast, { refetchMs: 120_000 })
  const hazard = useRegionQuery('hazard', getHazard, { refetchMs: 120_000 })
  const grid = useRegionQuery('grid', getGrid)
  const [chosen, setChosen] = useState<string | null>(null)

  const byCell = useMemo(() => {
    const out = new Map<string, ForecastPoint[]>()
    for (const f of forecast.data?.features ?? []) {
      const list = out.get(f.properties.grid_id) ?? []
      list.push(f.properties)
      out.set(f.properties.grid_id, list)
    }
    for (const list of out.values()) list.sort((a, b) => a.horizon_hours - b.horizon_hours)
    return out
  }, [forecast.data])

  const cellIds = [...byCell.keys()]
  const cell = chosen && byCell.has(chosen) ? chosen : (cellIds[0] ?? null)
  const points = cell ? (byCell.get(cell) ?? []) : []
  const now = grid.data?.features.find((f) => f.properties.grid_id === cell)?.properties.pm25 ?? null
  const hazards = (hazard.data?.features ?? []).map((f) => f.properties)

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Forecast</h1>
        <p className="text-sm text-text-secondary">
          Served PM2.5 forecasts and the 24-hour hazard outlook, with the model that produced each.
        </p>
      </div>
      <LiveFailureBanner />
      <NotConfigured of={forecast.data} />
      <QueryError error={forecast.error} what="Forecast" />

      {forecast.isLoading && <LoadingState message="Loading forecasts…" />}
      {cell && (
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <ProvenanceBadge value="predicted" />
              <label className="text-sm">
                Cell{' '}
                <select
                  value={cell}
                  onChange={(e) => setChosen(e.target.value)}
                  className="rounded border border-border bg-bg-panel px-2 py-0.5 font-mono text-xs"
                >
                  {cellIds.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <span className="text-xs text-text-muted">
              Now: <Value value={now} unit="µg/m³" reason="no served value for this cell" />
            </span>
          </CardHeader>
          <CardBody className="space-y-3">
            {points[0] && <ModelLine p={points[0]} />}
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points.map((p) => ({ h: `+${p.horizon_hours} h`, p50: p.p50 }))}>
                  <CartesianGrid stroke="#1e293b" />
                  <XAxis dataKey="h" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} unit=" µg" />
                  <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1e293b', fontSize: 12 }} />
                  <Line type="monotone" dataKey="p50" stroke="#22d3ee" strokeWidth={2} dot isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <table className="w-full text-xs">
              <thead className="text-left text-text-muted">
                <tr>
                  <th className="py-1">Horizon</th>
                  <th>Valid at</th>
                  <th>P10</th>
                  <th>P50</th>
                  <th>P90</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.horizon_hours} className="border-t border-border/60">
                    <td className="py-1">+{p.horizon_hours} h</td>
                    <td>{formatDateTime(p.valid_at, timeZone)}</td>
                    <td>{p.p10 === null ? <Missing reason={NO_QUANTILES} inline /> : p.p10}</td>
                    <td>
                      <Value value={p.p50} unit="µg/m³" reason="the model produced no value" />
                    </td>
                    <td>{p.p90 === null ? <Missing reason={NO_QUANTILES} inline /> : p.p90}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-text-muted">P10 / P90 “—”: {NO_QUANTILES}.</p>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader className="flex items-center gap-2">
          <ProvenanceBadge value="predicted" />
          <span className="text-sm font-medium">24-hour hazard outlook</span>
        </CardHeader>
        <CardBody>
          <QueryError error={hazard.error} what="Hazard" />
          {hazards[0] && <ModelLine p={hazards[0]} />}
          {hazards.some((h) => !h.calibrated) && (
            <p className="mt-1 text-[11px] text-amber-300/90">
              Not calibrated: a score is a rank for ordering cells, not the chance of exceeding the
              threshold.
            </p>
          )}
          {hazards.length > 0 ? (
            <table className="mt-2 w-full text-xs">
              <thead className="text-left text-text-muted">
                <tr>
                  <th className="py-1">Cell</th>
                  <th>Score</th>
                  <th>Threshold</th>
                  <th>Calibration</th>
                </tr>
              </thead>
              <tbody>
                {hazards.map((h) => (
                  <HazardRow key={h.grid_id} h={h} />
                ))}
              </tbody>
            </table>
          ) : (
            !hazard.isLoading && <Missing reason="no hazard outlook was served for this region" />
          )}
        </CardBody>
      </Card>
    </div>
  )
}
