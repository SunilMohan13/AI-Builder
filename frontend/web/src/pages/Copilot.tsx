import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../context/AppContext'
import { useDataMode } from '../context/DataModeContext'
import { Bot, Check, Copy, Send, Trash2 } from 'lucide-react'
import { Card, CardBody, CardHeader } from '../components/common/Card'
import { ScientificBadge } from '../components/common/Badge'
import { FallbackBanner } from '../components/common/Provenance'
import { queryCopilot, suggestedQuestions } from '../services/copilotService'
import type { CopilotMessage } from '../types'

/** Human label for each grounded tool the backend can call. */
const TOOL_LABELS: Record<string, string> = {
  get_air_quality: 'air quality',
  get_wind: 'wind',
  get_active_fires: 'active fires',
  get_hazard_outlook: 'hazard outlook',
  list_active_events: 'active events',
  explain_event: 'event evidence',
}

function toolSummary(calls: CopilotMessage['toolCalls']): string | null {
  if (!calls?.length) return null
  const names = calls.map((c) => TOOL_LABELS[c.name] ?? c.name)
  return Array.from(new Set(names)).join(', ')
}

/** Reports what actually produced the answer.
 *
 *  The previous UI ran a scripted spinner naming "CPCB, FIRMS, IMD, CAMS"
 *  regardless of what the backend consulted, then faked a typewriter over an
 *  already-complete string. Both are gone: this renders the tool calls the
 *  server really made.
 */
function AnswerProvenance({ message }: { message: CopilotMessage }) {
  const tools = toolSummary(message.toolCalls)
  if (message.llmUsed === undefined) return null

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-2 text-xs">
      {message.llmUsed ? (
        <span className="rounded bg-intel/10 px-1.5 py-0.5 text-intel">
          Gemini{message.model ? ` · ${message.model}` : ''}
        </span>
      ) : (
        <span className="rounded bg-bg-panel px-1.5 py-0.5 text-text-muted">
          Evidence lookup — no language model
        </span>
      )}
      {tools && <span className="text-text-muted">Looked up: {tools}</span>}
      {message.grounded === false && (
        <span className="rounded bg-warning/15 px-1.5 py-0.5 text-warning">
          Figures not verified against source data
        </span>
      )}
      {message.degradedReason && (
        <span className="text-text-muted">({message.degradedReason})</span>
      )}
    </div>
  )
}

