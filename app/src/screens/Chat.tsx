import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { InfoIcon, QUESTION_CHIP, TurnView } from '../components/AnswerView.tsx'
import { ComposerBillButton } from '../components/ComposerBillButton.tsx'
import { chatStrings } from '../lib/chatStrings.ts'
import { notifyAsked } from '../lib/threadEvents.ts'
import { setParams } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import { stopSpeaking } from '../lib/speech.ts'
import { lastAskId } from '../lib/thread.ts'
import { landBelowHeader } from '../lib/threadScroll.ts'
import { MAX_QUESTION, type ChatSession } from '../lib/useChat.ts'

interface Props {
  chat: ChatSession
  /** `?q=`: a question picked on the overview, sent as soon as the persona is known. */
  question: string | null
  /** The first message of every chat: the overview's `ai_disclosure` (contract section 6), or the app's own. */
  disclosure: string
  /** Starter questions: the overview's suggestions, or the partner's questions. */
  suggestions: string[]
  /**
   * Sentti's opening turn (turn 0), shown before the question turns. With an opening there is no
   * empty state and no separate disclosure line: the opening carries the disclosure.
   */
  opening?: ReactNode
  /** Starter chips under the opening while nothing is asked yet (when the overview failed). */
  starters?: string[]
}

/**
 * The thread on POST /api/ask, opened by Sentti's opening turn. It scrolls with the document (no
 * inner scroll container), and the view never scrolls while an answer streams in.
 */
export function Chat({ chat, question, disclosure, suggestions, opening, starters: openingStarters }: Props) {
  const { lang, customerId } = useSettings()
  const s = chatStrings(lang)
  const { turns, busy, retry, stop } = chat
  // Every question goes through here, so the opening can close its Undo toast (#315).
  const chatSend = chat.send
  const send = useCallback(
    (question: string) => {
      notifyAsked()
      chatSend(question)
    },
    [chatSend],
  )
  const [draft, setDraft] = useState('')
  const input = useRef<HTMLInputElement>(null)

  // Send `?q=` once, then drop it, so Back or a reload does not ask again. The timeout is
  // cleared if the effect is torn down first (React's strict mode runs effects twice).
  useEffect(() => {
    if (!question || !customerId) return
    const timer = window.setTimeout(() => {
      send(question)
      setParams({ q: null })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [question, customerId, send])

  // A new question is brought to the top once; the answer then grows below it without moving
  // the view (DESIGN.md: no autoscroll while streaming). Under an opening even the first one is.
  const lastId = turns.at(-1)?.id
  const many = turns.length > 1 || Boolean(opening)
  // Follow-ups and the answer's announcement belong to the last ask turn, even when a client turn
  // (#319) came after it while it was still streaming (#332).
  const latestAsk = lastAskId(turns)
  // It lands below the header's measured height, so large text does not hide it under the header (#332).
  useEffect(() => {
    if (lastId === undefined || !many) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const turn = document.querySelector(`[data-turn="${lastId}"]`)
    if (turn) landBelowHeader(turn, !reduce)
  }, [lastId, many])

  // Every new question stops an answer that is being read aloud, the latest one or an older one.
  useEffect(() => {
    if (lastId !== undefined) stopSpeaking()
  }, [lastId])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    if (!draft.trim()) {
      input.current?.focus()
      return
    }
    send(draft)
    setDraft('')
    input.current?.blur()
  }

  const empty = turns.length === 0 && !question
  const starters = suggestions.slice(0, 3)

  return (
    <div className="flex flex-col gap-6 pb-4">
      {opening ? (
        <>
          {opening}
          {empty && openingStarters && openingStarters.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {openingStarters.slice(0, 3).map((starter) => (
                <li key={starter}>
                  <button type="button" className={QUESTION_CHIP} onClick={() => send(starter)}>
                    {starter}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : empty ? (
        // An empty chat says what Sentti can and can't do, near the thumb.
        <div className="flex min-h-[calc(100dvh-220px)] flex-col justify-end gap-4">
          <p className="flex gap-2 text-xs text-muted">
            <InfoIcon />
            {disclosure}
          </p>
          <p className="rounded-lg border border-line bg-surface p-4 text-base text-ink-2">{s.can}</p>
          <ul className="flex flex-wrap gap-2">
            {starters.map((starter) => (
              <li key={starter}>
                <button type="button" className={QUESTION_CHIP} onClick={() => send(starter)}>
                  {starter}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="flex gap-2 text-xs text-muted">
          <InfoIcon />
          {disclosure}
        </p>
      )}

      {turns.map((turn, index) => {
        const last = index === turns.length - 1
        return (
          <div key={turn.id} className={last && many ? 'min-h-[calc(100dvh-180px)]' : undefined}>
            <TurnView
              turn={turn}
              latest={turn.id === latestAsk}
              suggestions={suggestions}
              onAsk={send}
              onRetry={() => retry(turn.id, turn.question)}
            />
          </div>
        )
      })}

      <form
        onSubmit={submit}
        // The icon buttons and their gaps keep their pixel size at any text size, so the input keeps
        // its room at 200 % text (#705); the text and the input grow.
        className="fixed inset-x-0 bottom-0 z-30 mx-auto flex max-w-[480px] items-center gap-[12px] border-t border-line bg-page px-4 pt-3 pb-[calc(env(safe-area-inset-bottom)+12px)]"
      >
        <ComposerBillButton />
        <label htmlFor="chat-input" className="sr-only">
          {s.inputLabel}
        </label>
        <input
          id="chat-input"
          ref={input}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={MAX_QUESTION}
          placeholder={s.placeholder}
          enterKeyHint="send"
          autoComplete="off"
          className="h-12 min-w-0 flex-1 rounded-pill border border-line-strong bg-surface px-[min(1.25rem,20px)] text-base text-ellipsis text-ink-2 placeholder:text-muted"
        />
        {busy ? (
          <button
            type="button"
            onClick={stop}
            aria-label={s.stop}
            className="inline-flex size-[48px] shrink-0 items-center justify-center rounded-pill bg-deep text-on-deep focus-visible:outline-mint"
          >
            <span aria-hidden="true" className="size-[16px] rounded-[3px] bg-on-deep" />
          </button>
        ) : (
          <button
            type="submit"
            aria-label={s.send}
            className="inline-flex size-[48px] shrink-0 items-center justify-center rounded-pill bg-deep text-on-deep focus-visible:outline-mint"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[24px]" fill="none" stroke="currentColor" strokeWidth="2.25">
              <path d="M12 19V5M5.5 11.5L12 5l6.5 6.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
      </form>
    </div>
  )
}
