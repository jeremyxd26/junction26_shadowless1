import { useEffect, useRef, useState } from 'react'
import { saveScore } from '../../lib/learnProgress.ts'
import { useSettings } from '../../lib/settings.ts'
import { learnStrings } from './learnStrings.ts'
import { miniTest } from './miniTests.ts'

/** An answer; its colour comes only from its state, so no background class competes with another. */
const ANSWER = 'min-h-11 rounded-md border-2 px-4 py-2 text-left text-base font-semibold text-ink'
/** A pass is at least this many right answers out of three. */
export const PASS_SCORE = 2

/**
 * A topic's mini-test: three questions, one at a time. After each answer a short verdict, and after a
 * wrong one a friendly line on why; at the end the score ("2 of 3") is kept with the persona's progress.
 */
export function MiniTest({
  topic,
  onDone,
  onNextTopic,
}: {
  topic: string
  /** Back to the topic list. */
  onDone: () => void
  /** The next topic, or undefined after the last one. */
  onNextTopic?: () => void
}) {
  const { lang, customerId } = useSettings()
  const s = learnStrings(lang)
  const [questions] = useState(() => miniTest(topic, lang))
  const [index, setIndex] = useState(0)
  const [picked, setPicked] = useState<string | null>(null)
  const [score, setScore] = useState(0)
  const [finished, setFinished] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)

  // Each new question and the result take the focus, so a screen reader reads them.
  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [index, finished])

  if (questions.length === 0) return null
  const question = questions[index]
  const last = index === questions.length - 1

  if (finished) {
    return (
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
        <h3 ref={heading} tabIndex={-1} className="text-lg font-semibold text-ink outline-none">
          {s.testResult(score, questions.length)}
        </h3>
        <p className="text-base text-ink-2">
          {score === questions.length ? s.testAll : score >= PASS_SCORE ? s.testPassed : s.testRetryNote}
        </p>
        <div className="flex flex-wrap gap-2">
          {score < PASS_SCORE ? (
            <button
              type="button"
              onClick={() => {
                setIndex(0)
                setPicked(null)
                setScore(0)
                setFinished(false)
              }}
              className="min-h-11 rounded-pill bg-deep px-5 text-base font-semibold text-on-deep"
            >
              {s.retry}
            </button>
          ) : (
            onNextTopic && (
              <button type="button" onClick={onNextTopic} className="min-h-11 rounded-pill bg-deep px-5 text-base font-semibold text-on-deep">
                {s.nextTopic}
              </button>
            )
          )}
          <button
            type="button"
            onClick={onDone}
            className="min-h-11 rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
          >
            {s.backToTopics}
          </button>
        </div>
      </section>
    )
  }

  const right = picked !== null && picked === question.right
  return (
    <section aria-labelledby={`test-${topic}-${index}`} className="flex flex-col gap-3">
      <p className="text-sm text-muted">{s.testProgress(index + 1, questions.length)}</p>
      <h3 id={`test-${topic}-${index}`} ref={heading} tabIndex={-1} className="text-lg font-semibold leading-7 text-ink outline-none">
        {question.question}
      </h3>
      <div role="group" aria-label={s.testAnswers} className="flex flex-col items-stretch gap-2">
        {question.options.map((option) => {
          const chosen = picked === option.key
          const isRight = option.key === question.right
          // Before the answer: white. After it: the right answer green, a wrong pick red, the rest faded.
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
                if (isRight) setScore((n) => n + 1)
              }}
              className={`${ANSWER} ${look}`}
            >
              {picked !== null && isRight && <span className="sr-only">, {s.testCorrectMark}</span>}
              {option.text}
            </button>
          )
        })}
      </div>
      {picked !== null && (
        <div className="flex flex-col gap-2" role="status">
          <p className="text-base font-semibold text-ink">{right ? s.testRight : s.testWrong}</p>
          {!right && <p className="text-base text-ink-2">{question.explain}</p>}
        </div>
      )}
      {picked !== null && (
        <button
          type="button"
          onClick={() => {
            if (last) {
              saveScore(customerId, topic, score)
              setFinished(true)
            } else {
              setIndex(index + 1)
              setPicked(null)
            }
          }}
          className="min-h-11 self-start rounded-pill bg-deep px-5 text-base font-semibold text-on-deep"
        >
          {last ? s.testFinish : s.testNext}
        </button>
      )}
    </section>
  )
}
