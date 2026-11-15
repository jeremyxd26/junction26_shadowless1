import { useEffect, useRef, useState, type ReactNode } from 'react'
import { markDone } from '../../lib/learnProgress.ts'
import { useSettings } from '../../lib/settings.ts'
import { learnStrings } from './learnStrings.ts'
import type { LessonIcon, TeachLesson } from './teachLessons.ts'
import { learnMore, peopleLine } from './peopleLikeYou.ts'

const OPTION = 'min-h-11 rounded-md border-2 px-4 py-2 text-left text-base font-semibold text-ink'

/** The lesson's line icon (own drawings), brand green. */
function Icon({ name }: { name: LessonIcon }) {
  const paths: Record<LessonIcon, ReactNode> = {
    pie: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3v9h9" />
      </>
    ),
    baskets: <path d="M4 9h16l-1.5 10h-13zM8 9l4-5 4 5" />,
    save: <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />,
    reference: <path d="M5 4h14v16H5zM9 9h6M9 13h6M9 17h3" />,
    account: <path d="M3 10l9-6 9 6M5 10v8M19 10v8M9 10v8M15 10v8M3 20h18" />,
    auto: <path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" />,
    payday: <path d="M4 6h16v12H4zM4 10h16M8 15h3" />,
    buffer: <path d="M3 12a9 9 0 0 1 18 0zM12 12v6a2 2 0 0 0 4 0" />,
    median: <path d="M5 20V12M9 20V8M12 20V4M15 20V9M19 20v-6M3 20h18" />,
    link: (
      <>
        <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
        <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
      </>
    ),
    transfer: <path d="M4 8h13M13 4l4 4-4 4M20 16H7M11 12l-4 4 4 4" />,
  }
  return (
    <span aria-hidden="true" className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-mint-tint text-brand">
      <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {paths[name]}
      </svg>
    </span>
  )
}

/**
 * A Learn-tab lesson in four steps: teach (two or three sentences, one icon), the customer's numbers
 * (the API's display), one check question about the idea (right green, wrong red with the right one
 * green and a line on why), then the takeaway and the next step. A lesson counts as done once its
 * check is answered. The topic's lessons follow one another from `startAt`.
 */
