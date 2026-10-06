/**
 * Builds a small, region-clipped geography bundle from Natural Earth
 * (public domain) so the map always has coastlines and borders without
 * depending on a remote basemap.
 *
 * Run: node scripts/build-geography.mjs
 */
import { writeFileSync } from 'node:fs'

const BASE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson'

// Generous around the Punjab–Delhi corridor so panning stays in context.
const BBOX = { west: 66, east: 90, south: 19, north: 38 }

const SETS = [
  { file: 'ne_50m_coastline', kind: 'coast' },
  { file: 'ne_50m_admin_0_boundary_lines_land', kind: 'country' },
  { file: 'ne_50m_admin_1_states_provinces_lines', kind: 'state' },
]

const inBox = ([lon, lat]) =>
  lon >= BBOX.west && lon <= BBOX.east && lat >= BBOX.south && lat <= BBOX.north

const round = ([lon, lat]) => [Math.round(lon * 1000) / 1000, Math.round(lat * 1000) / 1000]

/** Split a line into the runs that fall inside the bbox, keeping the
 *  crossing point on each side so lines reach the frame edge. */
function clipLine(coords) {
  const runs = []
  let run = []
  for (let i = 0; i < coords.length; i++) {
    const here = inBox(coords[i])
    const neighbourInside =
      (i > 0 && inBox(coords[i - 1])) || (i < coords.length - 1 && inBox(coords[i + 1]))
    if (here || neighbourInside) {
      run.push(round(coords[i]))
    } else if (run.length > 1) {
      runs.push(run)
      run = []
    } else {
      run = []
    }
  }
  if (run.length > 1) runs.push(run)
  return runs
}

const features = []

for (const { file, kind } of SETS) {
  const res = await fetch(`${BASE}/${file}.geojson`)
  if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`)
  const fc = await res.json()

  let kept = 0
  for (const f of fc.features) {
    const g = f.geometry
    if (!g) continue
    const lines =
      g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : []

    for (const line of lines) {
      for (const run of clipLine(line)) {
        features.push({
          type: 'Feature',
          properties: { kind },
          geometry: { type: 'LineString', coordinates: run },
        })
        kept++
      }
    }
  }
  console.log(`${file.padEnd(42)} -> ${kept} clipped lines`)
}

const out = { type: 'FeatureCollection', features }
const json = JSON.stringify(out)
writeFileSync(new URL('../src/data/geography.json', import.meta.url), json)
console.log(`\nwrote src/data/geography.json — ${(json.length / 1024).toFixed(0)} KB, ${features.length} features`)
