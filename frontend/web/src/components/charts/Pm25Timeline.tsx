import { Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ComposedChart, ReferenceLine } from 'recharts'
import type { ForecastPoint } from '../../types'

const axisStyle = { fill: '#64748b', fontSize: 10 }

const tooltipStyle = {
  background: '#151d2e',
  border: '1px solid #1e293b',
  borderRadius: 8,
  fontSize: 12,
}

/**
 * Observed history up to now, then the predicted branch. The reference line
 * keeps the observed/predicted boundary explicit.
 */
export function Pm25Timeline({
  history,
  forecast,
  height = 180,
}: {
  history: { hour: number; pm25: number }[]
  forecast: ForecastPoint[]
  height?: number
}) {
  const data = [
    ...history.map((h) => ({ hour: h.hour, observed: h.pm25, predicted: null as number | null })),
    ...forecast.map((f, i) => ({
      hour: f.hour,
      observed: i === 0 ? f.pm25 : null,
      predicted: f.pm25,
    })),
  ]

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <XAxis
            dataKey="hour"
            tick={axisStyle}
            tickFormatter={(h: number) => (h === 0 ? 'Now' : h > 0 ? `+${h}h` : `${h}h`)}
            stroke="#1e293b"
          />
          <YAxis tick={axisStyle} stroke="#1e293b" />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={(h) => (h === 0 ? 'Now' : `${h}h`)} />
          <ReferenceLine x={0} stroke="#334155" strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="observed"
            name="Observed"
            stroke="#f1f5f9"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="predicted"
            name="Predicted"
            stroke="#22d3ee"
            strokeWidth={2}
            strokeDasharray="4 3"
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
