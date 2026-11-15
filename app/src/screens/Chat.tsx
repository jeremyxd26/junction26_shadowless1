import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type FormEvent, type ReactNode } from 'react'
import { InfoIcon, QUESTION_CHIP, TurnView } from '../components/AnswerView.tsx'
import { ComposerBillButton } from '../components/ComposerBillButton.tsx'
import { OpeningFold } from '../components/OpeningFold.tsx'
import { ComposerMicButton } from '../components/ComposerMicButton.tsx'
import { ScrollToLatest } from '../components/ScrollToLatest.tsx'
import { Toast } from '../components/Toast.tsx'
import { VoiceMode } from '../components/VoiceMode.tsx'
import { chatStrings } from '../lib/chatStrings.ts'
import { micStrings } from '../lib/micStrings.ts'
import { notifyAsked } from '../lib/threadEvents.ts'
import { setParams } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import { stopSpeaking, unlockVoice } from '../lib/speech.ts'
import { isClientTurn, lastAskId } from '../lib/thread.ts'
import { landBelowHeader } from '../lib/threadScroll.ts'
import { NEAR_LIMIT, fitPaste } from '../lib/questionLength.ts'
import { audioContext, withSpoken } from '../lib/stt.ts'
import { MAX_QUESTION, type ChatSession } from '../lib/useChat.ts'
import { voiceModeAvailable } from '../lib/voiceMode.ts'
import { voiceModeStrings } from '../lib/voiceModeStrings.ts'
import { VoiceSession, type VoiceEnd } from '../lib/voiceSession.ts'

