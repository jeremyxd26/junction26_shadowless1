// One turn of the chat: the question, then Sentti's answer in the Sentti answer shape
// (DESIGN.md "Answer order" and "States"): takeaway → card(s) → explanation → lesson → at most
// one next step (#684). While the stream runs: the stages and a card skeleton. The answer carries
// no AI line and no source label; the AI disclosure is behind the header's ⓘ (#685).
import type { Action } from '../api/types.ts'
import { STAGES, splitTakeaway, withoutPartialToken, writtenByTemplate, type Answer } from '../lib/answer.ts'
import { chatStrings, errorMessage } from '../lib/chatStrings.ts'
import { hostScreenTarget, openHostScreen } from '../lib/hostActions.ts'
import { captionOf } from '../lib/answerFigures.ts'
import { nextStep } from '../lib/nextStep.ts'
import { openEvidence, openWhatIf } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import { isClientTurn } from '../lib/thread.ts'
import type { Turn } from '../lib/useChat.ts'
import { AnswerCard } from './AnswerCard.tsx'
import { ClientTurnView } from './ClientTurnView.tsx'
import { TokenText } from './cards.tsx'
import { SpeakButton } from './SpeakButton.tsx'
import { ErrorBlock } from './States.tsx'

type Strings = ReturnType<typeof chatStrings>

export const ACTION_CHIP =
  'inline-flex min-h-11 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-left text-base font-semibold text-brand hover:bg-mint-tint'
export const QUESTION_CHIP =
  'inline-flex min-h-11 items-center rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-semibold text-ink hover:bg-mint'

/** Answer text with its numbers as text (#684): 16 px; the line keeps room for the 44 px number targets. */
const ANSWER_TEXT = 'text-base leading-8 text-ink-2'
/** The first sentence: a little larger, in the normal weight, not large bold (#684). */
const TAKEAWAY = 'text-lg leading-8 text-ink'
/** The clarify question keeps its emphasis: it is the whole answer. */
const CLARIFY = 'text-xl font-bold leading-9 text-ink'
/** The one next step: a link-like button, not a pill (#684). */
const NEXT_STEP =
  'inline-flex min-h-11 items-center text-left text-base font-semibold text-brand underline decoration-brand/40 decoration-1 underline-offset-4 hover:decoration-brand'

export function InfoIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="mt-0.5 size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
    </svg>
  )
}

/** "Sentti" with the AI tag; a client turn (#319), which the AI model does not write, shows it without. */
export function SenttiLabel({ s, ai = true }: { s: Strings; ai?: boolean }) {
  return (
    <p className="flex items-center gap-1.5 text-sm font-bold text-brand">
      {s.sentti}
      {ai && <span className="rounded-sm border border-brand px-1 text-xs font-bold">AI</span>}
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

function ActionChip({ action, onAsk, className = ACTION_CHIP }: { action: Action; onAsk: (question: string) => void; className?: string }) {
  if (action.type === 'open_evidence') {
    return (
      <button type="button" className={className} onClick={() => openEvidence(action.evidence_ref)}>
        {action.label}
      </button>
    )
  }
  if (action.type === 'ask') {
    return (
      <button type="button" className={className} onClick={() => onAsk(action.prompt)}>
        {action.label}
      </button>
    )
  }
  if (action.type === 'open_whatif') {
    // The what-if sheet (#154) takes the action's scenario unchanged.
    return (
      <button type="button" className={className} onClick={() => openWhatIf(action.scenario)}>
        {action.label}
      </button>
    )
  }
  if (action.type === 'open_host_screen') {
    // Into the bank app's own screen (#268); a target the app does not know renders nothing.
    const target = hostScreenTarget(action.target)
    if (!target) return null
    return (
      <button type="button" className={className} onClick={() => openHostScreen(target)}>
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
  if (isClientTurn(turn)) return <ClientTurnView turn={turn} label={<SenttiLabel s={s} ai={false} />} />
  const { answer } = turn
  const { done } = answer
  const streaming = answer.status === 'streaming'
  const outcome = done?.outcome
  const hasContent = answer.cards.length > 0 || answer.text.length > 0
  // At most one next step, from what the response carries; a follow-up only on the latest answer
  // (nextStep falls back to the way to a human on an older one).
  const step = nextStep(done, answer.cards, latest)

  let body
  if (done && outcome === 'refused') {
    // Off-topic: a normal bubble with a grey rule, the refusal label, the template text.
    body = (
      <div className="border-l-4 border-line-strong pl-4">
        {done.refusal && <p className="text-xs font-semibold text-muted">{done.refusal.label}</p>}
        <p className={`mt-1 ${ANSWER_TEXT}`}>
          <TokenText text={answer.text} numbers={answer.numbers} plain />
        </p>
      </div>
    )
  } else if (done && outcome === 'clarify' && done.clarify) {
    body = (
      <>
        <p className={CLARIFY}>{done.clarify.question}</p>
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
            <TokenText text={takeaway} numbers={answer.numbers} plain />
          </p>
        )}
        {/* One main number per answer: only the first card draws one large (#684). */}
        {answer.cards.map((card, index) => (
          <AnswerCard
            key={card.card_id}
            card={card}
            later={index > 0}
            previousCaption={index > 0 ? captionOf(answer.cards[index - 1]) : null}
          />
        ))}
        {holdText && <CardSkeleton />}
        {rest && (
          <p className={ANSWER_TEXT}>
            <TokenText text={withoutPartialToken(rest)} numbers={answer.numbers} plain />
          </p>
        )}
      </>
    )
  }

  return (
    <article data-turn={turn.id} aria-busy={streaming} className="flex scroll-mt-16 flex-col gap-3">
      <p className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-deep px-4 py-3 text-base break-words whitespace-pre-wrap text-on-deep">
        {turn.question}
      </p>

      {(hasContent || streaming || done) && (
        <div className="flex min-h-11 items-center justify-between gap-2">
          <SenttiLabel s={s} />
          {done && <SpeakButton id={String(turn.id)} text={done.text_rendered} language={answer.meta?.language ?? lang} />}
        </div>
      )}
      {/* No AI line here: `done.ai_disclosure` is the overview's text, behind the header's ⓘ (#685). */}
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
      {step && (
        <div data-next-step="" className="flex">
          {step.kind === 'action' ? (
            <ActionChip action={step.action} onAsk={onAsk} className={NEXT_STEP} />
          ) : (
            <button type="button" className={NEXT_STEP} onClick={() => onAsk(step.question)}>
              {step.question}
            </button>
          )}
        </div>
      )}

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
