import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Bot, Send, Trash2, X } from 'lucide-react'
import { ApiError } from '../api/client'
import { askCopilot } from '../api/regions'
import type { CopilotAnswer } from '../api/regionTypes'
import { Card } from '../components/common/Card'
import { LiveFailureBanner } from '../components/common/Banners'
import { useDataMode } from '../context/DataModeContext'
import { useRegion } from '../context/RegionContext'
import { loadRecording } from '../data/regions'
import { resolve } from '../services/resolve'

const INCIDENT_QUESTION = 'Explain this incident.'

type Message =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; text: string; answer: CopilotAnswer | null; failed?: boolean }

/** The Live list mirrors what the Demo generator records, so both modes offer the same questions. */
function liveSuggestions(displayName: string): string[] {
  return [
    `What is the air quality in ${displayName} right now?`,
    'Which pollution events are active?',
    'Are there active fires?',
  ]
}

function AnswerProvenance({ answer }: { answer: CopilotAnswer }) {
  const tools = [...new Set(answer.tool_calls.map((c) => c.name))]
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-2 text-[11px]">
      {answer.llm_used ? (
        <span className="rounded bg-intel/10 px-1.5 py-0.5 text-intel">Gemini{answer.model ? ` · ${answer.model}` : ''}</span>
      ) : (
        <span className="rounded bg-bg-panel px-1.5 py-0.5 text-text-muted">Evidence lookup — no language model</span>
      )}
      {tools.length > 0 && <span className="text-text-muted">Tools: {tools.join(', ')}</span>}
      {answer.grounding && (
        <span className={answer.grounding.grounded ? 'text-emerald-300/80' : 'text-amber-300'}>
          {answer.grounding.grounded
            ? `grounded (${answer.grounding.numbers_checked} numbers checked)`
            : 'figures not verified against tool results'}
        </span>
      )}
      {answer.degraded_reason && <span className="text-text-muted">({answer.degraded_reason})</span>}
    </div>
  )
}

export function Copilot() {
  const { mode } = useDataMode()
  const { region, regionId } = useRegion()
  const [params, setParams] = useSearchParams()
  const incidentId = params.get('incident')
  // A conversation belongs to one mode, region and incident; changing any starts a new one.
  const scope = `${mode}|${regionId ?? ''}|${incidentId ?? ''}`
  const [conversation, setConversation] = useState<{ scope: string; messages: Message[] }>({
    scope,
    messages: [],
  })
  const messages = conversation.scope === scope ? conversation.messages : []
  const setMessages = (update: (m: Message[]) => Message[]) =>
    setConversation((c) => ({ scope, messages: update(c.scope === scope ? c.messages : []) }))
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  const end = useRef<HTMLDivElement>(null)

  const suggestions = useQuery({
    queryKey: ['copilot-suggestions', mode, regionId, region?.display_name],
    enabled: regionId !== null,
    queryFn: async () => {
      if (mode === 'demo') {
        const recording = regionId ? loadRecording(regionId) : null
        return recording ? (await recording).suggested_questions : []
      }
      return region ? liveSuggestions(region.display_name) : []
    },
  })

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  const send = async (text: string) => {
    if (!regionId) return
    seq.current += 1
    const turn = seq.current
    const history = messages.map((m) => ({ role: m.role, text: m.text }))
    setMessages((m) => [...m, { id: `u${turn}`, role: 'user', text }])
    setInput('')
    setBusy(true)
    try {
      const answer = await resolve('copilot', regionId, (t) => askCopilot(t, text, regionId, incidentId, history))
      setMessages((m) => [...m, { id: `a${turn}`, role: 'assistant', text: answer.answer, answer }])
    } catch (error) {
      const reason = error instanceof ApiError ? error.reason : 'the request failed'
      setMessages((m) => [
        ...m,
        { id: `e${turn}`, role: 'assistant', text: `No answer: ${reason}.`, answer: null, failed: true },
      ])
    } finally {
      setBusy(false)
    }
  }

  const chips = [...(incidentId ? [INCIDENT_QUESTION] : []), ...(suggestions.data ?? [])]

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div>
        <div className="flex items-center gap-2">
          <Bot className="h-6 w-6 text-intel" />
          <h1 className="text-xl font-semibold">Ask AeroPulse</h1>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={() => setMessages(() => [])}
              className="ml-auto flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-text-muted hover:text-text-primary"
            >
              <Trash2 className="h-3 w-3" /> Clear
            </button>
          )}
        </div>
        <p className="text-sm text-text-secondary">
          Questions about {region?.display_name ?? 'this region'}. Every figure comes from an
          AeroPulse tool lookup and is checked against it before it is shown.
          {mode === 'demo' && ' Demo replays answers recorded from the real API; other questions need Live.'}
        </p>
      </div>
      <LiveFailureBanner />
      {incidentId && (
        <div className="flex items-center gap-2 self-start rounded-md border border-intel/30 bg-intel/5 px-2 py-1 text-xs">
          <span className="text-text-muted">Incident</span>
          <span className="font-mono">{incidentId}</span>
          <button
            type="button"
            aria-label="Clear incident"
            onClick={() =>
              setParams((p) => {
                const next = new URLSearchParams(p)
                next.delete('incident')
                return next
              })
            }
          >
            <X className="h-3 w-3 text-text-muted" />
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {chips.map((q) => (
          <button
            key={q}
            type="button"
            disabled={busy}
            onClick={() => void send(q)}
            className="rounded-full border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-intel/40 hover:text-intel disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      <Card className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" aria-live="polite">
          {messages.length === 0 && !busy && (
            <p className="text-sm text-text-muted">Pick a suggested question or type your own.</p>
          )}
          {messages.map((m) => (
            <div
              key={m.id}
              className={`rounded-lg p-3 text-sm ${
                m.role === 'user'
                  ? 'ml-8 bg-intel/10'
                  : `mr-8 whitespace-pre-line bg-bg-elevated ${'failed' in m && m.failed ? 'text-amber-200' : ''}`
              }`}
            >
              {m.text}
              {m.role === 'assistant' && m.answer && m.answer.evidence.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-intel">
                  {m.answer.evidence.map((c, i) => (
                    <span key={`${c.source}-${c.time}-${i}`}>
                      {c.source}
                      {c.time ? ` · ${c.time}` : ''}
                    </span>
                  ))}
                </div>
              )}
              {m.role === 'assistant' && m.answer && m.answer.limitations.length > 0 && (
                <details className="mt-2 text-[11px] text-text-muted">
                  <summary className="cursor-pointer">Limitations</summary>
                  <ul className="mt-1 list-disc pl-4">
                    {m.answer.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </details>
              )}
              {m.role === 'assistant' && m.answer && <AnswerProvenance answer={m.answer} />}
            </div>
          ))}
          {busy && <div className="mr-8 rounded-lg bg-bg-elevated p-3 text-sm text-text-muted">Looking it up…</div>}
          <div ref={end} />
        </div>
      </Card>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (input.trim() && !busy) void send(input.trim())
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about air quality, fires, events or an incident…"
          maxLength={2000}
          disabled={busy}
          className="flex-1 rounded-lg border border-border bg-bg-panel px-4 py-2.5 text-sm outline-none focus:border-intel/50 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-lg bg-intel/20 px-4 py-2.5 text-intel hover:bg-intel/30 disabled:opacity-50"
          aria-label="Send"
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
    </div>
  )
}