/** How long the toast stays after voice mode closed by itself. */
const VOICE_TOAST_MS = 6000

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
  // A paste over the limit was cut to fit; the note stays until the draft changes again (#716).
  const [cut, setCut] = useState(false)
  // While the mic records or sends, its bar takes the whole composer row (#751).
  const [voice, setVoice] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const composer = useRef<HTMLFormElement>(null)
  const sendButton = useRef<HTMLButtonElement>(null)
  const left = MAX_QUESTION - draft.length
  const note = cut ? s.cut : left <= NEAR_LIMIT ? s.charactersLeft(left) : null

  // Voice mode (#811): with an empty input the send button opens it (a live build with a microphone API).
  const vs = voiceModeStrings(lang)
  const [voiceSession, setVoiceSession] = useState<VoiceSession | null>(null)
  const [voiceToast, setVoiceToast] = useState<string | null>(null)
  const talk = voiceModeAvailable(customerId) && !draft.trim() && !busy

  /** Why voice mode closed by itself, as the toast says it; the input is usable again. */
  const voiceEnded = (reason: VoiceEnd) =>
    reason.kind === 'nothing' ? vs.nothing : reason.kind === 'answer' ? vs.answerFailed : micStrings(lang).failures[reason.failure]

  // Everything that needs the tap itself happens here: the audio contexts (iOS runs only those made in a
  // gesture), the device voice's unlock and the microphone request.
  const openVoice = () => {
    if (!customerId) return
    setVoiceToast(null)
    stopSpeaking()
    unlockVoice()
    const session = new VoiceSession(
      {
        customerId,
        lang,
        ask: send,
        closed: (reason) => {
          setVoiceSession(null)
          if (reason) setVoiceToast(voiceEnded(reason))
          requestAnimationFrame(() => sendButton.current?.focus())
        },
      },
      audioContext(),
      turns,
    )
    setVoiceSession(session)
    void session.start()
  }

  // The toast goes by itself after a while, and with the next question.
  useEffect(() => {
    if (!voiceToast) return
    const timer = window.setTimeout(() => setVoiceToast(null), VOICE_TOAST_MS)
    return () => window.clearTimeout(timer)
  }, [voiceToast])

  /** A paste that would go over 500 characters is cut to fit, at a word break when one is near. */
  const paste = (event: ClipboardEvent<HTMLInputElement>) => {
    const field = event.currentTarget
    const fitted = fitPaste(draft, field.selectionStart ?? draft.length, field.selectionEnd ?? draft.length, event.clipboardData.getData('text'))
    if (!fitted) return
    event.preventDefault()
    setDraft(fitted.value)
    setCut(true)
    requestAnimationFrame(() => field.setSelectionRange(fitted.caret, fitted.caret))
  }

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
  // Only the first answer carries the visible "Sentti" label, so a long thread reads like a conversation.
  const firstAsk = turns.find((turn) => !isClientTurn(turn))?.id
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
    setCut(false)
    setVoiceToast(null)
    input.current?.blur()
  }

  const empty = turns.length === 0 && !question
  const starters = suggestions.slice(0, 3)

  return (
    <div className="flex flex-col gap-6 pb-4">
      {opening ? (
        <>
          <OpeningFold canFold={turns.length > 0} foldKey={lastId}>
            {opening}
          </OpeningFold>
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
              firstAnswer={turn.id === firstAsk}
              suggestions={suggestions}
              onAsk={send}
              onRetry={() => retry(turn.id, turn.question)}
            />
          </div>
        )
      })}

      <ScrollToLatest thinking={busy} enabled={turns.length > 0} composer={composer} />
      <form
        ref={composer}
        onSubmit={submit}
        // The icon buttons and their gaps keep their pixel size at any text size, so the input keeps
        // its room at 200 % text (#705); the text and the input grow. The mic sits inside the input's pill,
        // and the side gutters stay 16 px, so the input keeps over 60 % of the row at 320 px (#751).
        className="fixed inset-x-0 bottom-0 z-30 mx-auto flex max-w-[480px] flex-wrap items-center gap-[8px] border-t border-line bg-page px-[16px] pt-3 pb-[calc(env(safe-area-inset-bottom)+12px)]"
      >
        {/* How much room is left near the limit, or that a paste was cut (#716): a line of its own above the row. */}
        {note && (
          <p id="chat-input-note" className="order-first basis-full text-sm text-muted">
            {note}
          </p>
        )}
        {/* A cut paste is announced once; the count is read with the field, not on every key. */}
        <p role="status" className="sr-only">
          {cut ? s.cut : ''}
        </p>
        <div className={voice ? 'hidden' : 'contents'}>
          <ComposerBillButton />
        </div>
        {/* Not positioned, so the mic's status line still sits above the whole composer. */}
        <div
          className={
            voice
              ? 'flex min-w-0 flex-1 items-center'
              : // The focus ring goes around the whole pill, mic included, not just the typing area.
                'flex h-12 min-w-0 flex-1 items-center rounded-pill border border-line-strong bg-surface pr-px has-[input:focus-visible]:[outline:var(--focus-ring-width)_solid_var(--color-brand)] has-[input:focus-visible]:outline-offset-2'
          }
        >
          <label htmlFor="chat-input" className="sr-only">
            {s.inputLabel}
          </label>
          <input
            id="chat-input"
            ref={input}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
              setCut(false)
            }}
            onPaste={paste}
            aria-describedby={note ? 'chat-input-note' : undefined}
            maxLength={MAX_QUESTION}
            placeholder={s.placeholder}
            enterKeyHint="send"
            autoComplete="off"
            className={`${voice ? 'hidden' : ''} h-full min-w-0 flex-1 rounded-pill bg-transparent outline-none pr-1 pl-[min(1.25rem,20px)] text-base text-ellipsis text-ink-2 placeholder:text-muted last:pr-[min(1.25rem,20px)]`}
          />
          <ComposerMicButton
            onText={(text) => {
              setDraft((current) => withSpoken(current, text))
              setCut(false)
            }}
            onActive={setVoice}
          />
        </div>
        {voice ? null : busy ? (
          <button
            type="button"
            onClick={stop}
            aria-label={s.stop}
            className="inline-flex size-[48px] shrink-0 items-center justify-center rounded-pill bg-deep text-on-deep focus-visible:outline-mint"
          >
            <span aria-hidden="true" className="size-[16px] rounded-[3px] bg-on-deep" />
          </button>
        ) : (
          // With an empty input (and voice mode available) the same round button opens voice mode: a wave
          // in place of the arrow, the two icons cross-fading as text comes and goes (#811).
          <button
            ref={sendButton}
            type={talk ? 'button' : 'submit'}
            onClick={talk ? openVoice : undefined}
            aria-label={talk ? vs.start : s.send}
            className="relative inline-flex size-[48px] shrink-0 items-center justify-center rounded-pill bg-deep text-on-deep focus-visible:outline-mint"
          >
            <SendIcon shown={!talk}>
              <path d="M12 19V5M5.5 11.5L12 5l6.5 6.5" strokeLinecap="round" strokeLinejoin="round" />
            </SendIcon>
            <SendIcon shown={talk}>
              <path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" strokeLinecap="round" />
            </SendIcon>
          </button>
        )}
      </form>
      {voiceSession && <VoiceMode session={voiceSession} turns={turns} />}
      {voiceToast && !voiceSession && <Toast text={voiceToast} numbers={{}} onClose={() => setVoiceToast(null)} />}
    </div>
  )
}

/** One of the send button's two icons, stacked; the hidden one fades and shrinks out (no motion when reduced). */
function SendIcon({ shown, children }: { shown: boolean; children: ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.25"
      className={`absolute size-[24px] transition-[opacity,scale] duration-(--duration-fast) motion-reduce:transition-none ${
        shown ? 'scale-100 opacity-100' : 'scale-50 opacity-0'
      }`}
    >
      {children}
    </svg>
  )
}
