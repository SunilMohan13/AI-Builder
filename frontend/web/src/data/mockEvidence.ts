import type { EvidenceItem, EvidenceNode, EvidenceEdge, TimelineEvent } from '../types'
import { HERO_EVENT_ID } from './mockEvents'

export const mockEvidence: EvidenceItem[] = [
  {
    id: 'ev_1',
    category: 'Fire',
    source: 'NASA FIRMS',
    observation: '42 active fire detections in Punjab corridor',
    time: '2026-09-08T08:32:00Z',
    confidence: 91,
    supports: HERO_EVENT_ID,
    strength: 'Strong',
  },
  {
    id: 'ev_2',
    category: 'CPCB',
    source: 'CPCB CAAQMS',
    observation: 'PM2.5 increased 68% across 6 stations within 30 min',
    time: '2026-09-08T08:35:00Z',
    confidence: 96,
    supports: HERO_EVENT_ID,
    strength: 'Strong',
  },
  {
    id: 'ev_3',
    category: 'Satellite',
    source: 'Sentinel-5P',
    observation: 'Elevated NO₂ column over source region',
    time: '2026-09-08T06:30:00Z',
    confidence: 84,
    supports: HERO_EVENT_ID,
    strength: 'Moderate',
  },
  {
    id: 'ev_4',
    category: 'Weather',
    source: 'IMD',
    observation: 'SE wind 14 km/h aligned with transport corridor',
    time: '2026-09-08T08:30:00Z',
    confidence: 94,
    supports: HERO_EVENT_ID,
    strength: 'Strong',
  },
  {
    id: 'ev_5',
    category: 'CAMS',
    source: 'Copernicus CAMS',
    observation: 'Regional transport signal supports plume movement',
    time: '2026-09-08T07:45:00Z',
    confidence: 78,
    supports: HERO_EVENT_ID,
    strength: 'Moderate',
  },
  {
    id: 'ev_6',
    category: 'Forecast',
    source: 'AeroPulse Forecast Engine',
    observation: 'Plume trajectory toward Delhi NCR within 6h',
    time: '2026-09-08T08:40:00Z',
    confidence: 89,
    supports: HERO_EVENT_ID,
    strength: 'Strong',
  },
  {
    id: 'ev_7',
    category: 'Citizen',
    source: 'Citizen report cr_4',
    observation: 'Geotagged smoke photo near Sangrur, 11 km from fire cluster',
    time: '2026-09-08T08:20:00Z',
    confidence: 62,
    supports: HERO_EVENT_ID,
    // Deliberately Weak. A citizen report raises confidence only where
    // independent evidence already agrees, and never opens an event on its
    // own — showing it as Strong would misrepresent how it is used.
    strength: 'Weak',
  },
  {
    id: 'ev_8',
    category: 'Counter-signal',
    source: 'MODIS MAIAC AOD',
    observation: 'AOD retrieval unavailable over source region — 78% cloud cover',
    time: '2026-09-08T07:10:00Z',
    confidence: 41,
    supports: HERO_EVENT_ID,
    // An absent observation is evidence about coverage, not about pollution.
    // Listing it keeps the panel from reading as six sources all agreeing
    // when one of them simply could not see.
    strength: 'Weak',
  },
]

export const evidenceNodes: EvidenceNode[] = [
  { id: 'event', label: 'Pollution Event', type: 'event', x: 400, y: 200 },
  { id: 'fire', label: 'Fire', type: 'fire', x: 120, y: 80, item: mockEvidence[0] },
  { id: 'cpcb', label: 'CPCB', type: 'cpcb', x: 120, y: 200, item: mockEvidence[1] },
  { id: 'satellite', label: 'Satellite', type: 'satellite', x: 120, y: 320, item: mockEvidence[2] },
  { id: 'weather', label: 'Weather', type: 'weather', x: 680, y: 80, item: mockEvidence[3] },
  { id: 'cams', label: 'CAMS', type: 'cams', x: 680, y: 200, item: mockEvidence[4] },
  { id: 'forecast', label: 'Forecast', type: 'forecast', x: 680, y: 320, item: mockEvidence[5] },
]

export const evidenceEdges: EvidenceEdge[] = [
  { from: 'fire', to: 'event' },
  { from: 'cpcb', to: 'event' },
  { from: 'satellite', to: 'event' },
  { from: 'weather', to: 'event' },
  { from: 'cams', to: 'event' },
  { from: 'forecast', to: 'event' },
]

export const eventTimeline: TimelineEvent[] = [
  { id: 't1', time: '08:32', label: 'Fire cluster detected (FIRMS)', icon: 'fire' },
  { id: 't2', time: '08:35', label: 'PM2.5 anomaly confirmed (CPCB)', icon: 'alert' },
  { id: 't3', time: '08:38', label: 'Wind alignment verified (IMD)', icon: 'wind' },
  { id: 't4', time: '08:40', label: 'Event confirmed — HIGH severity', icon: 'check' },
  { id: 't5', time: '08:42', label: 'Forecast plume generated', icon: 'forecast' },
  { id: 't6', time: '08:45', label: 'Population exposure calculated', icon: 'risk' },
  { id: 't7', time: '08:47', label: 'Citizen photo corroborated (+6% source conf.)', icon: 'fire' },
  { id: 't8', time: '08:52', label: 'Authority alert dispatched — Delhi NCR', icon: 'alert' },
  { id: 't9', time: '09:05', label: 'GRAP Stage II recommended to CAQM', icon: 'check' },
]
