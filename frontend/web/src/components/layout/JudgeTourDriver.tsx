import { useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../../context/AppContext'
import { judgeTourSteps } from '../../demo/judgeTourSteps'
import { useHeroEventId } from '../../hooks/useHeroEventId'

/** Auto-navigates the 90s judge tour while syncing demo phase, map layers, and timeline. */
export function JudgeTourDriver() {
  const navigate = useNavigate()
  const heroEventId = useHeroEventId()
  const steps = useMemo(() => judgeTourSteps(heroEventId), [heroEventId])
  const {
    judgeTourRunning,
    stopJudgeTour,
    setDemoPhase,
    setHourOffset,
    setLayers,
    setTourCaption,
    setPendingCopilotQuestion,
  } = useApp()
  const stepRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!judgeTourRunning) {
      stepRef.current = 0
      if (timerRef.current) clearTimeout(timerRef.current)
      return
    }

    const runStep = (index: number) => {
      const step = steps[index]
      if (!step) {
        stopJudgeTour()
        setDemoPhase('complete')
        setTourCaption(null)
        return
      }

      stepRef.current = index
      setDemoPhase(step.phase)
      setTourCaption(step.caption)
      if (step.hourOffset !== undefined) setHourOffset(step.hourOffset)
      if (step.layers) setLayers((prev) => ({ ...prev, ...step.layers }))
      if (step.copilotQuestion) setPendingCopilotQuestion(step.copilotQuestion)
      else setPendingCopilotQuestion(null)

      navigate(step.route)

      timerRef.current = setTimeout(() => runStep(index + 1), step.durationMs)
    }

    setDemoPhase('fire')
    runStep(0)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [
    judgeTourRunning,
    navigate,
    steps,
    setDemoPhase,
    setHourOffset,
    setLayers,
    setTourCaption,
    setPendingCopilotQuestion,
    stopJudgeTour,
  ])

  return null
}
