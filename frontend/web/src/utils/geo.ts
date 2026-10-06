export const KM_PER_DEG_LAT = 111

export function cellPolygon(lat: number, lon: number, sizeKm = 1): [number, number][] {
  const dLat = sizeKm / KM_PER_DEG_LAT / 2
  const dLon = sizeKm / (KM_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180)) / 2
  return [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat - dLat],
    [lon + dLon, lat + dLat],
    [lon - dLon, lat + dLat],
    [lon - dLon, lat - dLat],
  ]
}

/** Square cell covering exactly one grid step, so adjacent cells tile without gaps. */
export function cellPolygonDeg(lat: number, lon: number, stepDeg: number): [number, number][] {
  const h = stepDeg / 2
  return [
    [lon - h, lat - h],
    [lon + h, lat - h],
    [lon + h, lat + h],
    [lon - h, lat + h],
    [lon - h, lat - h],
  ]
}

/** 1 km expressed in degrees of latitude — the native analytical resolution. */
export const KM1_DEG = 1 / KM_PER_DEG_LAT

export function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLon = ((lon2 - lon1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/**
 * Gaussian puff advected downwind. Distances are in kilometres and the
 * dispersion sigmas grow with travel distance, so a Punjab release reaches
 * Delhi (~300 km downwind) over the forecast horizon instead of decaying
 * within a few kilometres.
 */
export function plumeKernel(
  cellLat: number,
  cellLon: number,
  originLat: number,
  originLon: number,
  transportBearingDeg: number,
  intensity: number,
  hourOffset: number,
  windSpeedKmh = WIND_SPEED_KMH,
): number {
  const north = (cellLat - originLat) * KM_PER_DEG_LAT
  const east =
    (cellLon - originLon) * KM_PER_DEG_LAT * Math.cos((originLat * Math.PI) / 180)

  const theta = (transportBearingDeg * Math.PI) / 180
  const downwind = east * Math.sin(theta) + north * Math.cos(theta)
  const crosswind = east * Math.cos(theta) - north * Math.sin(theta)

  // Upwind of the source the contribution is negligible.
  if (downwind < -25) return 0

  const travel = Math.max(windSpeedKmh * hourOffset, 1)
  const sigmaAlong = 45 + travel * 0.5
  // Kept narrow relative to the along-wind spread so the result reads as a
  // directional ribbon rather than a circular wash.
  const sigmaCross = 15 + travel * 0.12

  const along = Math.exp(-((downwind - travel) ** 2) / (2 * sigmaAlong ** 2))
  const cross = Math.exp(-(crosswind ** 2) / (2 * sigmaCross ** 2))
  const dilution = 1 / (1 + travel / 180)

  return intensity * along * cross * dilution
}

/**
 * Analysis domain. Deliberately wider than the Punjab–Delhi corridor so the
 * field extends past the viewport at the default zoom; a tight rectangle
 * renders its own boundary as a hard-edged box over the basemap.
 */
export const CORRIDOR_BOUNDS = {
  west: 71.5,
  east: 81.5,
  south: 25.0,
  north: 33.5,
}

export const PUNJAB_FIRE_CENTER = { lat: 30.9, lon: 75.4 }

/**
 * Direction the smoke travels toward, degrees clockwise from north. 146°
 * points the Punjab plume down the corridor at Delhi NCR.
 */
export const TRANSPORT_BEARING_DEG = 146

/** Meteorological convention: the direction the wind blows *from*. */
export const WIND_FROM_DEG = (TRANSPORT_BEARING_DEG + 180) % 360

export const WIND_SPEED_MS = 6
export const WIND_SPEED_KMH = WIND_SPEED_MS * 3.6

export interface NamedLocation {
  name: string
  lat: number
  lon: number
  zoom: number
}

/** Searchable places inside the pilot corridor. */
export const CORRIDOR_LOCATIONS: NamedLocation[] = [
  { name: 'Delhi NCR', lat: 28.61, lon: 77.21, zoom: 9 },
  { name: 'Ghaziabad', lat: 28.67, lon: 77.45, zoom: 10 },
  { name: 'Sonipat', lat: 28.99, lon: 77.02, zoom: 10 },
  { name: 'Panipat', lat: 29.39, lon: 76.97, zoom: 10 },
  { name: 'Karnal', lat: 29.69, lon: 76.99, zoom: 10 },
  { name: 'Ambala', lat: 30.38, lon: 76.78, zoom: 10 },
  { name: 'Ludhiana', lat: 30.9, lon: 75.85, zoom: 10 },
  { name: 'Patiala', lat: 30.34, lon: 76.38, zoom: 10 },
  { name: 'Amritsar', lat: 31.63, lon: 74.87, zoom: 10 },
  { name: 'Punjab fire cluster', lat: PUNJAB_FIRE_CENTER.lat, lon: PUNJAB_FIRE_CENTER.lon, zoom: 8.5 },
]

export function searchLocations(query: string, limit = 5): NamedLocation[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  return CORRIDOR_LOCATIONS.filter((l) => l.name.toLowerCase().includes(q)).slice(0, limit)
}
