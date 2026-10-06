import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react'
import type { DemoPhase, MapLayerVisibility, Notification } from '../types'
import { mockNotifications } from '../data/mockPopulation'
import { fetchAlerts } from '../services/alertService'
import { bumpLivePm25 } from '../services/eventService'
import { bumpSourceFreshness } from '../services/sourceService'
import { isDemo, subscribeDataMode } from '../services/dataMode'
import { MAP_STORY_STEP_MS, MAP_STORY_STEPS } from '../demo/mapStorySteps'

interface AppContextValue {
  hourOffset: number
  setHourOffset: Dispatch<SetStateAction<number>>
  layers: MapLayerVisibility
  setLayers: Dispatch<SetStateAction<MapLayerVisibility>>
  toggleLayer: (key: keyof MapLayerVisibility) => void
  livePaused: boolean
  setLivePaused: (v: boolean) => void
  lastLiveUpdate: Date
  notifications: Notification[]
  demoPhase: DemoPhase
  setDemoPhase: Dispatch<SetStateAction<DemoPhase>>
  demoRunning: boolean
  demoPaused: boolean
  startDemo: () => void
  pauseDemo: () => void
  skipDemo: () => void
  exitDemo: () => void
  judgeTourRunning: boolean
  startJudgeTour: () => void
  stopJudgeTour: () => void
  tourCaption: string | null
  setTourCaption: (caption: string | null) => void
  pendingCopilotQuestion: string | null
  setPendingCopilotQuestion: (q: string | null) => void
  demoIntensity: number
  commandPaletteOpen: boolean
  setCommandPaletteOpen: (v: boolean) => void
  notificationsOpen: boolean
  setNotificationsOpen: (v: boolean) => void
  selectedFireId: string | null
  setSelectedFireId: (id: string | null) => void
  selectedGridId: string | null
  setSelectedGridId: (id: string | null) => void
  sidebarCollapsed: boolean
  setSidebarCollapsed: (v: boolean) => void
  mobileNavOpen: boolean
  setMobileNavOpen: (v: boolean) => void
  windBearingOffset: number
  setWindBearingOffset: (deg: number) => void
  showBaselinePlume: boolean
  setShowBaselinePlume: (v: boolean) => void
  showGrapZone: boolean
  setShowGrapZone: (v: boolean) => void
  showExposureRibbon: boolean
  setShowExposureRibbon: (v: boolean) => void
  showFireSeasonGlobe: boolean
  setShowFireSeasonGlobe: (v: boolean) => void
  mapStoryRunning: boolean
  mapStoryCaption: string | null
  startMapStory: () => void
  stopMapStory: () => void
}

const AppContext = createContext<AppContextValue | null>(null)

const DEMO_PHASES: DemoPhase[] = [
  'fire',
  'anomaly',
  'wind',
  'plume',
  'confirmed',
  'forecast',
  'risk',
  'complete',
]

const PHASE_DURATION = 2200