export function Copilot() {
  const { pendingCopilotQuestion, setPendingCopilotQuestion } = useApp()
  const { mode } = useDataMode()
  const [messages, setMessages] = useState<CopilotMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const seqRef = useRef(0)
  const endRef = useRef<HTMLDivElement>(null)

  // A mode switch changes which backend answers, so a transcript from the
  // other mode would be misleading to leave on screen.
  useEffect(() => {
    setMessages([])
  }, [mode])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isLoading])

  const history = useMemo(
    () =>
      messages.map((m) => ({
        role: m.role as 'user' | 'assistant',
        text: m.content,
      })),
    [messages],
  )

  const sendMessage = async (text: string) => {
    seqRef.current += 1
    const turn = seqRef.current
    setMessages((m) => [...m, { id: `u_${turn}`, role: 'user', content: text }])
    setInput('')
    setIsLoading(true)

    try {
      const response = await queryCopilot(text, history)
      setMessages((m) => [...m, response])
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'the request failed'
      setMessages((m) => [
        ...m,
        {
          id: `err_${turn}`,
          role: 'assistant',
          content: `Copilot did not answer: ${reason}. Demo data is not substituted in Live mode.`,
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    if (!pendingCopilotQuestion || isLoading) return
    const q = pendingCopilotQuestion
    setPendingCopilotQuestion(null)
    void sendMessage(q)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot hand-off from the map
  }, [pendingCopilotQuestion])

  const copy = async (msg: CopilotMessage) => {
    try {
      await navigator.clipboard.writeText(msg.content)
      setCopiedId(msg.id)
      setTimeout(() => setCopiedId(null), 1500)
    } catch {
      // Clipboard is blocked in some embedded contexts; failing quietly is
      // better than an error toast for a convenience action.
    }
  }

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div>
        <div className="flex items-center gap-2">
          <Bot className="h-6 w-6 text-intel" />
          <h1 className="text-xl font-semibold">AeroPulse Intelligence Copilot</h1>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={() => setMessages([])}
              className="ml-auto flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-text-muted hover:text-text-primary"
            >
              <Trash2 className="h-3 w-3" /> Clear
            </button>
          )}
        </div>
        <p className="text-sm text-text-secondary">
          Ask about air quality, wind, fires, hazards or active events. Every figure is looked
          up from AeroPulse data, never recalled by the model.
        </p>
        <FallbackBanner />
      </div>

      <div className="flex flex-wrap gap-2">
        {suggestedQuestions.map((q) => (
          <button
            key={q}
            type="button"
            disabled={isLoading}
            onClick={() => sendMessage(q)}
            className="rounded-full border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-intel/40 hover:text-intel disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      <Card className="flex min-h-0 flex-1 flex-col">
        <CardHeader>
          <ScientificBadge label="INFERRED" />
        </CardHeader>
        <CardBody
          className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto"
          aria-live="polite"
        >
          {messages.length === 0 && !isLoading && (
            <p className="text-sm text-text-muted">
              Select a suggested question or type your own. Answers are grounded in retrieved
              measurements, and every number is checked against its source before it is shown.
            </p>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`group rounded-lg p-3 text-sm ${
                msg.role === 'user'
                  ? 'ml-8 bg-intel/10 text-text-primary'
                  : 'mr-8 bg-bg-elevated whitespace-pre-line'
              }`}
            >
              {msg.content}

              {msg.role === 'assistant' && !!msg.recommendedActions?.length && (
                <div className="mt-3 border-t border-border pt-2">
                  <p className="text-xs font-medium text-text-muted">Recommended actions</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-text-secondary">
                    {msg.recommendedActions.map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ul>
                </div>
              )}

              {msg.role === 'assistant' && msg.confidence?.overall != null && (
                <p className="mt-2 text-xs text-text-muted">
                  Event confidence {Math.round(msg.confidence.overall * 100)}%
                </p>
              )}

              {!!msg.citations?.length && (
                <div className="mt-3 border-t border-border pt-2">
                  <p className="text-xs font-medium text-text-muted">Sources</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {msg.citations.map((c, index) => (
                      // Keyed by index too: the same source legitimately
                      // appears more than once with different timestamps.
                      <span key={`${c.source}_${c.time}_${index}`} className="text-xs text-intel">
                        {c.source}
                        {c.time ? ` · ${c.time}` : ''}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {msg.role === 'assistant' && <AnswerProvenance message={msg} />}

              {msg.role === 'assistant' && (
                <button
                  type="button"
                  onClick={() => copy(msg)}
                  className="mt-2 flex items-center gap-1 text-xs text-text-muted opacity-0 transition group-hover:opacity-100"
                  aria-label="Copy answer"
                >
                  {copiedId === msg.id ? (
                    <>
                      <Check className="h-3 w-3" /> Copied
                    </>
                  ) : (
                    <>
                      <Copy className="h-3 w-3" /> Copy
                    </>
                  )}
                </button>
              )}
            </div>
          ))}

          {isLoading && (
            <div className="mr-8 rounded-lg bg-bg-elevated p-3 text-sm text-text-muted">
              Looking up current measurements…
            </div>
          )}
          <div ref={endRef} />
        </CardBody>
      </Card>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (input.trim() && !isLoading) sendMessage(input.trim())
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about air quality, wind, fires, hazards…"
          disabled={isLoading}
          className="flex-1 rounded-lg border border-border bg-bg-panel px-4 py-2.5 text-sm outline-none focus:border-intel/50 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          className="rounded-lg bg-intel/20 px-4 py-2.5 text-intel hover:bg-intel/30 disabled:opacity-50"
          aria-label="Send"
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
    </div>
  )
}
