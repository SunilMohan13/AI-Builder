import { useMemo } from 'react'
import { motion } from 'framer-motion'
import type { EvidenceEdge, EvidenceNode } from '../../types'
import { NODE_THEMES } from './evidenceNodeTheme'
import { useReducedMotion } from '../../hooks/useReducedMotion'

interface EvidenceGraphViewProps {
  nodes: EvidenceNode[]
  edges: EvidenceEdge[]
  selectedId: string | null
  onSelect: (node: EvidenceNode) => void
}

export function EvidenceGraphView({
  nodes,
  edges,
  selectedId,
  onSelect,
}: EvidenceGraphViewProps) {
  const reducedMotion = useReducedMotion()
  const center = nodes.find((n) => n.type === 'event')

  const activeEdgeIds = useMemo(() => {
    if (!selectedId) return new Set<string>()
    return new Set(
      edges
        .filter((e) => e.from === selectedId || e.to === selectedId)
        .map((e) => `${e.from}-${e.to}`),
    )
  }, [edges, selectedId])

  return (
    <div className="relative overflow-hidden rounded-xl border border-cyan-500/15 bg-[#060a12]">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            'radial-gradient(circle at 50% 45%, rgba(34,211,238,0.12), transparent 55%), linear-gradient(rgba(30,41,59,0.35) 1px, transparent 1px), linear-gradient(90deg, rgba(30,41,59,0.35) 1px, transparent 1px)',
          backgroundSize: '100% 100%, 32px 32px, 32px 32px',
        }}
      />

      <svg viewBox="0 0 800 420" className="relative z-[1] h-[min(52vh,440px)] w-full">
        <defs>
          <filter id="evidence-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <radialGradient id="hub-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </radialGradient>
        </defs>

        {center && (
          <circle cx={center.x} cy={center.y} r={120} fill="url(#hub-glow)" className="opacity-80" />
        )}

        {edges.map((e, i) => {
          const from = nodes.find((n) => n.id === e.from)
          const to = nodes.find((n) => n.id === e.to)
          if (!from || !to) return null
          const key = `${e.from}-${e.to}`
          const active = activeEdgeIds.has(key)
          return (
            <motion.line
              key={key}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={active ? '#22d3ee' : '#334155'}
              strokeWidth={active ? 2.5 : 1.5}
              strokeOpacity={active ? 0.95 : 0.45}
              strokeDasharray={active ? '6 8' : undefined}
              initial={reducedMotion ? false : { pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{ delay: 0.05 * i, duration: 0.45 }}
              className={active ? 'evidence-edge-flow' : undefined}
            />
          )
        })}

        {nodes.map((node, i) => {
          const theme = NODE_THEMES[node.type]
          const isSelected = selectedId === node.id
          const isHub = node.type === 'event'
          const r = isHub ? theme.radius : theme.radius
          const Icon = theme.icon

          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              className="cursor-pointer"
              onClick={() => onSelect(node)}
              role="button"
              tabIndex={0}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter' || ev.key === ' ') {
                  ev.preventDefault()
                  onSelect(node)
                }
              }}
            >
              <motion.g
                initial={reducedMotion ? false : { scale: 0.6, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: 0.06 * i, type: 'spring', stiffness: 320, damping: 22 }}
                whileHover={reducedMotion ? undefined : { scale: 1.06 }}
              >
                {(isSelected || isHub) && (
                  <circle
                    r={r + 14}
                    fill="none"
                    stroke={theme.stroke}
                    strokeOpacity={isSelected ? 0.5 : 0.25}
                    strokeWidth={1}
                    className={isHub && !reducedMotion ? 'evidence-hub-pulse' : undefined}
                  />
                )}
                <circle
                  r={r}
                  fill={theme.fill}
                  stroke={isSelected ? '#f8fafc' : theme.stroke}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  filter={isSelected ? 'url(#evidence-glow)' : undefined}
                />
                <foreignObject x={-12} y={-28} width={24} height={24} className="pointer-events-none">
                  <div className="flex h-6 w-6 items-center justify-center text-white/90">
                    <Icon size={isHub ? 18 : 14} strokeWidth={2} />
                  </div>
                </foreignObject>
                <text
                  textAnchor="middle"
                  y={r + 16}
                  fill="#e2e8f0"
                  fontSize={isHub ? 12 : 11}
                  fontWeight={isHub ? 600 : 500}
                  className="select-none font-sans"
                >
                  {node.label}
                </text>
              </motion.g>
            </g>
          )
        })}
      </svg>

      <div className="absolute bottom-3 left-3 rounded-md border border-border/60 bg-black/55 px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-text-muted">
        Click node · edges highlight fused path
      </div>
    </div>
  )
}
