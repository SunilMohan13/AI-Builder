import type { LucideIcon } from 'lucide-react'
import {
  Cloud,
  Flame,
  Gauge,
  Radar,
  Satellite,
  TrendingUp,
  Wind,
} from 'lucide-react'
import type { EvidenceNode, ScientificLabel } from '../../types'

export interface NodeTheme {
  fill: string
  stroke: string
  glow: string
  icon: LucideIcon
  scientific: ScientificLabel
  radius: number
}

export const NODE_THEMES: Record<EvidenceNode['type'], NodeTheme> = {
  event: {
    fill: '#0e7490',
    stroke: '#22d3ee',
    glow: 'rgba(34, 211, 238, 0.55)',
    icon: Radar,
    scientific: 'INFERRED',
    radius: 40,
  },
  fire: {
    fill: '#9a3412',
    stroke: '#fb923c',
    glow: 'rgba(251, 146, 60, 0.5)',
    icon: Flame,
    scientific: 'OBSERVED',
    radius: 30,
  },
  cpcb: {
    fill: '#14532d',
    stroke: '#4ade80',
    glow: 'rgba(74, 222, 128, 0.45)',
    icon: Gauge,
    scientific: 'OBSERVED',
    radius: 30,
  },
  satellite: {
    fill: '#4c1d95',
    stroke: '#a78bfa',
    glow: 'rgba(167, 139, 250, 0.45)',
    icon: Satellite,
    scientific: 'OBSERVED',
    radius: 30,
  },
  weather: {
    fill: '#1e3a5f',
    stroke: '#38bdf8',
    glow: 'rgba(56, 189, 248, 0.45)',
    icon: Wind,
    scientific: 'OBSERVED',
    radius: 30,
  },
  cams: {
    fill: '#134e4a',
    stroke: '#2dd4bf',
    glow: 'rgba(45, 212, 191, 0.4)',
    icon: Cloud,
    scientific: 'OBSERVED',
    radius: 30,
  },
  forecast: {
    fill: '#164e63',
    stroke: '#22d3ee',
    glow: 'rgba(34, 211, 238, 0.4)',
    icon: TrendingUp,
    scientific: 'PREDICTED',
    radius: 30,
  },
}
