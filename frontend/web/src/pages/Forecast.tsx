import { useState, useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Play, Pause, RotateCcw } from 'lucide-react'
import {
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Area,
  ComposedChart,
  ReferenceLine,
  CartesianGrid,
} from 'recharts'
import { AeroMap } from '../components/map/AeroMap'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { ScientificBadge } from '../components/common/Badge'
import { fetchForecastSeries } from '../services/forecastService'
import { fetchEvents } from '../services/eventService'
import { pickHeroEvent } from '../utils/heroEvent'
import { useApp } from '../context/AppContext'
import { useReducedMotion } from '../hooks/useReducedMotion'
import { getPollutionSwatch, getBandLabel } from '../utils/aqi'
import { useDataMode } from '../context/DataModeContext'
import { FallbackBanner, ModeContextNote } from '../components/common/Provenance'
import { HazardOutlook } from '../components/events/HazardOutlook'

const horizons = [0, 1, 3, 6, 12, 24, 48]

export function Forecast() {
  const { mode } = useDataMode()
  const { data: series = [] } = useQuery({
    queryKey: ['forecastSeries', mode],
    queryFn: () => fetchForecastSeries(),
  })
  const { data: events } = useQuery({
    queryKey: ['events', mode],
    queryFn: fetchEvents,
  })
  const region = pickHeroEvent(events)?.region ?? '—'
  const { hourOffset, setHourOffset } = useApp()
  const [playing, setPlaying] = useState(false)
  const reducedMotion = useReducedMotion()
  const playRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!playing || reducedMotion) return
    playRef.current = setInterval(() => {
      setHourOffset((h) => (h >= 12 ? 0 : h + 1))
    }, 1100)
    return () => {
      if (playRef.current) clearInterval(playRef.current)
    }
  }, [playing, reducedMotion, setHourOffset])

  // A true range area (tuple dataKey) draws the confidence band directly,
  // rather than masking a stacked area against a hardcoded page colour.
  const chartData = useMemo(
    () =>
      series.map((p) => ({
        hour: p.hour,
        pm25: p.pm25,
        baselinePm25: p.baselinePm25 ?? p.pm25,
        band: [p.confidenceLow, p.confidenceHigh] as [number, number],
      })),
    [series],
  )

  const current = useMemo(() => {
    if (series.length === 0) return null
    return series.reduce(
      (best, p) =>
        Math.abs(p.hour - hourOffset) < Math.abs(best.hour - hourOffset) ? p : best,
      series[0],
    )
  }, [series, hourOffset])

  const peak = useMemo(() => {
    if (series.length === 0) return null
    return series.reduce((a, b) => (b.pm25 > a.pm25 ? b : a), series[0])
  }, [series])

  const yDomain = useMemo(() => {
    if (series.length === 0) return { min: 0, max: 100 }
    const lows = series.map((p) => p.confidenceLow)
    const highs = series.map((p) => p.confidenceHigh)
    const pad = 12
    return {
      min: Math.max(0, Math.floor((Math.min(...lows) - pad) / 10) * 10),
      max: Math.ceil((Math.max(...highs) + pad) / 10) * 10,
    }
  }, [series])

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <FallbackBanner />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold">Forecast</h1>
          <p className="text-sm text-text-secondary">Where pollution will move</p>
          <ModeContextNote />
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wider text-text-muted">
              {region} · {hourOffset === 0 ? 'now' : `+${hourOffset}h`}
            </p>
            <div className="flex items-baseline gap-2">
              <motion.span
                key={current?.pm25 ?? 'empty'}
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="font-mono text-2xl font-bold tabular-nums"
                style={{ color: current ? getPollutionSwatch(current.pm25) : undefined }}
              >
                {current ? current.pm25 : '—'}
              </motion.span>
              <span className="text-xs text-text-muted">
                {current ? `µg/m³ · ${getBandLabel(current.pm25)}` : 'no forecast'}
              </span>
            </div>
          </div>
          <ScientificBadge label="PREDICTED" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div
          role="group"
          aria-label="Forecast horizon"
          className="flex overflow-hidden rounded-lg border border-border"
        >
          {horizons.map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => setHourOffset(h)}
              aria-pressed={hourOffset === h}
              className={`relative px-3.5 py-1.5 text-sm transition-colors ${
                hourOffset === h
                  ? 'text-intel'
                  : 'text-text-secondary hover:bg-bg-panel hover:text-text-primary'
              }`}
            >
              {hourOffset === h && (
                <motion.span
                  layoutId="horizon-pill"
                  className="absolute inset-0 -z-10 bg-intel/15"
                  transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                />
              )}
              {h === 0 ? 'Now' : `${h}h`}
            </button>
          ))}
        </div>

        <div className="ml-auto flex gap-1">
          <button
            type="button"
            onClick={() => setPlaying(!playing)}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary transition-colors hover:border-intel/40 hover:text-intel"
          >
            {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {playing ? 'Pause' : 'Play forecast'}
          </button>
          <button
            type="button"
            onClick={() => {
              setPlaying(false)
              setHourOffset(0)
            }}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary transition-colors hover:text-text-primary"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </button>
        </div>
      </div>

      <Card className="min-h-[300px] flex-1 overflow-hidden">
        <CardBody className="h-full p-0">
          {/* `embedded` suppresses the full map chrome. The map timeline is
              off because the horizon buttons above already set the hour, and
              two scrubbers for one value is how they drift apart. */}
          <AeroMap
            embedded
            showControls={false}
            showGlobeBar={false}
            showTimeline={false}
            showLegend={false}
            forceLayers={{ forecast: true, pollution: true, fires: true, wind: false }}
            className="h-full w-full"
          />
        </CardBody>
      </Card>

      {/* Kept below the map rather than in a side column so the trajectory is
          always on screen, not pushed off at narrow widths. */}
      <div className="grid shrink-0 gap-3 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardHeader className="flex items-center justify-between py-2">
            <span className="text-xs font-medium">PM2.5 trajectory · {region}</span>
            <span className="text-[10px] text-text-muted">
              cyan = model · dashed = persistence baseline
            </span>
          </CardHeader>
          <CardBody className="h-[150px] p-2">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                <CartesianGrid stroke="#151f30" vertical={false} />
                <XAxis
                  dataKey="hour"
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  tickFormatter={(h: number) => (h === 0 ? 'Now' : `+${h}h`)}
                  stroke="#1e293b"
                />
                {/* Domain follows the data so the rise is legible instead of
                    being flattened against a 0-based axis. */}
                <YAxis
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  stroke="#1e293b"
                  domain={[yDomain.min, yDomain.max]}
                  allowDataOverflow
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{
                    background: '#151d2e',
                    border: '1px solid #1e293b',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelFormatter={(h) => (h === 0 ? 'Now' : `+${h}h`)}
                  formatter={(value, name) =>
                    name === 'pm25'
                      ? [`${value} µg/m³`, 'Predicted']
                      : [
                          `${(value as [number, number])[0]}–${(value as [number, number])[1]}`,
                          'Confidence',
                        ]
                  }
                />
                <Area
                  dataKey="band"
                  stroke="none"
                  fill="rgba(34,211,238,0.20)"
                  isAnimationActive={!reducedMotion}
                />
                <ReferenceLine
                  x={hourOffset}
                  stroke="#22d3ee"
                  strokeDasharray="3 3"
                  strokeOpacity={0.8}
                />
                <Line
                  type="monotone"
                  dataKey="baselinePm25"
                  stroke="#64748b"
                  strokeWidth={1.5}
                  strokeDasharray="6 4"
                  dot={false}
                  isAnimationActive={!reducedMotion}
                  name="baseline"
                />
                <Line
                  type="monotone"
                  dataKey="pm25"
                  stroke="#22d3ee"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={!reducedMotion}
                  name="pm25"
                />
              </ComposedChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>

        <Card>
          <CardHeader className="py-2">
            <span className="text-xs font-medium">Outlook</span>
          </CardHeader>
          <CardBody className="space-y-2 p-3 text-xs">
            <div className="flex justify-between">
              <span className="text-text-secondary">Peak</span>
              <span className="font-mono font-medium">
                {peak ? `${peak.pm25} µg/m³ · +${peak.hour}h` : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">Confidence range</span>
              <span className="font-mono">
                {current ? `${current.confidenceLow}–${current.confidenceHigh}` : '—'}
              </span>
            </div>
            {/* Skill against persistence is an offline evaluation result.
                No served response carries it, so it is a demo figure. */}
            {mode === 'demo' && (
              <>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Forecast confidence</span>
                  <span className="font-mono">89%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">vs persistence @ +6h</span>
                  <span className="font-mono text-emerald-400">−18% error</span>
                </div>
              </>
            )}
            <p className="border-t border-border pt-2 text-text-muted">
              {mode === 'demo'
                ? 'Smoke is advecting southeast from the Punjab fire cluster at ~22 km/h. Values are model output, not measurements.'
                : 'These are model outputs, not measurements. Treat the band, not the line, as the answer.'}
            </p>
          </CardBody>
        </Card>
      </div>

      <HazardOutlook />
    </div>
  )
}
