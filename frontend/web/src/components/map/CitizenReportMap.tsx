import { useEffect, useRef } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { CitizenReport } from '../../types'
import { attachBasemapFallback, CARTO_STYLE_URL } from './basemapStyle'

const statusColor: Record<CitizenReport['status'], string> = {
  CORROBORATED: '#22d3ee',
  PENDING: '#facc15',
  REJECTED: '#64748b',
}

/**
 * Lightweight report map. Marker count is small, so plain MapLibre markers are
 * cheaper than pulling deck.gl into this view.
 */
export function CitizenReportMap({
  reports,
  selectedId,
  onSelect,
}: {
  reports: CitizenReport[]
  selectedId?: string | null
  onSelect?: (report: CitizenReport) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const markersRef = useRef<maplibregl.Marker[]>([])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: CARTO_STYLE_URL,
      center: [77.1, 29.1],
      zoom: 7,
      attributionControl: { compact: true },
    })
    mapRef.current = map
    attachBasemapFallback(map)

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    markersRef.current.forEach((m) => m.remove())
    markersRef.current = reports.map((report) => {
      const el = document.createElement('button')
      el.type = 'button'
      el.setAttribute('aria-label', `${report.type} in ${report.location}`)
      const active = report.id === selectedId
      el.style.cssText = `width:${active ? 18 : 12}px;height:${active ? 18 : 12}px;border-radius:9999px;cursor:pointer;border:2px solid ${statusColor[report.status]};background:${statusColor[report.status]}33;`
      el.onclick = () => onSelect?.(report)
      return new maplibregl.Marker({ element: el })
        .setLngLat([report.lon, report.lat])
        .addTo(map)
    })

    return () => {
      markersRef.current.forEach((m) => m.remove())
      markersRef.current = []
    }
  }, [reports, selectedId, onSelect])

  return <div ref={containerRef} className="h-full w-full" />
}