export function LearnLesson({
  lessons,
  startAt,
  onQuiz,
  onBack,
  ageBand = null,
}: {
  lessons: TeachLesson[]
  startAt: string
  onQuiz?: () => void
  onBack: () => void
  /** The persona's age band ("35-44", from /api/personas): a Statistics Finland line for people that age (#885). */
  ageBand?: string | null
}) {
  const { lang, customerId } = useSettings()
  const s = learnStrings(lang)
  const [index, setIndex] = useState(() => Math.max(0, lessons.findIndex((lesson) => lesson.key === startAt)))
  const [picked, setPicked] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const lesson = lessons[index]
  const people = lesson ? peopleLine(lesson.key, ageBand, lang) : null
  const more = lesson ? learnMore(lesson.key, ageBand, lang) : []

  // Each new lesson takes the focus at its title and starts at the top.
  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
    heading.current?.scrollIntoView({ block: 'start' })
  }, [index])

  if (!lesson) return null
  const last = index === lessons.length - 1
  const right = picked !== null && picked === lesson.check.right

  return (
    <article className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <p className="shrink-0 text-sm text-muted">{s.lessonOf(index + 1, lessons.length)}</p>
        <div aria-hidden="true" className="h-1.5 flex-1 overflow-hidden rounded-pill bg-sunken">
          <div
            className="h-full rounded-pill bg-brand transition-[width] duration-500 ease-out"
            style={{ width: `${Math.round(((index + (picked !== null ? 1 : 0)) / lessons.length) * 100)}%` }}
          />
        </div>
      </div>

      <section className="card-enter flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
        <div className="flex items-center gap-3">
          <Icon name={lesson.icon} />
          <h3 ref={heading} tabIndex={-1} className="scroll-mt-32 text-lg font-semibold leading-7 text-ink outline-none">
            {lesson.title}
          </h3>
        </div>
        <p className="text-base text-ink-2">{lesson.teach}</p>
      </section>

      {lesson.numbers.length > 0 && (
        <section aria-label={lesson.numbersTitle} className="card-enter flex flex-col gap-2 rounded-lg bg-mint-tint p-4">
          <p className="text-sm font-semibold text-ink-2">{lesson.numbersTitle}</p>
          <dl className="flex flex-col gap-1">
            {lesson.numbers.map((figure) => (
              <div key={figure.label} className="flex flex-wrap items-baseline justify-between gap-x-3">
                <dt className="text-base text-ink-2">{figure.label}</dt>
                <dd className="text-lg font-semibold tabular-nums text-ink">{figure.display}</dd>
              </div>
            ))}
          </dl>
          {lesson.source && <p className="text-xs leading-4 text-muted">{lesson.source}</p>}
          {/* People the customer's age in Finland (#885): the sentence as built from the fact record. */}
          {people && <p className="border-t border-mint-line pt-2 text-sm leading-5 text-ink-2">{people.text}</p>}
        </section>
      )}

      <section aria-labelledby={`check-${lesson.key}`} className="flex flex-col gap-2">
        <p className="text-sm font-semibold text-muted">{s.checkLabel}</p>
        <h4 id={`check-${lesson.key}`} className="text-base font-semibold text-ink">
          {lesson.check.question}
        </h4>
        <div role="group" aria-label={s.testAnswers} className="flex flex-col items-stretch gap-2">
          {lesson.check.options.map((option) => {
            const chosen = picked === option.key
            const isRight = option.key === lesson.check.right
            const look =
              picked === null
                ? 'border-line bg-surface hover:bg-sunken'
                : isRight
                  ? 'answer-pop border-brand bg-mint'
                  : chosen
                    ? 'answer-pop border-danger bg-danger-tint'
                    : 'border-line bg-surface opacity-60'
            return (
              <button
                key={option.key}
                type="button"
                disabled={picked !== null}
                aria-pressed={picked === null ? undefined : chosen}
                onClick={() => {
                  setPicked(option.key)
                  markDone(customerId, lesson.key)
                }}
                className={`${OPTION} ${look}`}
              >
                {picked !== null && isRight && <span className="sr-only">{s.testCorrectMark}: </span>}
                {option.text}
              </button>
            )
          })}
        </div>
        {picked !== null && (
          <p role="status" className="text-base text-ink">
            <span className="font-semibold">{right ? s.testRight : s.testWrong}</span> {right ? '' : lesson.check.explain}
          </p>
        )}
      </section>

      {picked !== null && (
        <section className="card-enter flex flex-col gap-3 rounded-lg border-l-4 border-brand bg-surface p-4">
          <p className="text-sm font-semibold text-muted">{s.takeawayLabel}</p>
          <p className="text-base font-semibold text-ink">{lesson.takeaway}</p>
          <div className="flex flex-wrap gap-2">
            {!last ? (
              <button
                type="button"
                onClick={() => {
                  setIndex(index + 1)
                  setPicked(null)
                }}
                className="min-h-11 rounded-pill bg-deep px-5 text-base font-semibold text-on-deep"
              >
                {s.nextLesson}
              </button>
            ) : (
              onQuiz && (
                <button type="button" onClick={onQuiz} className="min-h-11 rounded-pill bg-deep px-5 text-base font-semibold text-on-deep">
                  {s.takeQuiz}
                </button>
              )
            )}
            <button
              type="button"
              onClick={onBack}
              className="min-h-11 rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
            >
              {s.backToTopic}
            </button>
          </div>
          {more.length > 0 && (
            <div className="flex flex-col gap-1 border-t border-line pt-3">
              <p className="text-sm font-semibold text-muted">{s.learnMore}</p>
              {more.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-11 flex-wrap items-center gap-x-1.5 text-base font-semibold text-brand underline underline-offset-4"
                >
                  {link.title}
                  <span className="text-sm font-normal text-muted no-underline">· {link.publisher}</span>
                </a>
              ))}
            </div>
          )}
        </section>
      )}
    </article>
  )
}
