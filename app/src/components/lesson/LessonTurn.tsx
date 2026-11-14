import { useEffect, useId, useState } from 'react'
import { BASKETS } from '../../lib/baskets.ts'
import { usePrefersReducedMotion } from '../../lib/motion.ts'
import { useOpening } from '../../lib/openingContext.ts'
import { markDone, readProgress } from '../../lib/learnProgress.ts'
import { firstWords, useWordReveal } from '../../lib/reveal.ts'
import { useSettings } from '../../lib/settings.ts'
import { openEvidence } from '../../lib/url.ts'
import type { ClientTurnProps } from '../clientTurns.tsx'
import { lessonKey, lessonsFor, opensOnReveal, revealOf, startIndex, type Lesson, type PickLesson } from './lessons.ts'
import { lessonStrings } from './lessonStrings.ts'

const HEADING = 'text-lg font-semibold leading-7 text-ink outline-none'
const ANSWER =
  'min-h-11 rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-semibold tabular-nums text-ink hover:bg-mint disabled:hover:bg-mint-tint'

type Strings = ReturnType<typeof lessonStrings>

/** The reveal's first sentence: the verdict (or none) and the right number, per lesson. */
function verdictOf(lesson: Lesson, picked: string | null, s: Strings): string {
  if (lesson.kind === 'split') return s.two.reveal
  if (lesson.kind === 'quiz') return `${picked === lesson.right ? s.quiz.right : s.quiz.wrong} ${lesson.reveal}`
  const reveal = revealOf(lesson, picked as PickLesson['right']['source'] | null)
  const display = reveal.right.number.display
  const verdict = reveal.verdict ?? 'plain'
  return lesson.id === 1 ? s.one[verdict][lesson.span](display) : s.three[verdict](display)
}

/** How long Sentti "types" before its reveal after a pick (the chat feel); none under reduced motion. */
const THINKING_MS = 500

/**
 * "Lesson of the day" (#703, #704), a client turn: up to three short lessons on the user's own
 * numbers, one at a time. Each asks a question with answer buttons, then reveals the real figures
 * and one money concept; "Next lesson" moves on, and the last one ends the turn. Nothing is sent
 * to the API, and progress lives only in this component: a reload or a persona switch (useChat
 * drops the turns) starts again. As a chat: the picked answer becomes the customer's own bubble,
 * Sentti's reveal follows three typing dots and types in word by word (the answer reveal, #686),
 * and a bar fills as lessons are done. Under reduced motion everything shows at once.
 */
