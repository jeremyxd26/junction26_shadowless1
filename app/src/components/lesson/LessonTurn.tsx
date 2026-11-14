import { useEffect, useId, useState } from 'react'
import { useOpening } from '../../lib/openingContext.ts'
import { useSettings } from '../../lib/settings.ts'
import { openEvidence } from '../../lib/url.ts'
import type { ClientTurnProps } from '../clientTurns.tsx'
import { inSentence, lessonOne, opensOnReveal, revealOf, type LessonOne, type LessonOneSource } from './lessons.ts'
import { lessonStrings } from './lessonStrings.ts'

/** How many lessons the turn has today (#703: lesson 1; #704 adds lessons 2 and 3). */
const TOTAL = 1

const HEADING = 'text-lg font-semibold leading-7 text-ink outline-none'
const ANSWER =
  'min-h-11 rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-semibold tabular-nums text-ink hover:bg-mint disabled:hover:bg-mint-tint'

/**
 * "Lesson of the day" (#703), a client turn: a question about the user's own number, answer
 * buttons, then a reveal with the real number, the other options by their labels and one money
 * concept. Nothing is sent to the API, and progress lives only in this component: a reload or a
 * persona switch (useChat drops the turns) starts again. Nothing animates.
 */
export function LessonTurn({ onStep }: ClientTurnProps) {
  const { lang, t } = useSettings()
  const s = lessonStrings(lang)
  const opening = useOpening()
  // The lesson is fixed when the turn opens: a background refresh does not change it mid-way.
  const [lesson] = useState<LessonOne | null>(() => lessonOne(opening?.overview ?? null))
  const [picked, setPicked] = useState<LessonOneSource | null>(null)
  const [revealed, setRevealed] = useState(() => lesson !== null && opensOnReveal(lesson))
  const questionId = useId()

  const reveal = lesson && revealed ? revealOf(lesson, picked) : null
  const verdict = reveal && lesson ? s[reveal.verdict ?? 'plain'][lesson.span](reveal.right.number.display) : null
  // The step's title, announced once by the turn: the question, then the outcome.
  const title = !lesson ? s.none : (verdict ?? s.question[lesson.span])
  useEffect(() => {
    onStep(title)
  }, [onStep, title])

  if (!lesson) {
    return (
      <h3 data-step-heading="" tabIndex={-1} className={HEADING}>
        {s.none}
      </h3>
    )
  }

  const pick = (source: LessonOneSource) => {
    setPicked(source)
    setRevealed(true)
  }

  return (
    <div className="flex flex-col gap-3">
      {TOTAL > 1 && <p className="text-sm text-muted">{s.progress(1, TOTAL)}</p>}
      {!opensOnReveal(lesson) && (
        <section aria-labelledby={questionId} className="flex flex-col gap-3">
          <h3 id={questionId} data-step-heading={revealed ? undefined : ''} tabIndex={-1} className={HEADING}>
            {s.question[lesson.span]}
          </h3>
          <div role="group" aria-label={s.answers} className="flex flex-col items-start gap-2">
            {lesson.options.map((option) => (
              <button
                key={option.source}
                type="button"
                disabled={revealed}
                aria-pressed={revealed ? picked === option.source : undefined}
                onClick={() => pick(option.source)}
                // After the reveal the picked answer keeps a ring; the others step back (disabled).
                className={`${ANSWER} ${revealed ? (picked === option.source ? 'ring-2 ring-brand' : 'opacity-60') : ''}`}
              >
                {option.number.display}
              </button>
            ))}
          </div>
        </section>
      )}

      {reveal && verdict && (
        <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
          <h3 data-step-heading="" tabIndex={-1} className={HEADING}>
            {verdict}
          </h3>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-base text-ink-2">
            {reveal.right.number.evidence_ref ? (
              <button
                type="button"
                onClick={() => openEvidence(reveal.right.number.evidence_ref as string)}
                aria-label={`${reveal.right.number.label}: ${reveal.right.number.display}. ${t.chipHint}`}
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-pill border border-mint-line bg-mint-tint px-3.5 font-semibold tabular-nums text-ink hover:border-brand"
              >
                {reveal.right.number.display}
              </button>
            ) : (
              <span className="font-semibold tabular-nums text-ink">{reveal.right.number.display}</span>
            )}
            <span>{reveal.right.number.label}</span>
          </p>
          {reveal.others.length > 0 && (
            <ul className="flex flex-col gap-1 text-base text-ink-2">
              {reveal.others.map((option) => (
                <li key={option.source}>{s.isLabel(option.number.display, inSentence(option.number.label))}</li>
              ))}
            </ul>
          )}
          <p className="text-base text-ink">{s.concept}</p>
        </section>
      )}
    </div>
  )
}
