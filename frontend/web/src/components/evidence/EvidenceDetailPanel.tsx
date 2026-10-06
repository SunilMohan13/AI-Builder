import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Link2 } from 'lucide-react'
import { ScientificBadge } from '../common/Badge'
import type { EvidenceNode } from '../../types'
import { NODE_THEMES } from './evidenceNodeTheme'
import { formatDateTimeIST } from '../../utils/format'
import { useReducedMotion } from '../../hooks/useReducedMotion'

interface EvidenceDetailPanelProps {
  selected: EvidenceNode | null
  eventId: string
  linkedCount: number
  totalSources: number
}

export function EvidenceDetailPanel({
  selected,
  eventId,
  linkedCount,
  totalSources,
}: EvidenceDetailPanelProps) {
  const reducedMotion = useReducedMotion()
  const theme = selected ? NODE_THEMES[selected.type] : null

  return (
    <div
      className="flex h-full min-h-[420px] flex-col overflow-hidden rounded-xl border border-cyan-500/15 bg-gradient-to-b from-bg-panel/95 to-black/40 shadow-[inset_0_1px_0_rgba(34,211,238,0.08)]"
    >
      <div className="border-b border-border/80 px-4 py-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-300/80">
          Evidence details
        </p>
        <p className="mt-0.5 text-xs text-text-muted">
          {linkedCount}/{totalSources} connectors fused · {eventId}
        </p>
      </div>

      <div className="relative flex flex-1 flex-col p-4">
        {!selected?.item && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex flex-1 flex-col items-center justify-center text-center"
          >
            <div className="mb-3 h-14 w-14 rounded-full border border-dashed border-cyan-500/30 bg-cyan-500/5" />
            <p className="text-sm text-text-secondary">Select a source node</p>
            <p className="mt-1 max-w-[220px] text-xs text-text-muted">
              Independent observations converge on the central pollution event. Likelihood ≠
              causality.
            </p>
          </motion.div>
        )}

        {selected?.item && theme && (
          <motion.div
            key={selected.id}
            initial={reducedMotion ? false : { opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            className="space-y-4"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-lg font-semibold">{selected.label}</h3>
                <p className="text-sm text-text-secondary">{selected.item.source}</p>
              </div>
              <ScientificBadge label={theme.scientific} />
            </div>

            <div className="rounded-lg border border-border/70 bg-black/25 p-3">
              <p className="text-[10px] uppercase tracking-wider text-text-muted">Observation</p>
              <p className="mt-1 text-sm leading-relaxed text-text-primary">
                {selected.item.observation}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-md border border-border/60 p-2.5">
                <p className="text-[10px] text-text-muted">Recorded</p>
                <p className="font-mono text-xs">{formatDateTimeIST(selected.item.time)}</p>
              </div>
              <div className="rounded-md border border-border/60 p-2.5">
                <p className="text-[10px] text-text-muted">Strength</p>
                <p className="font-medium">{selected.item.strength}</p>
              </div>
            </div>

            <div>
              <div className="mb-1 flex justify-between text-[10px] text-text-muted">
                <span>Confidence</span>
                <span className="font-mono text-cyan-300">{selected.item.confidence}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-border/80">
                <motion.div
                  className="h-full rounded-full bg-gradient-to-r from-cyan-600 to-cyan-400"
                  initial={reducedMotion ? false : { width: 0 }}
                  animate={{ width: `${selected.item.confidence}%` }}
                  transition={{ duration: 0.5, ease: 'easeOut' }}
                />
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-md border border-emerald-500/20 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-200/90">
              <Link2 className="h-3.5 w-3.5 shrink-0" />
              Supports event {selected.item.supports}
            </div>

            <Link
              to={`/events/${eventId}`}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-intel hover:underline"
            >
              Open full event intelligence
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </motion.div>
        )}
      </div>
    </div>
  )
}
