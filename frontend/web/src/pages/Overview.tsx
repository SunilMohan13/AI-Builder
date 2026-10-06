import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import { KpiStat } from '../components/common/KpiStat'
import { EmptyState, LoadingState } from '../components/common/States'
import { ScientificBadge, StatusBadge } from '../components/common/Badge'
import { AeroMap } from '../components/map/AeroMap'
import { fetchEvents } from '../services/eventService'
import { fetchTotalExposure } from '../services/riskService'
import { fetchForecastSeries } from '../services/forecastService'
import { fetchSources } from '../services/sourceService'
import { pickHeroEvent } from '../utils/heroEvent'
import { getBandLabel } from '../utils/aqi'
import { formatFreshness } from '../utils/format'
import { useDataMode } from '../context/DataModeContext'
import { FallbackBanner, ModeContextNote, ScreenJobNote } from '../components/common/Provenance'
import { HealthGuidance } from '../components/common/HealthGuidance'
import { AdvancedOnly, useViewLevel } from '../context/ViewLevelContext'
import type { ForecastPoint, PollutionEvent } from '../types'

const FORECAST_HOURS = [1, 3, 6, 12]

/**
 * Picks the predicted horizons closest to the ones the peek wants to show.
 *
 * Returns `wanted` unchanged when there is no series yet, so the panel keeps
 * its shape while loading rather than reflowing once data lands.
 */
function nearestHours(wanted: number[], forecast: ForecastPoint[]): number[] {
  const available = forecast.filter((p) => p.hour > 0).map((p) => p.hour)
  if (available.length === 0) return wanted
  const snapped = wanted.map((target) =>
    available.reduce(
      (best, hour) => (Math.abs(hour - target) < Math.abs(best - target) ? hour : best),
      available[0],
    ),
  )
  return [...new Set(snapped)]
}

type Trend = 'rising' | 'falling' | 'steady' | 'unknown'

/** Direction over the next three hours, from the forecast on this screen. */
function readTrend(nowPm25: number | undefined, forecast: ForecastPoint[]): Trend {
  const ahead = forecast.find((p) => p.hour === 3) ?? forecast.find((p) => p.hour === 1)
  if (nowPm25 == null || !ahead) return 'unknown'
  const change = ahead.pm25 - nowPm25
  // Below 5 µg/m³ the move is inside the noise of the measurement itself.
  if (Math.abs(change) < 5) return 'steady'
  return change > 0 ? 'rising' : 'falling'
}

const TREND_COPY: Record<Trend, string> = {
  rising: 'getting worse over the next 3 hours',
  falling: 'easing over the next 3 hours',
  steady: 'holding steady over the next 3 hours',
  unknown: 'with no forecast available yet',
}

