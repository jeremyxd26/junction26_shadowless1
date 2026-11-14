import { useState } from 'react'
import { learnStrings } from '../components/learn/learnStrings.ts'
import { glossary } from '../components/learn/glossary.ts'
import { lessonsOf, nextLesson, topicsFor } from '../components/learn/topics.ts'
import { LessonTurn } from '../components/lesson/LessonTurn.tsx'
import { resetProgress, useLearnProgress } from '../lib/learnProgress.ts'
import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'

const noop = () => {}

function Bar({ done, total, label }: { done: number; total: number; label?: string }) {
  const percent = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div
      role={label ? 'progressbar' : undefined}
      aria-label={label}
      aria-valuemin={label ? 0 : undefined}
      aria-valuemax={label ? total : undefined}
      aria-valuenow={label ? done : undefined}
      aria-hidden={label ? undefined : true}
      className="h-2 overflow-hidden rounded-pill bg-sunken"
    >
      <div className="h-full rounded-pill bg-brand transition-[width] duration-500 ease-out" style={{ width: `${percent}%` }} />
    </div>
  )
}

function Tick({ done }: { done: boolean }) {
  return done ? (
    <span aria-hidden="true" className="inline-flex size-6 shrink-0 items-center justify-center rounded-pill bg-mint text-ink">
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  ) : (
    <span aria-hidden="true" className="inline-flex size-6 shrink-0 rounded-pill border-2 border-line-strong" />
  )
}

/**
 * The Learn tab: topics with progress, an overall count, completed lessons ticked, and "Continue" to
 * the next lesson, which opens the lesson turn in place. Client-side only; progress is the persona's
 * entry in learnProgress (lesson ids only).
 */
export function Learn() {
  const { lang, customerId } = useSettings()
  const s = learnStrings(lang)
  const opening = useOpening()
  const progress = useLearnProgress(customerId)
  const overview = opening?.overview ?? null
  const topics = topicsFor(overview, lang)
  const all = topics.flatMap((topic) => topic.lessons)
  const doneCount = all.filter((id) => progress.done.includes(id)).length
  const next = nextLesson(topics, progress.done)
  // The topic being studied (the lesson turn in place), or null for the topic list.
  const [studying, setStudying] = useState<string | null>(null)

  if (studying) {
    return (
      <section aria-label={s.topics[studying] ?? s.title} className="flex flex-col gap-4">
        <button
          type="button"
          onClick={() => setStudying(null)}
          className="inline-flex min-h-11 items-center gap-1 self-start rounded-pill pr-3 text-base font-semibold text-brand hover:bg-sunken"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2.25">
            <path d="M15 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {s.back}
        </button>
        <h2 className="text-xl font-bold text-ink">{s.topics[studying]}</h2>
        <LessonTurn key={studying} turnId={0} onStep={noop} onBusy={noop} lessons={lessonsOf(studying, overview, lang)} />
      </section>
    )
  }

  return (
    <section aria-labelledby="learn-title" className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <h2 id="learn-title" className="text-2xl font-bold text-ink">
          {s.title}
        </h2>
        <p className="text-base text-ink-2">{s.intro}</p>
      </div>

      {all.length === 0 ? (
        <p className="rounded-lg border border-line bg-surface p-4 text-base text-ink-2">{s.noLessons}</p>
      ) : (
        <>
          <div className="flex flex-col gap-2 rounded-xl bg-deep p-4 text-on-deep">
            <p className="text-lg font-semibold">{s.overall(doneCount, all.length)}</p>
            <Bar done={doneCount} total={all.length} label={s.overall(doneCount, all.length)} />
            <button
              type="button"
              onClick={() => setStudying(next?.topic ?? topics[0].id)}
              className="mt-2 inline-flex min-h-11 items-center justify-center self-start rounded-pill bg-mint px-5 text-base font-semibold text-ink hover:bg-mint-tint"
            >
              {next ? s.continue : s.again}
            </button>
            {!next && <p className="text-sm text-on-deep-muted">{s.allDone}</p>}
          </div>

          <ul className="flex flex-col gap-3">
            {topics.map((topic) => {
              const done = topic.lessons.filter((id) => progress.done.includes(id)).length
              return (
                <li key={topic.id} className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-lg font-semibold text-ink">{s.topics[topic.id]}</h3>
                    <span className="shrink-0 text-sm tabular-nums text-muted">{s.topicProgress(done, topic.lessons.length)}</span>
                  </div>
                  <Bar done={done} total={topic.lessons.length} />
                  <ul className="flex flex-col gap-1">
                    {topic.lessons.map((id) => {
                      const finished = progress.done.includes(id)
                      return (
                        <li key={id} className="flex min-h-9 items-center gap-3 text-base text-ink-2">
                          <Tick done={finished} />
                          <span>{s.lessons[id]}</span>
                          {finished && <span className="sr-only">, {s.doneMark}</span>}
                        </li>
                      )
                    })}
                  </ul>
                  <button
                    type="button"
                    onClick={() => setStudying(topic.id)}
                    className="min-h-11 self-start rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
                  >
                    {done < topic.lessons.length ? s.continue : s.again}
                  </button>
                </li>
              )
            })}
          </ul>

          <section aria-labelledby="glossary-title" className="flex flex-col gap-2">
            <h3 id="glossary-title" className="text-xl font-bold text-ink">
              {s.glossaryTitle}
            </h3>
            <p className="text-base text-ink-2">{s.glossaryIntro}</p>
            <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
              {glossary(overview, lang).map((entry) => (
                <li key={entry.id}>
                  <details className="group px-4">
                    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-base font-semibold text-ink [&::-webkit-details-marker]:hidden">
                      {entry.term}
                      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </summary>
                    <p className="pb-2 text-base text-ink-2">{entry.text}</p>
                    {entry.figure && (
                      <p className="pb-3 text-sm text-ink-2">
                        {s.inYourNumbers}: <span className="font-semibold tabular-nums text-ink">{entry.figure}</span>
                      </p>
                    )}
                  </details>
                </li>
              ))}
            </ul>
          </section>

          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={() => resetProgress(customerId)}
              className="min-h-11 rounded-pill px-1 text-sm font-semibold text-muted underline underline-offset-4 hover:text-ink"
            >
              {s.reset}
            </button>
            <p className="text-xs text-muted">{s.storageNote}</p>
          </div>
        </>
      )}
    </section>
  )
}
