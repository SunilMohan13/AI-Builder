import { mockEvidence, evidenceNodes, evidenceEdges, eventTimeline } from '../data/mockEvidence'
import { HERO_EVENT_ID } from '../data/mockEvents'
import type { EvidenceItem, EvidenceNode, EvidenceEdge, TimelineEvent } from '../types'
import { liveEvidence, liveEvidenceGraph, liveTimeline } from '../api/live'
import { resolve } from './resolve'

const delay = (ms = 100) => new Promise((r) => setTimeout(r, ms))

async function demoEvidence(eventId: string): Promise<EvidenceItem[]> {
  await delay()
  return mockEvidence.filter((e) => e.supports === eventId)
}

export async function fetchEvidence(eventId: string): Promise<EvidenceItem[]> {
  return resolve(
    'evidence',
    () => demoEvidence(eventId),
    () => liveEvidence(eventId),
  )
}

/**
 * The evidence graph view.
 *
 * Live reads `GET /api/v1/events/{id}/graph` and places vertices on a radial
 * layout. Demo keeps the curated illustration. An empty live graph is shown
 * as empty rather than silently substituting the illustration.
 */
export async function fetchEvidenceGraph(eventId?: string): Promise<{
  nodes: EvidenceNode[]
  edges: EvidenceEdge[]
}> {
  const target = eventId ?? HERO_EVENT_ID
  return resolve(
    'evidence-graph',
    async () => {
      await delay()
      return { nodes: evidenceNodes, edges: evidenceEdges }
    },
    () => liveEvidenceGraph(target),
  )
}

export async function fetchEventTimeline(eventId: string): Promise<TimelineEvent[]> {
  return resolve(
    'timeline',
    async () => {
      await delay(60)
      if (eventId === HERO_EVENT_ID) return eventTimeline
      return eventTimeline.slice(0, 3)
    },
    () => liveTimeline(eventId),
  )
}