export function Overview() {
  const { mode } = useDataMode()
  const { data: events = [], isLoading: eventsLoading } = useQuery({
    queryKey: ['events', mode],
    queryFn: fetchEvents,
  })
  const { data: totalExposure } = useQuery({
    queryKey: ['totalExposure', mode],
    queryFn: fetchTotalExposure,
  })
  const { data: forecast = [] } = useQuery({
    queryKey: ['forecastSeries', mode],
    queryFn: () => fetchForecastSeries(),
  })
  const { data: sources = [] } = useQuery({
    queryKey: ['sources', mode],
    queryFn: fetchSources,
  })
  const hero = pickHeroEvent(events)
  const activeCount = events.filter((e) => e.status === 'ACTIVE').length
  const exposureKnown = totalExposure !== null && totalExposure !== undefined

  // The headline arrow used to be a hardcoded "up" while the forecast beside
  // it fell from 185 to 94. Read the direction off the forecast that is on
  // the same screen, so the two can never disagree.
  const trend = readTrend(hero?.pm25, forecast)

  // The horizons belong to whoever produced the forecast, so a fixed +1h
  // column sat permanently empty in live, where the API's first horizon is
  // later than that. Snap each wanted horizon to the nearest one actually
  // predicted and drop the duplicates, which keeps the near/mid/far spread
  // the peek is for instead of collapsing onto the first four rows.
  const peekHours = nearestHours(FORECAST_HOURS, forecast)

  if (eventsLoading) return <LoadingState message="Loading command overview..." />

  return (
    <div className="flex h-full min-h-0 flex-col overflow-auto bg-black">
      <div className="shrink-0 border-b border-cyan-500/20 bg-gradient-to-r from-black via-bg-panel/40 to-black px-4 py-2">
        <h1 className="font-mono text-xs uppercase tracking-[0.22em] text-cyan-300/95">
          Command overview
        </h1>
        <ScreenJobNote
          question="How bad is it, and what is driving it?"
          serves="catalog KPIs, event list, forecast peek, source freshness"
          notThis="the 1 km grid lab or a single-event Detect workspace"
        />
        <ModeContextNote className="pt-1 text-[11px]" />
        <FallbackBanner />
      </div>

      {hero ? <SituationBlock hero={hero} trend={trend} /> : null}

      <KpiStrip
        aqi={hero && !hero.provenance?.unavailable?.includes('pm25') ? hero.aqi : undefined}
        pm25={hero && !hero.provenance?.unavailable?.includes('pm25') ? hero.pm25 : undefined}
        trend={trend}
        activeCount={activeCount}
        totalCount={events.length}
        totalExposure={exposureKnown ? (totalExposure as number) : null}
      />

      <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,1.1fr)_minmax(260px,0.9fr)]">
        <aside className="flex min-h-0 flex-col border-b border-border lg:border-b-0 lg:border-r">
          <div className="border-b border-border px-4 py-3">
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
              Event catalog
            </p>
            <p className="mt-1 text-[11px] text-text-secondary">
              {events.length} events fused from multiple sources
            </p>
          </div>
          {events.length === 0 ? (
            <EmptyState
              title="No live events"
              description="Switch to Demo for the Punjab episode, or wait for the API to fuse an event."
            />
          ) : (
            <ul className="min-h-0 flex-1 overflow-auto">
              {events.map((event) => (
                <li key={event.id}>
                  <EventRow event={event} featured={event.id === hero?.id} />
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* Scrolls on its own, like the event list opposite it. Without
            this the third card runs past the row and the locator map,
            which comes later in the document, paints over it. */}
        <div className="flex min-h-0 flex-col overflow-auto">
          <div className="border-b border-border px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
                Forecast peek
              </p>
              <ScientificBadge label="PREDICTED" />
            </div>
            <div
              className="mt-3 grid gap-2"
              style={{ gridTemplateColumns: `repeat(${peekHours.length}, minmax(0, 1fr))` }}
            >
              {peekHours.map((hour) => {
                const point = forecast.find((p) => p.hour === hour)
                return (
                  <div key={hour}>
                    <p className="font-mono text-[10px] text-text-muted">+{hour}h</p>
                    <p className="font-mono text-sm text-text-primary">
                      {point ? `${Math.round(point.pm25)}` : '—'}
                    </p>
                    <p className="text-[10px] text-text-muted">µg/m³</p>
                  </div>
                )
              })}
            </div>
            <Link to="/forecast" className="mt-2 inline-block text-[11px] text-intel hover:underline">
              Open forecast chart →
            </Link>
          </div>

          <div className="border-b border-border px-4 py-3">
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
              What to do now
            </p>
            <div className="mt-2">
              <HealthGuidance
                pm25={hero && !hero.provenance?.unavailable?.includes('pm25') ? hero.pm25 : null}
              />
            </div>
          </div>

          {/* Repeats Source Health in full. Kept for the operator who wants
              to know whether to trust the screen, hidden from everyone
              answering "how bad is it". */}
          <AdvancedOnly>
            <div className="border-b border-border px-4 py-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
                Source freshness
              </p>
              <ul className="mt-2 space-y-1">
                {sources.slice(0, 5).map((source) => (
                  <li
                    key={source.id}
                    className="flex items-center justify-between gap-2 font-mono text-[11px]"
                  >
                    <span className="text-text-secondary">{source.name}</span>
                    <span className="text-text-muted">
                      {source.status} · {formatFreshness(source.freshnessMinutes)}
                    </span>
                  </li>
                ))}
              </ul>
              <Link
                to="/sources"
                className="mt-2 inline-block text-[11px] text-intel hover:underline"
              >
                Open source health →
              </Link>
            </div>
          </AdvancedOnly>
        </div>
      </div>

      <div className="relative h-48 shrink-0 border-t border-border">
        <AeroMap
          compact
          embedded
          showTimeline={false}
          showGlobeBar={false}
          showControls={false}
          showLegend={false}
          forceLayers={{
            pollution: true,
            fires: true,
            wind: false,
            forecast: false,
            industry: false,
            population: false,
          }}
          initialScene="corridor"
          sceneRequest="corridor"
          className="h-full"
        />
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center justify-between gap-2 px-3 py-2">
          <p className="rounded border border-white/10 bg-black/70 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-text-muted backdrop-blur">
            Locator · PM2.5 + fires only
          </p>
          <Link
            to="/map"
            className="pointer-events-auto rounded-md border border-cyan-500/30 bg-black/70 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-cyan-200 backdrop-blur hover:bg-black/85"
          >
            Open live map →
          </Link>
        </div>
      </div>
    </div>
  )
}

/**
 * The lede.
 *
 * Answers what is happening, where, how serious, which way it is going and
 * what to do — in that order, in a sentence. The event id, the likelihood
 * percentage and the "ranking not causality" caveat are true and important,
 * but they are the second question, so they sit in advanced view.
 */
function SituationBlock({ hero, trend }: { hero: PollutionEvent; trend: Trend }) {
  const { advanced } = useViewLevel()
  const likelihoodKnown = !hero.provenance?.unavailable?.includes('sourceLikelihood')
  const topLikelihood = likelihoodKnown ? hero.sourceLikelihood[0] : undefined
  const pmKnown = !hero.provenance?.unavailable?.includes('pm25')

  return (
    <div className="shrink-0 border-b border-border px-4 py-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
        Situation
      </p>

      {/* Live titles already end in the region ("Biomass burning event ·
          Punjab"), so appending it produced "... Punjab in Punjab". */}
      <p className="mt-1 text-sm text-text-primary">
        <span className="font-medium">{hero.title}</span>
        {hero.title.includes(hero.region) ? null : <> in {hero.region}</>}
        {pmKnown ? <> — air quality is {getBandLabel(hero.pm25).toLowerCase()}</> : null}, and{' '}
        {TREND_COPY[trend]}.
      </p>

      {topLikelihood ? (
        <p className="mt-1 text-[11px] text-text-secondary">
          The most likely driver is {topLikelihood.source.toLowerCase()}.
          {advanced ? (
            <span className="text-text-muted">
              {' '}
              Likelihood {topLikelihood.probability}% — a ranking across candidate sources, not
              proof of cause.
            </span>
          ) : null}
        </p>
      ) : (
        <p className="mt-1 text-[11px] text-text-secondary">
          The driver has not been attributed for this event.
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Link
          to={`/events/${hero.id}`}
          className="inline-flex items-center gap-1 text-xs text-intel hover:underline"
        >
          {advanced ? `Investigate ${hero.id}` : 'See the evidence'}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
        <Link to="/forecast" className="text-xs text-text-secondary hover:text-intel">
          Where it is heading →
        </Link>
        <Link to="/risk" className="text-xs text-text-secondary hover:text-intel">
          Who is affected →
        </Link>
      </div>
    </div>
  )
}

function EventRow({ event, featured }: { event: PollutionEvent; featured: boolean }) {
  const { advanced } = useViewLevel()
  const pmKnown = !event.provenance?.unavailable?.includes('pm25')
  return (
    <Link
      to={`/events/${event.id}`}
      className={`block border-b border-border/70 px-4 py-3 hover:bg-white/5 ${
        featured ? 'bg-intel/10' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          {advanced && <p className="font-mono text-[10px] text-text-muted">{event.id}</p>}
          <p className="mt-0.5 text-sm text-text-primary">{event.title}</p>
          <p className="mt-0.5 text-[11px] text-text-muted">{event.region}</p>
        </div>
        <StatusBadge variant={event.severity === 'SEVERE' ? 'severe' : 'warning'}>
          {event.severity}
        </StatusBadge>
      </div>
      <p className="mt-1 font-mono text-[11px] text-text-secondary">
        {pmKnown ? `${event.pm25} µg/m³ · AQI ${event.aqi}` : 'PM2.5 —'}
        {' · '}
        {event.status}
      </p>
    </Link>
  )
}

function KpiStrip({
  aqi,
  pm25,
  trend,
  activeCount,
  totalCount,
  totalExposure,
}: {
  aqi: number | undefined
  pm25: number | undefined
  trend: Trend
  activeCount: number
  totalCount: number
  totalExposure: number | null
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="grid shrink-0 grid-cols-2 border-b border-border lg:grid-cols-4"
    >
      <div className="border-b border-border px-4 py-2.5 lg:border-b-0 lg:border-r">
        {aqi != null && pm25 != null ? (
          <KpiStat
            label="AQI"
            value={aqi}
            sublabel={getBandLabel(pm25)}
            className="[&_span.font-mono]:text-2xl"
          />
        ) : (
          <MutedKpi label="AQI" />
        )}
      </div>
      <div className="border-b border-border px-4 py-2.5 lg:border-b-0 lg:border-r">
        {pm25 != null ? (
          <KpiStat
            label="PM2.5"
            value={pm25}
            unit="µg/m³"
            trend={trend === 'rising' ? 'up' : trend === 'falling' ? 'down' : undefined}
            className="[&_span.font-mono]:text-2xl"
          />
        ) : (
          <MutedKpi label="PM2.5" />
        )}
      </div>
      <div className="border-b border-border px-4 py-2.5 lg:border-b-0 lg:border-r">
        {/* The catalog below lists every event, active or not. Showing only
            the active count next to a longer list read as a disagreement. */}
        <KpiStat
          label="Active Events"
          value={activeCount}
          sublabel={`of ${totalCount} tracked`}
          className="[&_span.font-mono]:text-2xl"
        />
      </div>
      <div className="px-4 py-2.5">
        {totalExposure != null ? (
          <KpiStat
            label="At Risk"
            value={Math.round(totalExposure / 100_000) / 10}
            unit="M people"
            decimals={1}
            className="[&_span.font-mono]:text-2xl"
          />
        ) : (
          <div title="No population cells were returned, so exposure cannot be summed.">
            <MutedKpi label="At Risk" />
          </div>
        )}
      </div>
    </motion.div>
  )
}

function MutedKpi({ label }: { label: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wider text-text-muted">{label}</p>
      <p className="font-mono text-2xl font-bold text-text-muted">&mdash;</p>
    </div>
  )
}
