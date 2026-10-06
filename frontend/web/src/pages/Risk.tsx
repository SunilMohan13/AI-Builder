import { useQuery } from '@tanstack/react-query'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { ScientificBadge, StatusBadge } from '../components/common/Badge'
import { KpiStat } from '../components/common/KpiStat'
import { AeroMap } from '../components/map/AeroMap'
import { fetchRiskAreas, fetchTotalExposure } from '../services/riskService'
import { PopulationRiskBars } from '../components/charts/PopulationRiskBars'
import { formatPopulation } from '../utils/format'
import { useDataMode } from '../context/DataModeContext'
import { FallbackBanner, MaybeValue, ModeContextNote } from '../components/common/Provenance'

export function Risk() {
  const { mode } = useDataMode()
  const { data: areas = [] } = useQuery({
    queryKey: ['riskAreas', mode],
    queryFn: fetchRiskAreas,
  })
  const { data: total } = useQuery({
    queryKey: ['totalExposure', mode],
    queryFn: fetchTotalExposure,
  })
  const isLive = mode === 'live'

  const riskVariant = (risk: string) => {
    if (risk === 'HIGH' || risk === 'SEVERE') return 'severe' as const
    if (risk === 'MEDIUM') return 'warning' as const
    return 'default' as const
  }

  return (
    <div className="space-y-4 p-4">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">Population Exposure</h1>
        <p className="text-sm text-text-secondary">Who may be affected by current pollution</p>
        <ModeContextNote />
      </div>

      <FallbackBanner />

      <Card>
        <CardBody className="flex items-center justify-between">
          <div>
            <ScientificBadge label="PREDICTED" />
            {total !== null && total !== undefined ? (
              <KpiStat
                label="People potentially exposed"
                value={total / 1_000_000}
                unit="M"
                className="mt-2"
              />
            ) : (
              <div className="mt-2">
                <p className="font-mono text-3xl font-bold text-text-muted">&mdash;</p>
                <p className="text-xs text-text-muted">People potentially exposed</p>
                <p className="mt-2 max-w-md text-xs text-amber-400/80">
                  No population cells were returned, so exposure cannot be summed.
                </p>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      <Card className="overflow-hidden">
        <CardBody className="h-[360px] p-0">
          {/* `embedded` suppresses the full map chrome. Without it the
              display panel and scenario lab cover a map this short. */}
          <AeroMap
            embedded
            showControls={false}
            showTimeline={false}
            showGlobeBar={false}
            forceLayers={{ population: true, pollution: true, fires: false, wind: false }}
            className="h-full"
          />
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <span className="text-sm font-medium">Most Affected Areas</span>
          </CardHeader>
          <CardBody>
            <ol className="space-y-2">
              {areas.map((a) => (
                <li
                  key={a.rank}
                  className="flex items-center justify-between rounded border border-border px-3 py-2"
                >
                  <span className="text-sm">
                    {a.rank}. {a.name}
                  </span>
                  <div className="flex items-center gap-3">
                    <span
                      className="font-mono text-xs text-text-muted"
                      title="Population in the affected area"
                    >
                      {formatPopulation(a.population)}
                    </span>
                    <StatusBadge variant={riskVariant(a.risk)}>{a.risk}</StatusBadge>
                  </div>
                </li>
              ))}
            </ol>
            <div className="mt-4 border-t border-border pt-4">
              <PopulationRiskBars areas={areas} />
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <span className="text-sm font-medium">Sensitive Populations</span>
          </CardHeader>
          <CardBody>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: 'Children', field: 'children' },
                { label: 'Elderly', field: 'elderly' },
                { label: 'Hospitals', field: 'hospitals' },
                { label: 'Schools', field: 'schools' },
              ].map((item) => (
                <div key={item.label} className="rounded border border-border p-3 text-center">
                  <p className="text-2xl font-mono font-bold">
                    {isLive ? (
                      <MaybeValue
                        field={item.field}
                        unavailable={['children', 'elderly', 'hospitals', 'schools']}
                        reason="The API does not serve sensitive-population counts."
                        value="—"
                      />
                    ) : (
                      { Children: '840K', Elderly: '620K', Hospitals: '142', Schools: '1,240' }[
                        item.label
                      ]
                    )}
                  </p>
                  <p className="text-xs text-text-muted">{item.label}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-text-muted">
              Exposure estimates combine predicted PM2.5 severity with gridded population data.
            </p>
            {isLive && (
              <p className="mt-2 text-xs text-amber-400/80">
                Sensitive-population counts are not on the API, so they render as unavailable.
                Ranked areas and the exposure total above are live from{' '}
                <code className="font-mono">/api/v1/risk/areas</code> — its population layer ships
                licensed <code className="font-mono">replace-before-production</code>.
              </p>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
