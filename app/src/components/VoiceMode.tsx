import { useEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent } from 'react'
import { useSettings } from '../lib/settings.ts'
import { useVoice } from '../lib/speech.ts'
import type { Turn } from '../lib/thread.ts'
import { ringStep } from '../lib/voiceMode.ts'
import { voiceModeStrings } from '../lib/voiceModeStrings.ts'
import type { VoicePhase, VoiceSession } from '../lib/voiceSession.ts'
import { SenttiMascot } from './voice/SenttiMascot.tsx'
import type { MascotState } from './voice/mascotStrings.ts'

/** The wave's bars. */
export const WAVE_BARS = 21

/** The cat's state in each phase (#893): it rests while the microphone opens. */
export const MASCOT_STATE: Record<VoicePhase, MascotState> = {
  starting: 'idle',
  listening: 'listening',
  thinking: 'thinking',
  speaking: 'speaking',
}

/** The reduced-motion ring's widths by level step: it thickens with the voice in steps, without a transition. */
const RING_WIDTH = ['border-[4px]', 'border-[9px]', 'border-[14px]', 'border-[20px]']

/** The still ring under reduced motion: its colour says the phase. */
const RING: Record<VoicePhase, string> = {
  starting: 'border-line-strong',
  listening: 'border-brand',
  thinking: 'border-line-strong',
  speaking: 'border-deep',
}

/**
 * Voice mode (#811): a full-screen overlay over the chat with Sentti the cat on a large round button,
 * a live wave under the cat, a caption (Listening… / Thinking… / Speaking…) and ✕. The button: while
 * listening it means "done talking", while Sentti speaks it interrupts and listens again. Esc exits like
 * ✕. The questions and answers land in the thread behind it as typed ones do.
 *
 * The cat (#893) listens, thinks and speaks with the phase, and its mouth follows Sentti's voice through
 * `session.level()`, polled in the cat's own frame loop. It is drawn over the button rather than inside
 * it (a button holds no block content), lets taps through, and is hidden from screen readers: the
 * caption is the one live status. Under reduced motion the cat is still, the bars hide and a still ring
 * around the cat shows the level in steps.
 */
export function VoiceMode({ session, turns }: { session: VoiceSession; turns: Turn[] }) {
  const { lang } = useSettings()
  const s = voiceModeStrings(lang)
  const voice = useVoice(lang)
  const { phase, missed, heard } = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot)
  const bars = useRef<(HTMLSpanElement | null)[]>([])
  const waveButton = useRef<HTMLButtonElement>(null)
  const exitButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    session.attach()
    return () => session.detach()
  }, [session])
  useEffect(() => session.setTurns(turns), [session, turns])
  useEffect(() => session.setVoice(voice), [session, voice])
  useEffect(() => waveButton.current?.focus(), [])

  // Frame by frame the bars follow the microphone while listening and the Gemini voice while speaking;
  // while thinking (or with the device voice) they breathe slowly. Nothing moves under reduced motion.
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0
    const draw = (now: number) => {
      const live = session.wave(WAVE_BARS)
      const { phase: current } = session.getSnapshot()
      const swing = current === 'speaking' ? 0.3 : current === 'thinking' ? 0.1 : 0.04
      bars.current.forEach((bar, i) => {
        if (!bar) return
        const idle = 0.1 + swing * (1 + Math.sin(now / 380 + i * 0.6)) * 0.5
        const level = live ? Math.max(0.06, live[i] ?? 0) : idle
        bar.style.transform = `scaleY(${level.toFixed(3)})`
      })
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [session])

  // Under reduced motion the still ring shows the level in steps instead (a few readings a second, no transition).
  const [step, setStep] = useState(0)
  useEffect(() => {
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const timer = window.setInterval(() => setStep(ringStep(session.level())), 150)
    return () => window.clearInterval(timer)
  }, [session])

  const caption = phase === 'speaking' ? s.speaking : phase === 'thinking' ? s.thinking : s.listening
  const tappable = phase === 'listening' || phase === 'speaking'
  const label = phase === 'listening' ? s.sendNow : phase === 'speaking' ? s.interrupt : caption

  // Esc exits; Tab stays on the overlay's two buttons.
  const keys = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      session.exit()
    } else if (event.key === 'Tab') {
      event.preventDefault()
      const next = document.activeElement === waveButton.current ? exitButton.current : waveButton.current
      next?.focus()
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="voice-mode-title"
      onKeyDown={keys}
      className="motion-fade fixed inset-0 z-50 flex touch-none flex-col items-center bg-page px-[16px] pt-[calc(env(safe-area-inset-top)+16px)] pb-[calc(env(safe-area-inset-bottom)+24px)]"
    >
      <h2 id="voice-mode-title" className="text-base font-bold text-ink">
        {s.title}
      </h2>
      <div className="flex w-full max-w-[448px] min-h-0 flex-1 flex-col items-center justify-center gap-8">
        <div className="relative shrink-0">
          <button
            ref={waveButton}
            type="button"
            aria-label={label}
            aria-disabled={!tappable}
            onClick={() => session.tap()}
            className="relative flex size-[min(72vw,280px)] shrink-0 flex-col items-center justify-end rounded-full bg-surface pb-[12%] shadow-float focus-visible:outline-mint aria-disabled:cursor-default"
          >
            {/* The wave: a low strip under the cat. */}
            <span aria-hidden="true" className="flex h-[12%] items-center gap-[min(0.8vw,3px)] motion-reduce:hidden">
              {Array.from({ length: WAVE_BARS }, (_, i) => (
                <span
                  key={i}
                  ref={(node) => {
                    bars.current[i] = node
                  }}
                  className="h-full w-[min(1.1vw,4px)] origin-center rounded-full bg-brand"
                  style={{ transform: 'scaleY(0.1)' }}
                />
              ))}
            </span>
            {/* Reduced motion: a still ring around the cat, its width the level in steps, its colour the phase. */}
            <span aria-hidden="true" className={`absolute inset-[4%] hidden rounded-full motion-reduce:block ${RING_WIDTH[step]} ${RING[phase]}`} />
          </button>
          {/* The cat, over the button: taps go through to it. Centred when the wave strip is hidden. */}
          <div
            aria-hidden="true"
            data-voice-mascot=""
            className="pointer-events-none absolute inset-x-0 top-[10%] flex justify-center motion-reduce:top-[22%] [&_svg]:size-[min(40vw,156px)]"
          >
            <SenttiMascot state={MASCOT_STATE[phase]} getLevel={() => session.level()} stateText={false} lang={lang} />
          </div>
        </div>
        {/* One status line: the caption, and "Didn't catch that" after a round with no words. */}
        <div role="status" className="flex min-h-[4.5rem] flex-col items-center gap-1 text-center">
          <p className="text-xl font-bold text-ink">{caption}</p>
          {missed && phase === 'listening' && <p className="text-base text-muted">{s.missed}</p>}
        </div>
        {heard && phase !== 'listening' && (
          <p className="line-clamp-3 max-w-full text-center text-base break-words text-ink-2">“{heard}”</p>
        )}
      </div>
      <button
        ref={exitButton}
        type="button"
        aria-label={s.exit}
        onClick={() => session.exit()}
        className="inline-flex size-[56px] shrink-0 items-center justify-center rounded-pill bg-sunken text-ink hover:bg-line focus-visible:outline-mint"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[24px]" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  )
}
