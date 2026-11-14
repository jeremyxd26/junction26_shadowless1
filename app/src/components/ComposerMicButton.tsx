import { useEffect, useRef, useState } from 'react'
import { micStrings } from '../lib/micStrings.ts'
import { useSettings } from '../lib/settings.ts'
import {
  AUDIO_BITS_PER_SECOND,
  MAX_RECORD_MS,
  STT_LIVE,
  STT_TIMEOUT_MS,
  SttFailed,
  canRecord,
  micFailure,
  pickType,
  transcribe,
  type SttFailure,
} from '../lib/stt.ts'

type Phase = 'idle' | 'starting' | 'recording' | 'sending'

const FAILURE_MS = 6000

interface Recording {
  recorder: MediaRecorder
  stream: MediaStream
  timer: number
  cancelled: boolean
}

function stopTracks(stream: MediaStream) {
  for (const track of stream.getTracks()) track.stop()
}

/**
 * A mic in the composer (#735), next to the paperclip: a tap records the question, a second tap or 15 s
 * stops it, and the words land in the composer's input; the user taps send. A refused microphone or a failed
 * request shows a short line above the composer, which stays usable throughout. 44 px at any text size.
 * Only in a live build with a microphone API (a mock build has no core to send the clip to).
 */
export function ComposerMicButton({ onText }: { onText: (text: string) => void }) {
  const { lang, customerId } = useSettings()
  const s = micStrings(lang)
  const [phase, setPhase] = useState<Phase>('idle')
  const [failure, setFailure] = useState<SttFailure | null>(null)
  const [ready, setReady] = useState(false)
  const recording = useRef<Recording | null>(null)
  const request = useRef<AbortController | null>(null)
  const mounted = useRef(false)

  // Leaving the screen or switching persona stops the microphone and drops a request in flight.
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      const current = recording.current
      recording.current = null
      if (current) {
        current.cancelled = true
        window.clearTimeout(current.timer)
        try {
          current.recorder.stop()
        } catch {
          // already stopped
        }
        stopTracks(current.stream)
      }
      request.current?.abort()
      request.current = null
    }
  }, [])

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
      current.recorder.stop()   // onstop sends the clip
    } catch {
      recording.current = null
      stopTracks(current.stream)
      setPhase('idle')
    }
  }

  const start = async () => {
    setFailure(null)
    setReady(false)
    setPhase('starting')
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      setFailure(micFailure(error))
      setPhase('idle')
      return
    }
    // The screen went away while the permission prompt was open: release the microphone at once.
    if (!mounted.current) {
      stopTracks(stream)
      return
    }
    const type = pickType((candidate) => MediaRecorder.isTypeSupported(candidate))
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(stream, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: AUDIO_BITS_PER_SECOND })
    } catch {
      stopTracks(stream)
      setFailure('no_mic')
      setPhase('idle')
      return
    }
    const chunks: Blob[] = []
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    const session: Recording = { recorder, stream, timer: 0, cancelled: false }
    recorder.onstop = () => {
      stopTracks(stream)
      window.clearTimeout(session.timer)
      if (recording.current === session) recording.current = null
      if (session.cancelled) return
      const clip = new Blob(chunks, { type: recorder.mimeType || type || 'audio/webm' })
      if (clip.size === 0) {
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
    } catch {
      recording.current = null
      window.clearTimeout(session.timer)
      stopTracks(stream)
      setFailure('no_mic')
      setPhase('idle')
      return
    }
    setPhase('recording')
  }

  const active = phase === 'recording'
  const status = active ? s.listening : phase === 'sending' ? s.writing : failure ? s.failures[failure] : null

  return (
    <>
      {/* A short line above the composer: listening, writing it down, or what went wrong. It keeps the
          bottom-right corner free for a round button there (scroll to the latest answer). */}
      {status && (
        <p
          className={`pointer-events-none absolute right-[72px] bottom-full left-4 mb-2 rounded-lg border px-3 py-2 text-sm text-ink shadow-sm ${
            failure && !active && phase !== 'sending' ? 'border-danger bg-danger-tint' : 'border-line bg-surface'
          }`}
        >
          {status}
        </p>
      )}
      <span role="status" className="sr-only">
        {failure ? s.failures[failure] : ready ? s.ready : ''}
      </span>
      <button
        type="button"
        aria-label={s.speak}
        aria-pressed={active}
        disabled={phase === 'starting' || phase === 'sending'}
        onClick={() => (active ? stop() : void start())}
        className={`relative inline-flex size-[44px] shrink-0 items-center justify-center rounded-pill focus-visible:outline-mint disabled:opacity-60 ${
          active ? 'bg-danger text-on-deep' : 'text-brand hover:bg-mint-tint'
        }`}
      >
        {active ? (
          <>
            {/* The pulse is the only motion; it stops under reduced motion (motion-safe). */}
            <span aria-hidden="true" className="absolute inset-0 rounded-pill bg-danger opacity-40 motion-safe:animate-ping" />
            <span aria-hidden="true" className="relative size-[14px] rounded-[3px] bg-on-deep" />
          </>
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[24px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
        )}
      </button>
    </>
  )
}
