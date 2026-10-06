import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { PopulationRiskArea } from '../../types'

const riskColor: Record<PopulationRiskArea['risk'], string> = {
  LOW: '#4ade80',
  MEDIUM: '#facc15',
  HIGH: '#f97316',
  SEVERE: '#dc2626',
}

export function PopulationRiskBars({
  areas,
  height = 200,
}: {
  areas: PopulationRiskArea[]
  height?: number
}) {
  const data = areas.map((a) => ({ name: a.name, population: a.population, risk: a.risk }))

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, bottom: 4, left: 12 }}>
          <XAxis type="number" tick={{ fill: '#64748b', fontSize: 10 }} stroke="#1e293b" />
          <YAxis
            type="category"
            dataKey="name"
            width={80}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            stroke="#1e293b"
          />
          <Tooltip
            cursor={{ fill: 'rgba(148,163,184,0.08)' }}
            contentStyle={{
              background: '#151d2e',
              border: '1px solid #1e293b',
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(value) => [Number(value).toLocaleString('en-IN'), 'People exposed']}
          />
          <Bar dataKey="population" radius={[0, 3, 3, 0]}>
            {data.map((d) => (
              <Cell key={d.name} fill={riskColor[d.risk]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