export function AppProvider({ children }: { children: ReactNode }) {
  const [hourOffset, setHourOffset] = useState(0)
  // Opens on "what is in the air and what is burning". Wind and the
  // predicted plume answer the next question, so they are a deliberate
  // second click rather than four layers stacked on arrival. The map story
  // and the Forecast page switch them on themselves.
  const [layers, setLayers] = useState<MapLayerVisibility>({
    pollution: true,
    fires: true,
    wind: false,
    forecast: false,
    industry: false,
    population: false,
  })
  const [livePaused, setLivePaused] = useState(false)
  const [lastLiveUpdate, setLastLiveUpdate] = useState(new Date())
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [demoPhase, setDemoPhase] = useState<DemoPhase>('idle')
  const [demoRunning, setDemoRunning] = useState(false)
  const [demoPaused, setDemoPaused] = useState(false)
  const [judgeTourRunning, setJudgeTourRunning] = useState(false)
  const [tourCaption, setTourCaption] = useState<string | null>(null)
  const [pendingCopilotQuestion, setPendingCopilotQuestion] = useState<string | null>(null)
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [selectedFireId, setSelectedFireId] = useState<string | null>(null)
  const [selectedGridId, setSelectedGridId] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [windBearingOffset, setWindBearingOffset] = useState(0)
  const [showBaselinePlume, setShowBaselinePlume] = useState(false)
  const [showGrapZone, setShowGrapZone] = useState(true)
  const [showExposureRibbon, setShowExposureRibbon] = useState(true)
  const [showFireSeasonGlobe, setShowFireSeasonGlobe] = useState(false)
  const [mapStoryRunning, setMapStoryRunning] = useState(false)
  const [mapStoryCaption, setMapStoryCaption] = useState<string | null>(null)
  const [, setMapStoryIndex] = useState(0)
  const [, setPhaseIndex] = useState(0)

  // Alerts come from the API in Live and from the scripted set in Demo.
  // `fetchAlerts` resolves that, so a live failure lands in the fallback
  // banner instead of silently emptying the drawer.
  const loadAlerts = useCallback(() => {
    let cancelled = false
    fetchAlerts()
      .then((items) => {
        if (!cancelled) setNotifications(items)
      })
      .catch(() => {
        // resolve() has already recorded the failure for the banner.
        if (!cancelled) setNotifications([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const cancel = loadAlerts()
    const unsubscribe = subscribeDataMode(() => loadAlerts())
    return () => {
      cancel()
      unsubscribe()
    }
  }, [loadAlerts])

  const toggleLayer = useCallback((key: keyof MapLayerVisibility) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }))
  }, [])

  const demoIntensity = useMemo(() => {
    if (demoPhase === 'idle') return 1
    if (demoPhase === 'fire') return 0.3
    if (demoPhase === 'anomaly') return 0.6
    if (demoPhase === 'wind') return 0.7
    if (demoPhase === 'plume') return 0.85
    return 1
  }, [demoPhase])

  const startDemo = useCallback(() => {
    setDemoRunning(true)
    setDemoPaused(false)
    setPhaseIndex(0)
    setDemoPhase('fire')
    setHourOffset(0)
    setNotifications(mockNotifications)
    setLayers((l) => ({ ...l, fires: true, wind: false, forecast: false, pollution: true }))
  }, [])

  const exitDemo = useCallback(() => {
    setDemoRunning(false)
    setDemoPaused(false)
    setJudgeTourRunning(false)
    setTourCaption(null)
    setPendingCopilotQuestion(null)
    setDemoPhase('idle')
    setPhaseIndex(0)
    setHourOffset(0)
  }, [])

  const stopJudgeTour = useCallback(() => {
    setJudgeTourRunning(false)
    setTourCaption(null)
    setPendingCopilotQuestion(null)
    setDemoRunning(false)
    setDemoPhase('complete')
  }, [])

  const startJudgeTour = useCallback(() => {
    setJudgeTourRunning(true)
    setDemoRunning(true)
    setDemoPaused(false)
    setPhaseIndex(0)
    setDemoPhase('fire')
    setHourOffset(0)
    setNotifications(mockNotifications)
    setLayers({
      pollution: true,
      fires: true,
      wind: false,
      forecast: false,
      industry: false,
      population: false,
    })
  }, [])

  const skipDemo = useCallback(() => {
    setDemoPhase('complete')
    setPhaseIndex(DEMO_PHASES.length - 1)
    setHourOffset(3)
    setLayers({ pollution: true, fires: true, wind: true, forecast: true, industry: false, population: true })
  }, [])

  const pauseDemo = useCallback(() => setDemoPaused((p) => !p), [])

  const stopMapStory = useCallback(() => {
    setMapStoryRunning(false)
    setMapStoryCaption(null)
    setMapStoryIndex(0)
  }, [])

  const startMapStory = useCallback(() => {
    setMapStoryRunning(true)
    setMapStoryIndex(0)
    const first = MAP_STORY_STEPS[0]
    setMapStoryCaption(first.caption)
    setHourOffset(first.hour)
    if (first.layers) setLayers((l) => ({ ...l, ...first.layers }))
  }, [])

  useEffect(() => {
    if (!mapStoryRunning) return
    const timer = setInterval(() => {
      setMapStoryIndex((i) => {
        const next = i + 1
        if (next >= MAP_STORY_STEPS.length) {
          setMapStoryRunning(false)
          setMapStoryCaption('Map story complete · scrub timeline or run again')
          return i
        }
        const step = MAP_STORY_STEPS[next]
        setMapStoryCaption(step.caption)
        setHourOffset(step.hour)
        if (step.layers) setLayers((l) => ({ ...l, ...step.layers }))
        return next
      })
    }, MAP_STORY_STEP_MS)
    return () => clearInterval(timer)
  }, [mapStoryRunning])

  useEffect(() => {
    if (!demoRunning || demoPaused || judgeTourRunning) return
    const timer = setInterval(() => {
      setPhaseIndex((i) => {
        const next = i + 1
        if (next >= DEMO_PHASES.length) {
          setDemoRunning(false)
          setDemoPhase('complete')
          return i
        }
        const phase = DEMO_PHASES[next]
        setDemoPhase(phase)
        if (phase === 'wind') setLayers((l) => ({ ...l, wind: true }))
        if (phase === 'plume' || phase === 'forecast') {
          setLayers((l) => ({ ...l, forecast: true }))
          setHourOffset(2)
        }
        if (phase === 'risk') {
          setLayers((l) => ({ ...l, population: true }))
          setHourOffset(4)
          setNotifications((current) =>
            current.some((n) => n.id === 'demo-alert')
              ? current
              : [
                  {
                    id: 'demo-alert',
                    title: 'Population risk threshold exceeded',
                    message: '2.4M people in projected plume path — Delhi NCR',
                    time: 'just now',
                    route: '/risk',
                    icon: 'warning',
                  },
                  ...current,
                ],
          )
        }
        if (phase === 'confirmed') setHourOffset(1)
        return next
      })
    }, PHASE_DURATION)
    return () => clearInterval(timer)
  }, [demoRunning, demoPaused, judgeTourRunning])

  useEffect(() => {
    if (livePaused) return
    const timer = setInterval(() => {
      if (isDemo()) {
        bumpLivePm25()
        bumpSourceFreshness()
      }
      setLastLiveUpdate(new Date())
    }, 12000)
    return () => clearInterval(timer)
  }, [livePaused])

  const value: AppContextValue = {
    hourOffset,
    setHourOffset,
    layers,
    setLayers,
    toggleLayer,
    livePaused,
    setLivePaused,
    lastLiveUpdate,
    notifications,
    demoPhase,
    setDemoPhase,
    demoRunning,
    demoPaused,
    startDemo,
    pauseDemo,
    skipDemo,
    exitDemo,
    judgeTourRunning,
    startJudgeTour,
    stopJudgeTour,
    tourCaption,
    setTourCaption,
    pendingCopilotQuestion,
    setPendingCopilotQuestion,
    demoIntensity,
    commandPaletteOpen,
    setCommandPaletteOpen,
    notificationsOpen,
    setNotificationsOpen,
    selectedFireId,
    setSelectedFireId,
    selectedGridId,
    setSelectedGridId,
    sidebarCollapsed,
    setSidebarCollapsed,
    mobileNavOpen,
    setMobileNavOpen,
    windBearingOffset,
    setWindBearingOffset,
    showBaselinePlume,
    setShowBaselinePlume,
    showGrapZone,
    setShowGrapZone,
    showExposureRibbon,
    setShowExposureRibbon,
    showFireSeasonGlobe,
    setShowFireSeasonGlobe,
    mapStoryRunning,
    mapStoryCaption,
    startMapStory,
    stopMapStory,
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
