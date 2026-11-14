// One turn of the chat: the question, then Sentti's answer in the Sentti answer shape
// (DESIGN.md "Answer order" and "States"): takeaway → card(s) → explanation → lesson →
// action chips → follow-up chips. While the stream runs: the stages and a card skeleton.
import type { Action } from '../api/types.ts'
import { STAGES, actionsOf, splitTakeaway, withoutPartialToken, writtenByTemplate, type Answer } from '../lib/answer.ts'
import { chatStrings, errorMessage } from '../lib/chatStrings.ts'
import { hostScreenTarget, openHostScreen } from '../lib/hostActions.ts'
import { openEvidence, openWhatIf } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import type { Turn } from '../lib/useChat.ts'
import { AnswerCard } from './AnswerCard.tsx'
import { TokenText } from './cards.tsx'
import { ErrorBlock } from './States.tsx'

type Strings = ReturnType<typeof chatStrings>

export const ACTION_CHIP =
  'inline-flex min-h-11 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-left text-base font-semibold text-brand hover:bg-mint-tint'
export const QUESTION_CHIP =
  'inline-flex min-h-11 items-center rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-semibold text-ink hover:bg-mint'

/** Answer text with number chips: 16 px, with room for the 32 px inline chips. */
const ANSWER_TEXT = 'text-base leading-8 text-ink-2'
const TAKEAWAY = 'text-xl font-bold leading-9 text-ink'

export function InfoIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="mt-0.5 size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
    </svg>
  )
}

export function SenttiLabel({ s }: { s: Strings }) {
  return (
    <p className="flex items-center gap-1.5 text-sm font-bold text-brand">
      {s.sentti}
      <span className="rounded-sm border border-brand px-1 text-xs font-bold">AI</span>
    </p>
  )
}

function StageIcon({ state }: { state: 'done' | 'now' | 'todo' }) {
  if (state === 'done') {
    return (
      <span aria-hidden="true" className="inline-flex size-6 shrink-0 items-center justify-center rounded-pill bg-mint text-ink">
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="3">
          <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    )
  }
  if (state === 'now') {
    return <span aria-hidden="true" className="size-6 shrink-0 animate-spin rounded-pill border-[3px] border-sunken border-t-brand" />
  }
  return <span aria-hidden="true" className="size-6 shrink-0 rounded-pill border-2 border-line-strong/50" />
}

/** "Reading your question → Checking your transactions → Writing", labels from `status`. */
function Stages({ answer, s }: { answer: Answer; s: Strings }) {
  return (
    <ol aria-label={s.stagesLabel} className="flex flex-col">
      {STAGES.map((key, index) => {
        const state = index < answer.stage ? 'done' : index === answer.stage ? 'now' : 'todo'
        const tone = state === 'now' ? 'font-semibold text-ink-2' : state === 'done' ? 'text-ink-2' : 'text-muted'
        return (
          <li key={key} className="flex min-h-9 items-center gap-3">
            <StageIcon state={state} />
            <span className={`text-base ${tone}`}>{answer.labels[key] ?? s.stages[key]}</span>
            {state !== 'todo' && <span className="sr-only">, {state === 'done' ? s.stageDone : s.stageNow}</span>}
          </li>
        )
      })}
    </ol>
  )
}

function CardSkeleton() {
  return (
    <div aria-hidden="true" className="rounded-lg border border-line bg-surface p-4">
      <div className="h-5 w-3/5 animate-pulse rounded-pill bg-sunken" />
      <div className="mt-2 h-3.5 w-2/5 animate-pulse rounded-pill bg-sunken" />
      <div className="mt-5 h-11 w-1/2 animate-pulse rounded-md bg-sunken" />
      <div className="mt-5 h-3 w-full animate-pulse rounded-pill bg-sunken" />
      <div className="mt-3 h-3 w-11/12 animate-pulse rounded-pill bg-sunken" />
      <div className="mt-3 h-3 w-4/5 animate-pulse rounded-pill bg-sunken" />
    </div>
  )
}

function ActionChip({ action, onAsk }: { action: Action; onAsk: (question: string) => void }) {
  if (action.type === 'open_evidence') {
    return (
      <button type="button" className={ACTION_CHIP} onClick={() => openEvidence(action.evidence_ref)}>
        {action.label}
      </button>
    )
  }
  if (action.type === 'ask') {
    return (
      <button type="button" className={ACTION_CHIP} onClick={() => onAsk(action.prompt)}>
        {action.label}
      </button>
    )
  }
  if (action.type === 'open_whatif') {
    // The what-if sheet (#154) takes the action's scenario unchanged.
    return (
      <button type="button" className={ACTION_CHIP} onClick={() => openWhatIf(action.scenario)}>
        {action.label}
      </button>
    )
  }
  if (action.type === 'open_host_screen') {
    // Into the bank app's own screen (#268); a target the app does not know renders nothing.
    const target = hostScreenTarget(action.target)
    if (!target) return null
    return (
      <button type="button" className={ACTION_CHIP} onClick={() => openHostScreen(target)}>
        {action.label}
      </button>
    )
  }
  return null
}

