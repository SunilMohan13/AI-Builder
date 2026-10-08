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

const NO_QUANTILES = 'quantile forecasts are not built yet; this model serves a point value'

function pointPm25(p: ForecastPoint): number | null {
  if (typeof p.p50 === 'number') return p.p50
  if (typeof p.pm25 === 'number') return p.pm25
  return null
}

/** Issue time plus the horizon, when the row did not carry its own valid time. */
function validAt(p: ForecastPoint): string | null {
  if (p.valid_at) return p.valid_at
  if (!p.generated_at) return null
  const issued = Date.parse(p.generated_at)
  if (Number.isNaN(issued)) return null
  return new Date(issued + p.horizon_hours * 3_600_000).toISOString()
}

function ModelLine({
  p,
}: {
  p: { model_version: string; degraded?: boolean; degraded_reason?: string | null }
}) {
  const status =
    p.degraded === true
      ? `degraded: ${p.degraded_reason ?? 'reason not given'}`
      : p.degraded === false
        ? 'not degraded'
        : 'degraded status not served'
  return (
    <p className="text-[11px] text-text-muted">
      Model <span className="font-mono">{p.model_version}</span>
      {p.degraded === true ? (
        <span className="text-amber-300/90"> · {status}</span>
      ) : (
        ` · ${status}`
      )}
    </p>
  )
}

function HazardRow({ h }: { h: HazardPoint }) {
  return (
    <tr className="border-t border-border/60">
      <td className="py-1 pr-3 font-mono text-[11px]">{h.grid_id}</td>
      <td className="py-1 pr-3 font-mono text-[11px]">+{h.horizon_hours} h</td>
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

  const series = useMemo(() => {
    const groups = new Map<string, ForecastPoint[]>()
    for (const feature of forecast.data?.features ?? []) {
      const point = feature.properties
      // Advection moves the plume to a new cell at each horizon, so a cell
      // only ever holds one hour. The series is the event.
      const key = point.event_id ? `event:${point.event_id}` : `cell:${point.grid_id}`
      const list = groups.get(key) ?? []
      list.push(point)
      groups.set(key, list)
    }
    const out = [...groups.entries()].map(([key, points]) => {
      points.sort((a, b) => a.horizon_hours - b.horizon_hours || a.grid_id.localeCompare(b.grid_id))
      const origin = points.find((p) => p.horizon_hours === 0) ?? points[0]
      const label = origin.event_id ? `${origin.event_id} · ${origin.grid_id}` : origin.grid_id
      return { key, label, points }
    })
    out.sort((a, b) => {
      const stamp = (points: ForecastPoint[]) => points[0]?.generated_at ?? points[0]?.valid_at ?? ''
      return stamp(b.points).localeCompare(stamp(a.points))
    })
    return out
  }, [forecast.data])

  const selected = chosen && series.some((s) => s.key === chosen) ? chosen : (series[0]?.key ?? null)
  const points = series.find((s) => s.key === selected)?.points ?? []
  const origin = points.find((p) => p.horizon_hours === 0) ?? points[0]
  const chartRows = points.map((p, i) => {
    const sharedHorizon = points.some((q, j) => j !== i && q.horizon_hours === p.horizon_hours)
    const label = sharedHorizon ? `+${p.horizon_hours} h · ${p.grid_id.slice(0, 9)}` : `+${p.horizon_hours} h`
    return { label, pm25: pointPm25(p) }
  })
  const hasPoint = chartRows.some((row) => row.pm25 !== null)
  const moves = new Set(points.map((p) => p.grid_id)).size > 1
  const now = grid.data?.features.find((f) => f.properties.grid_id === origin?.grid_id)?.properties.pm25 ?? null
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
      {selected && (
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <ProvenanceBadge value="predicted" />
              <label className="text-sm">
                Forecast{' '}
                <select
                  value={selected}
                  onChange={(e) => setChosen(e.target.value)}
                  className="max-w-[28rem] rounded border border-border bg-bg-panel px-2 py-0.5 font-mono text-xs"
                >
                  {series.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <span className="text-xs text-text-muted">
              Now at origin:{' '}
              <Value value={now} unit="µg/m³" reason="no served value for the origin cell" />
            </span>
          </CardHeader>
          <CardBody className="space-y-3">
            {points[0] && <ModelLine p={points[0]} />}
            {moves && (
              <p className="text-[11px] text-text-muted">
                Each horizon is the cell the advection model moved this plume to, not a fixed station.
              </p>
            )}
            {hasPoint ? (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartRows}>
                    <CartesianGrid stroke="#1e293b" />
                    <XAxis dataKey="label" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={11} width={48} />
                    <Tooltip
                      contentStyle={{ background: '#111827', border: '1px solid #1e293b', fontSize: 12 }}
                      formatter={(value) => [`${value} µg/m³`, 'PM2.5']}
                    />
                    <Line
                      type="monotone"
                      dataKey="pm25"
                      name="PM2.5"
                      stroke="#22d3ee"
                      strokeWidth={2}
                      dot
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <Missing reason="no point forecast was served for this series" />
            )}
            <table className="w-full text-xs">
              <thead className="text-left text-text-muted">
                <tr>
                  <th className="py-1">Horizon</th>
                  <th>Cell</th>
                  <th>Valid at</th>
                  <th>PM2.5</th>
                  <th>P10</th>
                  <th>P90</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p, i) => (
                  <tr
                    key={`${p.event_id ?? ''}:${p.grid_id}:${p.horizon_hours}:${p.valid_at ?? p.generated_at ?? ''}:${i}`}
                    className="border-t border-border/60"
                  >
                    <td className="py-1">+{p.horizon_hours} h</td>
                    <td className="font-mono text-[11px]">{p.grid_id}</td>
                    <td>
                      {validAt(p) ? (
                        formatDateTime(validAt(p), timeZone)
                      ) : (
                        <Missing reason="valid time was not served" inline />
                      )}
                    </td>
                    <td>
                      <Value value={pointPm25(p)} unit="µg/m³" reason="no point forecast served" />
                    </td>
                    <td>
                      {typeof p.p10 === 'number' ? p.p10 : <Missing reason={NO_QUANTILES} inline />}
                    </td>
                    <td>
                      {typeof p.p90 === 'number' ? p.p90 : <Missing reason={NO_QUANTILES} inline />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-text-muted">
              PM2.5 is the served point forecast. P10 and P90 stay “—” until a quantile model sends them.
              When a row has an issue time and no valid time, valid time is the issue time plus the horizon.
            </p>
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
                  <th>Horizon</th>
                  <th>Score</th>
                  <th>Threshold</th>
                  <th>Calibration</th>
                </tr>
              </thead>
              <tbody>
                {hazards.map((h, i) => (
                  <HazardRow
                    key={`${h.grid_id}:${h.horizon_hours}:${h.model_version}:${i}`}
                    h={h}
                  />
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
