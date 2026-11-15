// Mock mode only (`/cards`, #798): Sentti's mascot in all five states, EN and FI, at 160 and 96 px,
// so it can be reviewed without the voice mode (#811). Nothing moves on its own except the states'
// own CSS loops: the fake voice and the celebrate replay start from buttons.
import { useEffect, useState } from 'react'
import type { Language } from '../../api/types.ts'
import { SenttiMascot } from './SenttiMascot.tsx'
import { MASCOT_STATES, mascotStateLabel } from './mascotStrings.ts'

/** The speaking mouth's level while the fake voice is off: half open and still. */
const STILL_LEVEL = 0.6
/** The fake voice: a new level every 50 ms (the voice mode feeds about as often), syllables at ~3 per second. */
const TICK_MS = 50

function fakeVoice(ms: number): number {
  return Math.abs(Math.sin((ms / 1000) * Math.PI * 3)) * (0.75 + 0.25 * Math.sin(ms / 700))
}

const BUTTON = 'min-h-[44px] rounded-pill border border-line-strong bg-surface px-4 text-sm font-semibold text-brand'

export function MascotGallery() {
  const [voice, setVoice] = useState(false)
  const [level, setLevel] = useState(STILL_LEVEL)
  const [round, setRound] = useState(0)

  useEffect(() => {
    if (!voice) return
    const start = performance.now()
    const timer = window.setInterval(() => setLevel(fakeVoice(performance.now() - start)), TICK_MS)
    return () => window.clearInterval(timer)
  }, [voice])

  const speakingLevel = voice ? level : STILL_LEVEL
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        <button type="button" aria-pressed={voice} onClick={() => setVoice((on) => !on)} className={BUTTON}>
          Fake voice (sine level)
        </button>
        <button type="button" onClick={() => setRound((n) => n + 1)} className={BUTTON}>
          Replay celebrate
        </button>
      </div>
      {(['en', 'fi'] as Language[]).flatMap((lang) =>
        [160, 96].map((size) => (
          <div key={`${lang}-${size}`} data-mascot-row={`${lang}-${size}`} className="flex flex-col gap-2">
            <p className="font-mono text-xs text-muted">
              {lang.toUpperCase()} · {size} px
            </p>
            <ul className="flex flex-wrap items-start gap-x-4 gap-y-3">
              {MASCOT_STATES.map((state) => (
                <li key={state === 'celebrate' ? `${state}-${round}` : state} className="flex flex-col items-center gap-1">
                  <SenttiMascot state={state} level={state === 'speaking' ? speakingLevel : 0} size={size} lang={lang} />
                  <p className="text-center font-mono text-xs text-muted">
                    {state}
                    {mascotStateLabel(state, lang) ? `: ${mascotStateLabel(state, lang)}` : ''}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )),
      )}
    </div>
  )
}