function QuestionChips({ questions, onAsk }: { questions: string[]; onAsk: (question: string) => void }) {
  if (questions.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-2">
      {questions.map((question) => (
        <li key={question}>
          <button type="button" className={QUESTION_CHIP} onClick={() => onAsk(question)}>
            {question}
          </button>
        </li>
      ))}
    </ul>
  )
}

interface Props {
  turn: Turn
  /** Only the latest turn offers follow-ups, clarify options and announces itself. */
  latest: boolean
  suggestions: string[]
  onAsk: (question: string) => void
  onRetry: () => void
}

export function TurnView({ turn, latest, suggestions, onAsk, onRetry }: Props) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const { answer } = turn
  const { done } = answer
  const streaming = answer.status === 'streaming'
  const outcome = done?.outcome
  const hasContent = answer.cards.length > 0 || answer.text.length > 0
  const followUps = latest && done ? done.follow_ups : []

  let body
  if (done && outcome === 'refused') {
    // Off-topic: a normal bubble with a grey rule, the refusal label, the template text.
    body = (
      <div className="border-l-4 border-line-strong pl-4">
        {done.refusal && <p className="text-xs font-semibold text-muted">{done.refusal.label}</p>}
        <p className={`mt-1 ${ANSWER_TEXT}`}>
          <TokenText text={answer.text} numbers={answer.numbers} />
        </p>
      </div>
    )
  } else if (done && outcome === 'clarify' && done.clarify) {
    body = (
      <>
        <p className={TAKEAWAY}>{done.clarify.question}</p>
        {latest && (
          <>
            <QuestionChips questions={done.clarify.options} onAsk={onAsk} />
            <p className="text-sm text-muted">{s.orType}</p>
          </>
        )}
      </>
    )
  } else {
    // Answered and fallback share one layout, so nothing changes its look when `done` arrives;
    // a fallback shows the service's short text as it is, with the cards. Until a card arrives, the text waits for `done`: an
    // answer without cards may still turn out to be a refusal or a clarification, which look
    // different, so the stages and the skeleton stay until then.
    const holdText = streaming && answer.cards.length === 0
    const { takeaway, rest } = holdText ? { takeaway: '', rest: '' } : splitTakeaway(answer.text)
    body = (
      <>
        {takeaway && (
          <p className={TAKEAWAY}>
            <TokenText text={takeaway} numbers={answer.numbers} />
          </p>
        )}
        {answer.cards.map((card) => (
          <AnswerCard key={card.card_id} card={card} />
        ))}
        {holdText && <CardSkeleton />}
        {rest && (
          <p className={ANSWER_TEXT}>
            <TokenText text={withoutPartialToken(rest)} numbers={answer.numbers} />
          </p>
        )}
      </>
    )
  }

  const actions = done && outcome !== 'refused' && outcome !== 'clarify' ? actionsOf(answer.cards) : []

  return (
    <article data-turn={turn.id} aria-busy={streaming} className="flex scroll-mt-16 flex-col gap-3">
      <p className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-deep px-4 py-3 text-base break-words whitespace-pre-wrap text-on-deep">
        {turn.question}
      </p>

      {(hasContent || streaming || done) && <SenttiLabel s={s} />}
      {streaming && <Stages answer={answer} s={s} />}
      {body}
      {/* Written from the template without the AI model (warning `llm_unavailable`, #282):
          a quiet note under the answer, whatever the outcome. */}
      {writtenByTemplate(done) && (
        <p className="flex gap-2 text-sm text-muted">
          <InfoIcon />
          {s.templateNote}
        </p>
      )}

      {done?.lesson && (
        <aside className="rounded-md bg-sunken p-4">
          <p className="text-sm font-semibold text-ink">{done.lesson.title}</p>
          <p className="mt-1 text-sm text-muted">{done.lesson.text}</p>
        </aside>
      )}
      {actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {actions.map((action, index) => (
            <ActionChip key={`${action.type}-${index}`} action={action} onAsk={onAsk} />
          ))}
        </div>
      )}
      <QuestionChips questions={followUps} onAsk={onAsk} />

      {answer.status === 'error' && answer.error && (
        <>
          <ErrorBlock message={errorMessage(answer.error, s)} onRetry={answer.error.retryable ? onRetry : undefined} />
          {latest && <QuestionChips questions={suggestions.filter((q) => q !== turn.question).slice(0, 2)} onAsk={onAsk} />}
        </>
      )}
      {answer.status === 'stopped' && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-muted">{s.stopped}</p>
          <button type="button" className={ACTION_CHIP} onClick={onRetry}>
            {s.askAgain}
          </button>
        </div>
      )}

      {/* Screen readers hear the stage while waiting, then the whole answer once, without tokens. */}
      {latest && (
        <p role="status" className="sr-only">
          {streaming
            ? (answer.labels[STAGES[answer.stage]] ?? s.stages[STAGES[answer.stage]])
            : done
              ? done.text_rendered
              : ''}
        </p>
      )}
    </article>
  )
}
