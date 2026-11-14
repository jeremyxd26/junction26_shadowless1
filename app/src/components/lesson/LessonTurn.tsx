import { useEffect, useId, useState } from 'react'
import { BASKETS } from '../../lib/baskets.ts'
import { useOpening } from '../../lib/openingContext.ts'
import { useSettings } from '../../lib/settings.ts'
import { openEvidence } from '../../lib/url.ts'
import type { ClientTurnProps } from '../clientTurns.tsx'
import { inSentence, lessonsFor, opensOnReveal, revealOf, type Lesson, type PickLesson } from './lessons.ts'
import { lessonStrings } from './lessonStrings.ts'

const HEADING = 'text-lg font-semibold leading-7 text-ink outline-none'
const ANSWER =
  'min-h-11 rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-semibold tabular-nums text-ink hover:bg-mint disabled:hover:bg-mint-tint'

type Strings = ReturnType<typeof lessonStrings>

/** The reveal's first sentence: the verdict (or none) and the right number, per lesson. */
function verdictOf(lesson: Lesson, picked: string | null, s: Strings): string {
  if (lesson.kind === 'split') return s.two.reveal
  const reveal = revealOf(lesson, picked as PickLesson['right']['source'] | null)
  const display = reveal.right.number.display
  const verdict = reveal.verdict ?? 'plain'
  return lesson.id === 1 ? s.one[verdict][lesson.span](display) : s.three[verdict](display)
}

/**
 * "Lesson of the day" (#703, #704), a client turn: up to three short lessons on the user's own
 * numbers, one at a time. Each asks a question with answer buttons, then reveals the real figures
 * and one money concept; "Next lesson" moves on, and the last one ends the turn. Nothing is sent
 * to the API, and progress lives only in this component: a reload or a persona switch (useChat
 * drops the turns) starts again. Nothing animates.
 */
export function LessonTurn({ onStep }: ClientTurnProps) {
  const { lang, t } = useSettings()
  const s = lessonStrings(lang)
  const opening = useOpening()
  // Today's lessons are fixed when the turn opens: a background refresh does not change them mid-way.
  const [lessons] = useState<Lesson[]>(() => lessonsFor(opening?.overview ?? null))
  const [index, setIndex] = useState(0)
  const [picked, setPicked] = useState<string | null>(null)
  const [revealed, setRevealed] = useState(() => lessons.length > 0 && opensOnReveal(lessons[0]))
  const questionId = useId()

  const lesson: Lesson | null = lessons[index] ?? null
  const total = lessons.length
  const last = index === total - 1
  const verdict = lesson && revealed ? verdictOf(lesson, picked, s) : null
  const split = lesson?.kind === 'split' && revealed ? lesson.rows.map((row) => `${row.label} ${row.display}`).join(', ') : null
  // The step's title, announced once by the turn: the question, then the outcome (and the end).
  const title = !lesson
    ? s.none
    : verdict
      ? [verdict, split, last ? s.done : null].filter(Boolean).join(' ')
      : lesson.kind === 'split'
        ? s.two.question
        : lesson.id === 1
          ? s.one.question[lesson.span]
          : s.three.question
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

  const question = lesson.kind === 'split' ? s.two.question : lesson.id === 1 ? s.one.question[lesson.span] : s.three.question
  const answers =
    lesson.kind === 'split'
      ? lesson.rows.map((row) => ({ key: row.key, text: row.label, icon: BASKETS[row.key]?.icon }))
      : lesson.options.map((option) => ({ key: option.source as string, text: option.number.display, icon: undefined }))
  const next = () => {
    const following = lessons[index + 1]
    setIndex(index + 1)
    setPicked(null)
    setRevealed(following ? opensOnReveal(following) : false)
  }

  return (
    <div className="flex flex-col gap-3">
      {total > 1 && <p className="text-sm text-muted">{s.progress(index + 1, total)}</p>}
      {!opensOnReveal(lesson) && (
        <section aria-labelledby={questionId} className="flex flex-col gap-3">
          <h3 id={questionId} data-step-heading={revealed ? undefined : ''} tabIndex={-1} className={HEADING}>
            {question}
          </h3>
          <div role="group" aria-label={s.answers} className="flex flex-col items-start gap-2">
            {answers.map((answer) => (
              <button
                key={answer.key}
                type="button"
                disabled={revealed}
                aria-pressed={revealed ? picked === answer.key : undefined}
                onClick={() => {
                  setPicked(answer.key)
                  setRevealed(true)
                }}
                // After the reveal the picked answer keeps a ring; the others step back (disabled).
                className={`${ANSWER} ${revealed ? (picked === answer.key ? 'ring-2 ring-brand' : 'opacity-60') : ''}`}
              >
                {answer.icon && (
                  <span aria-hidden="true" className="mr-2">
                    {answer.icon}
                  </span>
                )}
                {answer.text}
              </button>
            ))}
          </div>
        </section>
      )}

      {revealed && verdict && (
        <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
          <h3 data-step-heading="" tabIndex={-1} className={HEADING}>
            {verdict}
          </h3>
          {lesson.kind === 'split' ? (
            <ul className="flex flex-col gap-1 text-base text-ink-2">
              {lesson.rows.map((row) => (
                <li key={row.key} className="flex flex-wrap items-baseline gap-x-2">
                  <span aria-hidden="true">{BASKETS[row.key]?.icon}</span>
                  <span>{row.label}</span>
                  <span className="font-semibold tabular-nums text-ink">{row.display}</span>
                </li>
              ))}
            </ul>
          ) : (
            <PickReveal lesson={lesson} picked={picked} s={s} hint={t.chipHint} />
          )}
          <p className="text-base text-ink">{lesson.kind === 'split' ? s.two.concept : lesson.id === 1 ? s.one.concept : s.three.concept}</p>
          {last ? (
            <p className="text-base text-ink-2">{s.done}</p>
          ) : (
            <button
              type="button"
              onClick={next}
              className="mt-1 min-h-11 self-start rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
            >
              {s.next}
            </button>
          )}
        </section>
      )}
    </div>
  )
}

/** A pick lesson's reveal: the right number (its evidence on tap) with its label, the others, a reason. */
function PickReveal({ lesson, picked, s, hint }: { lesson: PickLesson; picked: string | null; s: Strings; hint: string }) {
  const reveal = revealOf(lesson, picked as PickLesson['right']['source'] | null)
  const right = reveal.right.number
  return (
    <>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-base text-ink-2">
        {right.evidence_ref ? (
          <button
            type="button"
            onClick={() => openEvidence(right.evidence_ref as string)}
            aria-label={`${right.label}: ${right.display}. ${hint}`}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-pill border border-mint-line bg-mint-tint px-3.5 font-semibold tabular-nums text-ink hover:border-brand"
          >
            {right.display}
          </button>
        ) : (
          <span className="font-semibold tabular-nums text-ink">{right.display}</span>
        )}
        <span>{right.label}</span>
      </p>
      {reveal.others.length > 0 && (
        <ul className="flex flex-col gap-1 text-base text-ink-2">
          {reveal.others.map((option) => (
            <li key={option.source}>{s.isLabel(option.number.display, inSentence(option.number.label))}</li>
          ))}
        </ul>
      )}
      {lesson.reason && (
        <p className="flex flex-wrap items-baseline gap-x-2 rounded-md bg-sunken p-3 text-base text-ink-2">
          <span>{lesson.reason.text}</span>
          <span className="font-semibold tabular-nums text-ink">{lesson.reason.amount.display}</span>
        </p>
      )}
    </>
  )
}
