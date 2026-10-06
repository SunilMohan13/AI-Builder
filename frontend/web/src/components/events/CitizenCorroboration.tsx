import { Link } from 'react-router-dom'
import { Camera } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { fetchCitizenReports } from '../../services/citizenService'
import { ScientificBadge } from '../common/Badge'
import { formatDateTimeIST } from '../../utils/format'
import { useDataMode } from '../../context/DataModeContext'

export function CitizenCorroboration({ eventId }: { eventId: string }) {
  const { mode } = useDataMode()
  const { data: reports = [] } = useQuery({
    queryKey: ['citizenReports', eventId, mode],
    queryFn: fetchCitizenReports,
  })

  const linked = reports.filter((r) => r.relatedEventId === eventId)
  const primary = linked[0]

  if (!primary) return null

  return (
    <div className="rounded-lg border border-emerald-500/25 bg-emerald-950/15 p-4">
      <div className="flex items-start gap-3">
        <Camera className="mt-0.5 h-5 w-5 text-emerald-400" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">Citizen corroboration</p>
            <ScientificBadge label="OBSERVED" />
          </div>
          <p className="mt-1 text-sm text-text-secondary">
            {primary.type} · {primary.location} — {primary.classification}
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Reported {formatDateTimeIST(primary.reportedAt)} · {primary.corroboration} matching
            reports · does not alone confirm causality
          </p>
          <Link
            to={`/citizen?highlight=${primary.id}`}
            className="mt-2 inline-block text-xs font-medium text-intel hover:underline"
          >
            View citizen report →
          </Link>
        </div>
      </div>
    </div>
  )
}
