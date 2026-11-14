import { useId, useMemo, useState, type ReactNode } from 'react'
import { glossary } from '../components/learn/glossary.ts'
import { learnStrings } from '../components/learn/learnStrings.ts'
import { MiniTest, PASS_SCORE } from '../components/learn/MiniTest.tsx'
import { miniTest } from '../components/learn/miniTests.ts'
import { lessonsOf, topicsFor, type Topic } from '../components/learn/topics.ts'
import { LessonTurn } from '../components/lesson/LessonTurn.tsx'
import { resetProgress, useLearnProgress } from '../lib/learnProgress.ts'
import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'

const noop = () => {}

type Strings = ReturnType<typeof learnStrings>
type View = { kind: 'home' } | { kind: 'topic'; topic: string } | { kind: 'lesson'; topic: string; lesson: string } | { kind: 'quiz'; topic: string }

function Bar({ done, total, label, onDeep = false }: { done: number; total: number; label?: string; onDeep?: boolean }) {
  const percent = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div
      role={label ? 'progressbar' : undefined}
      aria-label={label}
      aria-valuemin={label ? 0 : undefined}
      aria-valuemax={label ? total : undefined}
      aria-valuenow={label ? done : undefined}
      aria-hidden={label ? undefined : true}
      className={`h-1.5 overflow-hidden rounded-pill ${onDeep ? 'bg-on-deep/20' : 'bg-sunken'}`}
    >
      <div className={`h-full rounded-pill transition-[width] duration-500 ease-out ${onDeep ? 'bg-mint' : 'bg-brand'}`} style={{ width: `${percent}%` }} />
    </div>
  )
}

/** The topic's line icon (own drawings), brand green. */
function TopicIcon({ topic }: { topic: string }) {
  const paths: Record<string, ReactNode> = {
    money: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3v9h9" />
      </>
    ),
    bills: (
      <>
        <path d="M7 3h7l4 4v14H7z" />
        <path d="M14 3v4h4M10 12h5M10 16h5" />
      </>
    ),
    saving: (
      <>
        <path d="M3 12a9 9 0 0 1 18 0z" />
        <path d="M12 12v6a2 2 0 0 0 4 0" />
      </>
    ),
  }
  return (
    <span aria-hidden="true" className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-mint-tint text-brand">
      <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {paths[topic]}
      </svg>
    </span>
  )
}

function BackButton({ label, onBack }: { label: string; onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="inline-flex min-h-11 items-center gap-1 self-start rounded-pill pr-3 text-base font-semibold text-brand hover:bg-sunken"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2.25">
        <path d="M15 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label}
    </button>
  )
}

/** Three states kept apart: lessons done, quiz taken, quiz passed (at least two of three). */
interface TopicState {
  done: number
  total: number
  lessonsDone: boolean
  score: number | undefined
  passed: boolean
  /** Lessons done and the quiz passed. */
  complete: boolean
  /** The quiz was taken and not passed. */
  retry: boolean
}

function topicState(topic: Topic, done: string[], scores: Record<string, number>): TopicState {
  const count = topic.lessons.filter((id) => done.includes(id)).length
  const score = scores[topic.id]
  const passed = score !== undefined && score >= PASS_SCORE
  const lessonsDone = count === topic.lessons.length
  return { done: count, total: topic.lessons.length, lessonsDone, score, passed, complete: lessonsDone && passed, retry: score !== undefined && !passed }
}

function stateLabel(state: TopicState, quizLength: number, s: Strings): string {
  if (state.complete) return s.stateDone
  if (state.retry) return s.quizRetry(state.score ?? 0, quizLength)
  return state.done === 0 && state.score === undefined ? s.stateStart : s.stateProgress
}

/** The next step: the first lesson not done, else the first quiz not passed, else nothing (all done). */
function nextStep(topics: Topic[], done: string[], scores: Record<string, number>): View | null {
  for (const topic of topics) {
    const lesson = topic.lessons.find((id) => !done.includes(id))
    if (lesson) return { kind: 'lesson', topic: topic.id, lesson }
  }
  for (const topic of topics) {
    if (!topicState(topic, done, scores).passed && miniTest(topic.id, 'en').length > 0) return { kind: 'quiz', topic: topic.id }
  }
  return null
}

