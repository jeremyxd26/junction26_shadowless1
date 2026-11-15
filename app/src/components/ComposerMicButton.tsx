import { useEffect, useRef, useState, type Ref } from 'react'
import { micStrings } from '../lib/micStrings.ts'
import { useSettings } from '../lib/settings.ts'
import {
  AUDIO_BITS_PER_SECOND,
  MAX_RECORD_MS,
  STT_LIVE,
  STT_TIMEOUT_MS,
  SttFailed,
  audioContext,
  canRecord,
  clipTooShort,
  formatElapsed,
  levelMeter,
  micFailure,
  pickType,
  transcribe,
  type LevelMeter,
  type SttFailure,
} from '../lib/stt.ts'

type Phase = 'idle' | 'starting' | 'recording' | 'sending'

const FAILURE_MS = 6000
/** The waveform: this many bars, the newest on the right, one every TICK_MS. */
const BARS = 24
const TICK_MS = 100

interface Recording {
  recorder: MediaRecorder
  stream: MediaStream
  timer: number
  cancelled: boolean
  /** When recording began, to drop a clip too short to hold a question (#759). */
  started: number
  ticker: number
  meter: LevelMeter | null
}

function stopTracks(stream: MediaStream) {
  for (const track of stream.getTracks()) track.stop()
}

/** Stops everything a recording holds except the recorder itself: the timers, the level meter, the tracks. */
function release(session: Recording) {
  window.clearTimeout(session.timer)
  window.clearInterval(session.ticker)
  session.meter?.close()
  session.meter = null
  stopTracks(session.stream)
}

/**
 * A mic in the composer (#735), as an icon at the input's right edge (#751). A tap records the question: the
 * input and the paperclip give way to a recording bar (`onActive`) with cancel, a live waveform, a timer and
 * stop. Stop, or 15 s, sends the clip, with three dots while it is turned into text; the words land in the
 * composer's input and the user taps send. Cancel sends nothing. A refused microphone, a failed request or no
 * speech shows a short line above the composer, which stays usable throughout. 44 px targets at any text size.
 * Only in a live build with a microphone API (a mock build has no core to send the clip to).
 */
export function ComposerMicButton({ onText, onActive }: { onText: (text: string) => void; onActive?: (active: boolean) => void }) {
  const { lang, customerId } = useSettings()
  const s = micStrings(lang)
  const [phase, setPhase] = useState<Phase>('idle')
  const [failure, setFailure] = useState<SttFailure | null>(null)
  const [ready, setReady] = useState(false)
  const [levels, setLevels] = useState<number[]>([])
  const [elapsed, setElapsed] = useState(0)
  const recording = useRef<Recording | null>(null)
  const request = useRef<AbortController | null>(null)
  const mounted = useRef(false)
  const stopButton = useRef<HTMLButtonElement>(null)
  const micButton = useRef<HTMLButtonElement>(null)
  const barOpen = useRef(false)

  const active = phase === 'recording' || phase === 'sending'

  // Leaving the screen or switching persona stops the microphone and drops a request in flight.
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      const current = recording.current
      recording.current = null
      if (current) {
        current.cancelled = true
        try {
          current.recorder.stop()
        } catch {
          // already stopped
        }
        release(current)
      }
      request.current?.abort()
      request.current = null
    }
  }, [])

  // The composer shows the recording bar in place of the input while it records or sends.
  useEffect(() => {
    onActive?.(active)
  }, [active, onActive])

  // Focus follows the bar: onto stop when it opens, back onto the mic when it closes.
  useEffect(() => {
    if (phase === 'recording' && !barOpen.current) stopButton.current?.focus()
    if (phase === 'idle' && barOpen.current) micButton.current?.focus()
    barOpen.current = phase === 'recording' || phase === 'sending'
  }, [phase])

  // The line about a failure goes away after a few seconds, so it never covers the thread for long.
  useEffect(() => {
    if (!failure) return
    const timer = window.setTimeout(() => setFailure(null), FAILURE_MS)
    return () => window.clearTimeout(timer)
  }, [failure])

  if (!STT_LIVE || !customerId || !canRecord()) return null

  const send = (clip: Blob) => {
    setPhase('sending')
    const controller = new AbortController()
    request.current = controller
    const timer = window.setTimeout(() => controller.abort(), STT_TIMEOUT_MS)
    transcribe(clip, customerId, lang, controller.signal)
      .then((text) => {
        if (request.current !== controller) return
        onText(text)
        setReady(true)
      })
      .catch((error: unknown) => {
        if (request.current !== controller) return
        setFailure(error instanceof SttFailed ? error.reason : 'unavailable')
      })
      .finally(() => {
        window.clearTimeout(timer)
        if (request.current !== controller) return
        request.current = null
        setPhase('idle')
      })
  }

  const stop = () => {
    const current = recording.current
    if (!current) return
    window.clearTimeout(current.timer)
    try {
      current.recorder.stop() // onstop sends the clip
    } catch {
      recording.current = null
      release(current)
      setPhase('idle')
    }
  }

  // Cancel: while recording, the clip is dropped; while sending, the request is dropped. Nothing goes in the box.
  const cancel = () => {
    const current = recording.current
    if (current) {
      recording.current = null
      current.cancelled = true
      try {
        current.recorder.stop()
      } catch {
        // already stopped
      }
      release(current)
    }
    request.current?.abort()
    request.current = null
    setPhase('idle')
  }

  const start = async () => {
    setFailure(null)
    setReady(false)
    setPhase('starting')
    // Made in the tap, before the permission prompt, so the waveform's context is allowed to run.
    const context = audioContext()
    const dropContext = () => void context?.close().catch(() => {})
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      dropContext()
      setFailure(micFailure(error))
      setPhase('idle')
      return
    }
    // The screen went away while the permission prompt was open: release the microphone at once.
    if (!mounted.current) {
      dropContext()
      stopTracks(stream)
      return
    }
    const type = pickType((candidate) => MediaRecorder.isTypeSupported(candidate))
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(stream, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: AUDIO_BITS_PER_SECOND })
    } catch {
      dropContext()
      stopTracks(stream)
      setFailure('no_mic')
      setPhase('idle')
      return
    }
    const chunks: Blob[] = []
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    const session: Recording = { recorder, stream, timer: 0, cancelled: false, started: 0, ticker: 0, meter: levelMeter(context, stream) }
    recorder.onstop = () => {
      release(session)
      if (recording.current === session) recording.current = null
      if (session.cancelled) return
      const clip = new Blob(chunks, { type: recorder.mimeType || type || 'audio/webm' })
      // An empty or very short recording is never sent: the user is asked to try again (#759).
      if (clipTooShort(clip.size, Date.now() - session.started)) {
        setFailure('no_speech')
        setPhase('idle')
        return
      }
      send(clip)
    }
    session.timer = window.setTimeout(stop, MAX_RECORD_MS)
    recording.current = session
    try {
      recorder.start()
      session.started = Date.now()
    } catch {
      recording.current = null
      release(session)
      setFailure('no_mic')
      setPhase('idle')
      return
    }
    setLevels([])
    setElapsed(0)
    session.ticker = window.setInterval(() => {
      setElapsed(Date.now() - session.started)
      const level = session.meter?.read() ?? 0
      setLevels((previous) => [...previous.slice(-(BARS - 1)), level])
    }, TICK_MS)
    setPhase('recording')
  }

  const status = failure && phase === 'idle' ? s.failures[failure] : null
  const announced = phase === 'recording' ? s.recording : phase === 'sending' ? s.writing : failure ? s.failures[failure] : ready ? s.ready : ''

  return (
    <>
      {/* A short line above the composer about what went wrong. It keeps the bottom-right corner free for a
          round button there (scroll to the latest answer). */}
      {status && (
        <p className="pointer-events-none absolute right-[72px] bottom-full left-4 mb-2 rounded-lg border border-danger bg-danger-tint px-3 py-2 text-sm text-ink shadow-sm">
          {status}
        </p>
      )}
      <span role="status" className="sr-only">
        {announced}
      </span>
      {active ? (
        <RecordingBar
          sending={phase === 'sending'}
          levels={levels}
          elapsed={elapsed}
          lang={lang}
          onCancel={cancel}
          onStop={stop}
          stopRef={stopButton}
        />
      ) : (
        <button
          ref={micButton}
          type="button"
          aria-label={s.speak}
          disabled={phase === 'starting'}
          onClick={() => void start()}
          className="inline-flex size-[44px] shrink-0 items-center justify-center rounded-pill text-brand hover:bg-mint-tint focus-visible:outline-mint disabled:opacity-60"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[24px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
        </button>
      )}
    </>
  )
}

