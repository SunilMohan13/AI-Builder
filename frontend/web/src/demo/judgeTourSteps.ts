import type { DemoPhase } from '../types'
import { heroEventPath } from '../utils/heroEvent'
import { HERO_EVENT_ID } from '../data/mockEvents'

export interface JudgeTourStep {
  route: string
  durationMs: number
  phase: DemoPhase
  caption: string
  /** Copilot auto-send when route is /copilot */
  copilotQuestion?: string
  hourOffset?: number
  layers?: Partial<{
    pollution: boolean
    fires: boolean
    wind: boolean
    forecast: boolean
    industry: boolean
    population: boolean
  }>
}

export function judgeTourSteps(heroEventId: string): JudgeTourStep[] {
  return [
    {
      route: '/',
      durationMs: 5000,
      phase: 'confirmed',
      caption: 'Delhi NCR air is severe right now, and it is still climbing',
      hourOffset: 0,
    },
    {
      route: '/map',
      durationMs: 5000,
      phase: 'fire',
      caption: 'Satellites see fires in Punjab; ground stations see the PM2.5 rise',
      hourOffset: 0,
      layers: { pollution: true, fires: true, wind: false, forecast: false },
    },
    {
      route: '/map?scene=corridor',
      durationMs: 4500,
      phase: 'plume',
      caption: 'The wind is carrying that smoke southeast, toward Delhi',
      hourOffset: 3,
      layers: { pollution: true, fires: true, wind: true, forecast: true },
    },
    {
      route: heroEventPath(heroEventId),
      durationMs: 6000,
      phase: 'plume',
      caption: 'Fires, stations, weather and satellite become one event — with its reasons',
      hourOffset: 1,
    },
    {
      route: heroEventId ? `/evidence?eventId=${heroEventId}` : '/evidence',
      durationMs: 5000,
      phase: 'confirmed',
      caption: 'Six independent sources agreeing is why we call it burning, not traffic',
    },
    {
      route: '/forecast',
      durationMs: 5500,
      phase: 'forecast',
      caption: 'Six hours ahead, and measurably better than assuming no change',
      hourOffset: 6,
      layers: { forecast: true, pollution: true, fires: true },
    },
    {
      route: '/risk',
      durationMs: 5000,
      phase: 'risk',
      caption: 'Millions of people are under the projected path',
      hourOffset: 4,
      layers: { population: true, forecast: true },
    },
    {
      route: '/copilot',
      durationMs: 8000,
      phase: 'forecast',
      caption: 'Ask it why — it answers only from the evidence on these screens',
      copilotQuestion: 'What evidence supports biomass burning near Delhi?',
    },
    {
      route: '/',
      durationMs: 4000,
      phase: 'complete',
      caption: 'That is the whole chain: detect, attribute, predict, act',
    },
  ]
}

export const JUDGE_TOUR_STEPS = judgeTourSteps(HERO_EVENT_ID)

export const JUDGE_TOUR_TOTAL_SEC = Math.round(
  JUDGE_TOUR_STEPS.reduce((s, step) => s + step.durationMs, 0) / 1000,
)
