import { mockSources } from '../data/mockSources'
import type { SourceHealth } from '../types'
import { liveSources } from '../api/live'
import { resolve } from './resolve'

const delay = (ms = 80) => new Promise((r) => setTimeout(r, ms))

let freshnessBump = 0

export function bumpSourceFreshness() {
  freshnessBump = (freshnessBump + 1) % 3
}

async function demoSources(): Promise<SourceHealth[]> {
  await delay()
  return mockSources.map((s) => ({
    ...s,
    freshnessMinutes:
      s.freshnessMinutes === null ? null : s.freshnessMinutes + freshnessBump,
  }))
}

export async function fetchSources(): Promise<SourceHealth[]> {
  return resolve('sources', demoSources, liveSources)
}

export async function fetchSource(id: string): Promise<SourceHealth | null> {
  const sources = await fetchSources()
  return sources.find((s) => s.id === id) ?? null
}