/**
 * The recording bar (#751), the whole composer row: [cancel] [waveform] [0:03] [stop]. While the clip is
 * turned into text, three dots replace the waveform and stop is disabled. Under reduced motion the bars are
 * hidden and a still dot with "Recording" shows instead; the dots do not pulse.
 */
export function RecordingBar({
  sending,
  levels,
  elapsed,
  lang,
  onCancel,
  onStop,
  stopRef,
}: {
  sending: boolean
  levels: number[]
  elapsed: number
  lang: 'en' | 'fi'
  onCancel: () => void
  onStop: () => void
  stopRef?: Ref<HTMLButtonElement>
}) {
  const s = micStrings(lang)
  const bars = [...Array.from({ length: Math.max(0, BARS - levels.length) }, () => 0), ...levels.slice(-BARS)]
  return (
    <div className="flex h-12 min-w-0 flex-1 items-center gap-[4px] rounded-pill border border-line-strong bg-surface px-[2px]">
      <button
        type="button"
        aria-label={s.cancel}
        onClick={onCancel}
        className="inline-flex size-[44px] shrink-0 items-center justify-center rounded-pill text-ink-2 hover:bg-mint-tint focus-visible:outline-mint"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[22px]" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
      <div aria-hidden="true" className="flex h-[32px] min-w-0 flex-1 items-center justify-center overflow-hidden">
        {sending ? (
          <span className="flex items-center gap-[6px]">
            {[0, 150, 300].map((delay) => (
              <span key={delay} className="size-[8px] rounded-full bg-muted motion-safe:animate-pulse" style={{ animationDelay: `${delay}ms` }} />
            ))}
          </span>
        ) : (
          <>
            <span className="flex h-full items-center gap-[3px] motion-reduce:hidden">
              {bars.map((level, i) => (
                <span key={i} className="w-[3px] shrink-0 rounded-full bg-brand" style={{ height: `${Math.max(3, Math.round(level * 28))}px` }} />
              ))}
            </span>
            <span className="hidden items-center gap-[8px] text-sm text-ink-2 motion-reduce:inline-flex">
              <span className="size-[10px] rounded-full bg-danger" />
              {s.recording}
            </span>
          </>
        )}
      </div>
      <span className="shrink-0 text-sm text-ink-2 tabular-nums">{formatElapsed(elapsed)}</span>
      <button
        ref={stopRef}
        type="button"
        aria-label={s.stop}
        disabled={sending}
        onClick={onStop}
        className="inline-flex size-[44px] shrink-0 items-center justify-center rounded-pill bg-deep text-on-deep focus-visible:outline-mint disabled:opacity-60"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[22px]" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      </button>
    </div>
  )
}
