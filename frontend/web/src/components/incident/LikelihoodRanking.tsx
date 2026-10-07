import type { Hazard, LikelihoodEntry } from '../../api/regionTypes'
import { ProvenanceBadge } from '../common/ProvenanceBadge'
import { humanise } from '../../utils/format'

/**
 * Source likelihood as the API serves it: a heuristic ranking. Bars are
 * scaled to the top score in the entry so they read as order, never as
 * percentages; the raw score is shown beside each.
 */
export function LikelihoodRanking({
  entry,
  hazards,
  showEvidence = true,
}: {
  entry: LikelihoodEntry
  hazards: Hazard[]
  showEvidence?: boolean
}) {
  const names = new Map(hazards.map((h) => [h.source_class, h.display_name]))
  const ranking = [...entry.ranking].sort((a, b) => b.score - a.score)
  const top = ranking[0]?.score ?? 0

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-text-muted">
        <ProvenanceBadge value={entry.provenance_class} />
        <span>
          {entry.calibrated ? 'Calibrated' : 'Not calibrated'} · {entry.method_version} · cell{' '}
          <span className="font-mono">{entry.grid_id}</span>
        </span>
      </div>
      <p className="text-[10px] text-amber-300/80">
        A ranking, not probabilities: scores do not sum to 1 and are not percentages.
      </p>
      <ul className="space-y-1">
        {ranking.map((r) => (
          <li key={r.source_class}>
            <div className="flex justify-between text-xs">
              <span className="text-text-secondary">{names.get(r.source_class) ?? humanise(r.source_class)}</span>
              <span className="font-mono text-text-muted">score {r.score}</span>
            </div>
            <div className="mt-0.5 h-1.5 rounded bg-border">
              <div
                className="h-full rounded bg-amber-400/70"
                style={{ width: `${top > 0 ? (r.score / top) * 100 : 0}%` }}
              />
            </div>
            {r.contributing_signals.length > 0 && (
              <p className="mt-0.5 text-[10px] text-text-muted">
                {r.contributing_signals.map(humanise).join(' · ')}
              </p>
            )}
          </li>
        ))}
      </ul>
      {showEvidence && entry.evidence.length > 0 && (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-text-muted">Evidence ({entry.evidence.length} signals)</summary>
          <table className="mt-1 w-full">
            <tbody>
              {entry.evidence.map((e) => (
                <tr key={e.signal} className="border-t border-border/60">
                  <td className="py-0.5 pr-2 text-text-secondary">{humanise(e.signal)}</td>
                  <td className="py-0.5 pr-2 font-mono">
                    {e.value === null ? (
                      <span className="text-text-muted" title="The signal had no value for this cell.">
                        —
                      </span>
                    ) : (
                      `${String(e.value)}${e.unit ? ` ${e.unit}` : ''}`
                    )}
                  </td>
                  <td className="py-0.5 text-text-muted">{e.source_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  )
}