/**
 * The Learn tab, laid out as learning tabs usually are: "Lessons | Glossary" on top; in Lessons one
 * "Continue learning" card (the only Continue), the topics as compact rows, and a topic screen with
 * its lessons as a path (done ✓, next ●, not started ○, every step tappable) ending in its quiz. No
 * points or streaks. Client-side only; progress is the persona's entry in learnProgress.
 */
export function Learn() {
  const { lang, customerId } = useSettings()
  const s = learnStrings(lang)
  const opening = useOpening()
  const progress = useLearnProgress(customerId)
  const overview = opening?.overview ?? null
  const topics = topicsFor(overview, lang)
  const [section, setSection] = useState<'lessons' | 'glossary'>('lessons')
  const [view, setView] = useState<View>({ kind: 'home' })
  const quizLength = (topic: string) => miniTest(topic, 'en').length
  const nextTopicAfter = (topic: string) => {
    const at = topics.findIndex((item) => item.id === topic)
    return at >= 0 && at < topics.length - 1 ? topics[at + 1].id : null
  }

  if (view.kind === 'lesson') {
    return (
      <section aria-label={s.topics[view.topic] ?? s.title} className="flex flex-col gap-4">
        <BackButton label={s.topics[view.topic] ?? s.back} onBack={() => setView({ kind: 'topic', topic: view.topic })} />
        <LessonTurn
          key={`${view.topic}:${view.lesson}`}
          turnId={0}
          onStep={noop}
          onBusy={noop}
          lessons={lessonsOf(view.topic, overview, lang)}
          startAt={view.lesson}
          doneText={s.lessonDoneText}
          onFinish={[
            ...(quizLength(view.topic) > 0 ? [{ label: s.takeQuiz, act: () => setView({ kind: 'quiz', topic: view.topic }) }] : []),
            { label: s.backToTopic, act: () => setView({ kind: 'topic', topic: view.topic }) },
          ]}
        />
      </section>
    )
  }

  if (view.kind === 'quiz') {
    return (
      <section aria-label={`${s.topics[view.topic] ?? s.title}: ${s.takeTest}`} className="flex flex-col gap-4">
        <BackButton label={s.topics[view.topic] ?? s.back} onBack={() => setView({ kind: 'topic', topic: view.topic })} />
        <MiniTest
          key={view.topic}
          topic={view.topic}
          onDone={() => setView({ kind: 'home' })}
          onNextTopic={(() => {
            const next = nextTopicAfter(view.topic)
            return next ? () => setView({ kind: 'topic', topic: next }) : undefined
          })()}
        />
      </section>
    )
  }

  if (view.kind === 'topic') {
    const topic = topics.find((item) => item.id === view.topic)
    if (topic) {
      return <TopicScreen topic={topic} s={s} state={topicState(topic, progress.done, progress.scores)} done={progress.done} onBack={() => setView({ kind: 'home' })} onOpen={setView} />
    }
  }

  return (
    <section aria-labelledby="learn-title" className="flex flex-col gap-4">
      <h2 id="learn-title" className="text-2xl font-bold text-ink">
        {s.title}
      </h2>
      <div role="tablist" aria-label={s.sections} className="flex gap-1 rounded-pill bg-sunken p-1">
        {(['lessons', 'glossary'] as const).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={section === key}
            onClick={() => setSection(key)}
            className={`relative min-h-9 flex-1 rounded-pill text-[15px] font-semibold after:absolute after:inset-x-0 after:-inset-y-1 after:content-[''] ${
              section === key ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink'
            }`}
          >
            {key === 'lessons' ? s.segLessons : s.segGlossary}
          </button>
        ))}
      </div>

      {section === 'glossary' ? (
        <Glossary s={s} />
      ) : (
        <>
          <ContinueCard topics={topics} next={nextStep(topics, progress.done, progress.scores)} done={progress.done} s={s} onOpen={setView} />
          <ul className="flex flex-col gap-2">
            {topics.map((topic) => {
              const state = topicState(topic, progress.done, progress.scores)
              return (
                <li key={topic.id} className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
                  <button
                    type="button"
                    onClick={() => setView({ kind: 'topic', topic: topic.id })}
                    className="flex min-h-11 w-full items-center gap-3 rounded-md text-left hover:bg-sunken"
                  >
                    <TopicIcon topic={topic.id} />
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="text-base font-semibold text-ink">{s.topics[topic.id]}</span>
                        <span className={`shrink-0 text-right text-sm font-semibold ${state.complete ? 'text-brand' : 'text-muted'}`}>
                          {stateLabel(state, quizLength(topic.id), s)}
                        </span>
                      </span>
                      <span className="text-sm text-ink-2">{s.lessonCount(state.done, state.total)}</span>
                      <Bar done={state.done} total={state.total} />
                    </span>
                  </button>
                  {state.retry && (
                    <button
                      type="button"
                      onClick={() => setView({ kind: 'quiz', topic: topic.id })}
                      className="min-h-11 self-start rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
                    >
                      {s.retry}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
          <div className="flex flex-col items-start gap-1 pt-2">
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

/** The one "Continue learning" card: the next lesson and the only Continue; all done: review a topic. */
function ContinueCard({ topics, next, done, s, onOpen }: { topics: Topic[]; next: View | null; done: string[]; s: Strings; onOpen: (view: View) => void }) {
  const topic = next && next.kind !== 'home' ? (topics.find((item) => item.id === next.topic) ?? null) : null
  if (topics.length === 0) return <p className="rounded-lg border border-line bg-surface p-4 text-base text-ink-2">{s.noLessons}</p>
  if (!next || !topic) {
    return (
      <div className="flex flex-col gap-3 rounded-xl bg-deep p-4 text-on-deep">
        <p className="check-pop text-lg font-semibold">{s.allTopicsDone}</p>
        <button
          type="button"
          onClick={() => onOpen({ kind: 'topic', topic: topics[0].id })}
          className="inline-flex min-h-11 items-center justify-center self-start rounded-pill bg-mint px-5 text-base font-semibold text-ink hover:bg-mint-tint"
        >
          {s.reviewTopic}
        </button>
      </div>
    )
  }
  const doneHere = topic.lessons.filter((id) => done.includes(id)).length
  const count = s.lessonCount(doneHere, topic.lessons.length)
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-deep p-4 text-on-deep">
      <p className="text-sm font-semibold text-on-deep-muted">
        {s.continueTitle} · {s.topics[topic.id]}
      </p>
      <p className="text-lg font-semibold">{next.kind === 'lesson' ? s.lessons[next.lesson] : s.quizStep(miniTest(topic.id, 'en').length)}</p>
      <Bar done={doneHere} total={topic.lessons.length} label={`${s.topics[topic.id]}: ${count}`} onDeep />
      <p className="text-sm text-on-deep-muted">{count}</p>
      <button
        type="button"
        onClick={() => onOpen(next)}
        className="mt-1 inline-flex min-h-11 items-center justify-center self-start rounded-pill bg-mint px-5 text-base font-semibold text-ink hover:bg-mint-tint"
      >
        {next.kind === 'quiz' ? s.quizNext : s.continue}
      </button>
    </div>
  )
}

/** A topic: its lessons as a path (done ✓, next ●, not started ○; each opens), then its quiz. */
function TopicScreen({
  topic,
  s,
  state,
  done,
  onBack,
  onOpen,
}: {
  topic: Topic
  s: Strings
  state: TopicState
  done: string[]
  onBack: () => void
  onOpen: (view: View) => void
}) {
  const doneHere = state.done
  const allDone = state.lessonsDone
  const score = state.score
  const current = topic.lessons.find((id) => !done.includes(id)) ?? null
  const quizLength = miniTest(topic.id, 'en').length
  return (
    <section aria-labelledby="topic-title" className="flex flex-col gap-4">
      <BackButton label={s.title} onBack={onBack} />
      <div className="flex items-center gap-3">
        <TopicIcon topic={topic.id} />
        <div className="flex min-w-0 flex-col">
          <h2 id="topic-title" className="text-xl font-bold text-ink">
            {s.topics[topic.id]}
          </h2>
          <p className="text-sm text-ink-2">{s.lessonCount(doneHere, topic.lessons.length)}</p>
        </div>
      </div>
      {state.complete && (
        <p className="flex items-center gap-2 text-base font-semibold text-brand" role="status">
          <span aria-hidden="true" className="check-pop inline-flex size-7 items-center justify-center rounded-pill bg-mint text-ink">
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          {s.topicDone}
        </p>
      )}
      <ol className="flex flex-col">
        {topic.lessons.map((id) => {
          const finished = done.includes(id)
          const isCurrent = id === current
          return (
            <PathStep
              key={id}
              mark={finished ? 'done' : isCurrent ? 'current' : 'upcoming'}
              label={s.lessons[id] ?? id}
              state={finished ? s.stepDone : isCurrent ? s.stepCurrent : s.stepUpcoming}
              line={quizLength > 0 || id !== topic.lessons[topic.lessons.length - 1]}
              onOpen={() => onOpen({ kind: 'lesson', topic: topic.id, lesson: id })}
            />
          )
        })}
        {quizLength > 0 && (
          <PathStep
            mark={state.passed ? 'done' : allDone || state.retry ? 'current' : 'upcoming'}
            label={s.quizStep(quizLength)}
            state={state.retry ? s.quizRetry(score ?? 0, quizLength) : score !== undefined ? s.testScore(score, quizLength) : allDone ? s.stepCurrent : s.stepUpcoming}
            detail={state.retry ? `${s.quizRetry(score ?? 0, quizLength)} · ${s.retry}` : score !== undefined ? s.testScore(score, quizLength) : undefined}
            line={false}
            onOpen={() => onOpen({ kind: 'quiz', topic: topic.id })}
          />
        )}
      </ol>
    </section>
  )
}

function PathStep({
  mark,
  label,
  state,
  detail,
  line,
  onOpen,
}: {
  mark: 'done' | 'current' | 'upcoming'
  label: string
  state: string
  detail?: string
  line: boolean
  onOpen: () => void
}) {
  return (
    <li className="relative">
      {line && <span aria-hidden="true" className="absolute top-12 -bottom-2 left-[19px] w-0.5 bg-line" />}
      <button
        type="button"
        onClick={onOpen}
        aria-label={`${label}, ${state}`}
        className="flex min-h-14 w-full items-center gap-3 rounded-lg py-2 pr-2 text-left hover:bg-sunken"
      >
        <span
          aria-hidden="true"
          className={`relative z-10 inline-flex size-10 shrink-0 items-center justify-center rounded-pill ${
            mark === 'done' ? 'bg-mint text-ink' : mark === 'current' ? 'border-[3px] border-brand bg-surface' : 'border-2 border-line-strong bg-surface'
          }`}
        >
          {mark === 'done' ? (
            <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : mark === 'current' ? (
            <span className="size-3 rounded-pill bg-brand" />
          ) : null}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className={`text-base ${mark === 'upcoming' ? 'text-ink-2' : 'font-semibold text-ink'}`}>{label}</span>
          {detail && <span className="text-sm text-ink-2">{detail}</span>}
        </span>
      </button>
    </li>
  )
}

/** The glossary: a search field, then the terms A–Z as an accordion. */
function Glossary({ s }: { s: Strings }) {
  const { lang } = useSettings()
  const opening = useOpening()
  const overview = opening?.overview ?? null
  const [query, setQuery] = useState('')
  const searchId = useId()
  const entries = useMemo(() => [...glossary(overview, lang)].sort((a, b) => a.term.localeCompare(b.term, lang)), [overview, lang])
  const needle = query.trim().toLowerCase()
  const shown = needle ? entries.filter((entry) => `${entry.term} ${entry.text}`.toLowerCase().includes(needle)) : entries
  return (
    <section aria-label={s.glossaryTitle} className="flex flex-col gap-3">
      <label htmlFor={searchId} className="sr-only">
        {s.searchLabel}
      </label>
      <input
        id={searchId}
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={s.searchPlaceholder}
        autoComplete="off"
        className="h-12 rounded-pill border border-line-strong bg-surface px-4 text-base text-ink placeholder:text-muted"
      />
      <p className="text-sm text-ink-2">{s.glossaryIntro}</p>
      {shown.length === 0 ? (
        <p className="text-base text-ink-2" role="status">
          {s.noMatch}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
          {shown.map((entry) => (
            <li key={entry.id}>
              <details className="group px-4">
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-base font-semibold text-ink [&::-webkit-details-marker]:hidden">
                  {entry.term}
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
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
      )}
    </section>
  )
}