export function LessonTurn({ onStep, lessons: given }: ClientTurnProps & { lessons?: Lesson[] }) {
  const { lang, t, customerId } = useSettings()
  const s = lessonStrings(lang)
  const opening = useOpening()
  const reduced = usePrefersReducedMotion()
  // Today's lessons are fixed when the turn opens: a background refresh does not change them mid-way.
  // The Learn tab passes a topic's lessons; the thread's turn takes the overview's three.
  const [lessons] = useState<Lesson[]>(() => given ?? lessonsFor(opening?.overview ?? null))
  // It starts at the first lesson not done yet (the Learn tab's progress), or the first when all are done.
  const [start] = useState(() => startIndex(lessons, readProgress(customerId).done))
  const [index, setIndex] = useState(start)
  const [picked, setPicked] = useState<string | null>(null)
  const [revealed, setRevealed] = useState(() => lessons.length > 0 && opensOnReveal(lessons[start]))
  // Sentti is "typing" between the pick and its reveal.
  const [thinking, setThinking] = useState(false)
  const questionId = useId()

  useEffect(() => {
    if (!thinking) return
    const id = window.setTimeout(() => setThinking(false), THINKING_MS)
    return () => window.clearTimeout(id)
  }, [thinking])

  const lesson: Lesson | null = lessons[index] ?? null
  const total = lessons.length
  const last = index === total - 1
  const shown = revealed && !thinking
  const verdict = lesson && shown ? verdictOf(lesson, picked, s) : null
  const split = lesson?.kind === 'split' && shown ? lesson.rows.map((row) => `${row.label} ${row.display}`).join(', ') : null
  // The step's title, announced once by the turn: the question, then the outcome (and the end).
  const title = !lesson
    ? s.none
    : verdict
      ? [verdict, split, last ? s.done : null].filter(Boolean).join(' ')
      : lesson.kind === 'quiz'
        ? lesson.question
        : lesson.kind === 'split'
          ? s.two.question
          : lesson.id === 1
            ? s.one.question[lesson.span]
            : s.three.question
  useEffect(() => {
    onStep(title)
  }, [onStep, title])
  // A lesson counts as done once its reveal is shown (the Learn tab's progress).
  useEffect(() => {
    if (shown && lesson) markDone(customerId, lessonKey(lesson))
  }, [shown, lesson, customerId])

  if (!lesson) {
    return (
      <h3 data-step-heading="" tabIndex={-1} className={HEADING}>
        {s.none}
      </h3>
    )
  }

  const question =
    lesson.kind === 'quiz' ? lesson.question : lesson.kind === 'split' ? s.two.question : lesson.id === 1 ? s.one.question[lesson.span] : s.three.question
  const answers =
    lesson.kind === 'quiz'
      ? lesson.options.map((option) => ({ key: option.key, text: option.text, icon: undefined }))
      : lesson.kind === 'split'
        ? lesson.rows.map((row) => ({ key: row.key, text: row.label, icon: BASKETS[row.key]?.icon }))
        : lesson.options.map((option) => ({ key: option.source as string, text: option.number.display, icon: undefined }))
  const chosen = picked === null ? null : (answers.find((answer) => answer.key === picked) ?? null)
  const next = () => {
    const following = lessons[index + 1]
    setIndex(index + 1)
    setPicked(null)
    setThinking(false)
    setRevealed(following ? opensOnReveal(following) : false)
  }
  const done = index + (shown ? 1 : 0)

  return (
    <div className="flex flex-col gap-3">
      {total > 1 && (
        <div className="flex items-center gap-3">
          <p className="shrink-0 text-sm text-muted">{s.progress(index + 1, total)}</p>
          {/* Fills as lessons are done; its width eases (instant under reduced motion). */}
          <div aria-hidden="true" className="h-1.5 flex-1 overflow-hidden rounded-pill bg-sunken">
            <div
              className="h-full rounded-pill bg-brand transition-[width] duration-500 ease-out"
              style={{ width: `${Math.round((done / total) * 100)}%` }}
            />
          </div>
        </div>
      )}
      {!opensOnReveal(lesson) && (
        <section aria-labelledby={questionId} className="flex flex-col gap-3">
          <h3 id={questionId} data-step-heading={shown ? undefined : ''} tabIndex={-1} className={HEADING}>
            {question}
          </h3>
          {chosen ? (
            // The customer's own answer, as their bubble on the right.
            <p className="card-enter ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-deep px-4 py-3 text-base font-semibold tabular-nums text-on-deep">
              <span className="sr-only">{s.answers}: </span>
              {chosen.text}
            </p>
          ) : (
            <div role="group" aria-label={s.answers} className="flex flex-col items-start gap-2">
              {answers.map((answer) => (
                <button
                  key={answer.key}
                  type="button"
                  onClick={() => {
                    setPicked(answer.key)
                    setRevealed(true)
                    if (!reduced) setThinking(true)
                  }}
                  className={ANSWER}
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
          )}
        </section>
      )}

      {thinking && (
        // Sentti is typing: three dots bounce one after another (still under reduced motion, never shown then).
        <p className="flex min-h-11 items-center gap-[4px] self-start rounded-xl rounded-bl-sm border border-line bg-surface px-4">
          <span className="sr-only">{t.loading}</span>
          {[0, 150, 300].map((delay) => (
            <span key={delay} aria-hidden="true" className="dot-bounce size-[6px] rounded-pill bg-muted" style={{ animationDelay: `${delay}ms` }} />
          ))}
        </p>
      )}

      {shown && verdict && (
        <LessonReveal
          key={index}
          lesson={lesson}
          picked={picked}
          verdict={verdict}
          last={last}
          animate={picked !== null && !reduced}
          onNext={next}
          s={s}
          hint={t.chipHint}
        />
      )}
    </div>
  )
}

/**
 * Sentti's reveal of one lesson: after a pick the verdict types in word by word (as a live answer
 * does), then the figures, the concept and "Next lesson" fade in. A tap shows it all at once. A
 * lesson that opens on its reveal, or reduced motion, shows everything at once.
 */
function LessonReveal({
  lesson,
  picked,
  verdict,
  last,
  animate,
  onNext,
  s,
  hint,
}: {
  lesson: Lesson
  picked: string | null
  verdict: string
  last: boolean
  animate: boolean
  onNext: () => void
  s: Strings
  hint: string
}) {
  const [live] = useState(animate)
  const reveal = useWordReveal(verdict, live)
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4" onClick={reveal.revealing ? reveal.skip : undefined}>
      <h3 data-step-heading="" tabIndex={-1} className={HEADING}>
        {firstWords(verdict, reveal.words)}
      </h3>
      {!reveal.revealing && (
        <div className={`flex flex-col gap-2 ${live ? 'card-enter' : ''}`}>
          {lesson.kind === 'quiz' ? (
            lesson.example && <p className="rounded-md bg-sunken p-3 text-base text-ink-2">{lesson.example}</p>
          ) : lesson.kind === 'split' ? (
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
            <PickReveal lesson={lesson} picked={picked} s={s} hint={hint} />
          )}
          <p className="text-base text-ink">
            {lesson.kind === 'quiz' ? lesson.concept : lesson.kind === 'split' ? s.two.concept : lesson.id === 1 ? s.one.concept : s.three.concept}
          </p>
          {last ? (
            <p className="text-base text-ink-2">{s.done}</p>
          ) : (
            <button
              type="button"
              onClick={onNext}
              className="mt-1 min-h-11 self-start rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
            >
              {s.next}
            </button>
          )}
        </div>
      )}
    </section>
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
            <li key={option.source}>{s.optionRow(option.number.label, option.number.display)}</li>
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
