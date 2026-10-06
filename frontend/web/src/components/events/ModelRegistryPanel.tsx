import { useQuery } from '@tanstack/react-query'
import { Ban, CheckCircle2, CircleDot, FlaskConical } from 'lucide-react'
import { Card, CardBody, CardHeader } from '../common/Card'
import { fetchModelCatalog } from '../../services/hazardService'
import { useDataMode } from '../../context/DataModeContext'
import type { ModelCatalogEntry } from '../../types'
import { cn } from '../../utils/cn'

/**
 * What is actually serving, and what is not.
 *
 * The promotion gate withholds four of six trained models, and the reasons
 * are the most informative thing the ML platform produces. A dashboard that
 * showed six green models would be the opposite of what this system is for,
 * so the gate failures are rendered as first-class content rather than
 * hidden behind a status dot.
 */
export function ModelRegistryPanel({ className }: { className?: string }) {
  const { mode } = useDataMode()
  const { data: models = [] } = useQuery({
    queryKey: ['models', mode],
    queryFn: fetchModelCatalog,
  })

  const serving = models.filter((m) => m.stage === 'PRODUCTION')
  const withheld = models.filter((m) => m.gateFailures.length > 0)

  return (
    <Card className={className}>
      <CardHeader className="flex flex-wrap items-center gap-2">
        <FlaskConical className="h-4 w-4 text-intel" />
        <span className="text-sm font-medium">Model Registry</span>
        <span className="text-xs text-text-muted">
          {serving.length} serving · {withheld.length} withheld by the promotion gate
        </span>
      </CardHeader>
      <CardBody className="space-y-2">
        {models.map((model) => (
          <ModelRow key={model.modelId} model={model} />
        ))}
        <p className="border-t border-border pt-3 text-xs text-text-muted">
          A model is refused promotion when it cannot beat its own baseline. Withholding is the
          gate working, not a defect — metrics are only worth computing if they can block a
          release.
        </p>
      </CardBody>
    </Card>
  )
}

function ModelRow({ model }: { model: ModelCatalogEntry }) {
  const isServing = model.stage === 'PRODUCTION'
  const isBaseline = model.runtimeRole === 'PRIMARY_BASELINE'

  return (
    <div className="rounded border border-border px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {isServing ? (
            <CheckCircle2
              className={cn('h-3.5 w-3.5', isBaseline ? 'text-amber-400' : 'text-emerald-400')}
            />
          ) : (
            <Ban className="h-3.5 w-3.5 text-text-muted" />
          )}
          <span className="text-sm font-medium">{model.modelName}</span>
          <span className="font-mono text-[10px] text-text-muted">{model.version}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              'rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide',
              isServing && !isBaseline
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : isBaseline
                  ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                  : 'border-border text-text-muted',
            )}
          >
            {isBaseline ? 'baseline' : model.stage.toLowerCase()}
          </span>
        </div>
      </div>

      {model.gateFailures.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 border-l-2 border-amber-500/40 pl-2">
          {model.gateFailures.map((reason) => (
            <li key={reason} className="flex items-start gap-1 text-[11px] text-amber-200/80">
              <CircleDot className="mt-0.5 h-2.5 w-2.5 shrink-0" />
              {reason}
            </li>
          ))}
        </ul>
      )}
      {model.gateFailures.length === 0 && model.notes && (
        <p className="mt-1 text-[11px] text-text-muted">{model.notes}</p>
      )}
    </div>
  )
}
