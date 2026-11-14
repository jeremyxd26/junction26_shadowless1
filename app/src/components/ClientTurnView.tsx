import { Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { prefersReducedMotion } from '../lib/motion.ts'
import { useSettings } from '../lib/settings.ts'
import type { ClientTurn } from '../lib/thread.ts'
import { landBelowHeader, landingTop } from '../lib/threadScroll.ts'
import { useTurnHold } from '../lib/useTurnHold.ts'
import { ClientTurnBoundary } from './ClientTurnBoundary.tsx'
import { clientTurns } from './clientTurns.tsx'
import { LoadingBlock } from './States.tsx'

/**
 * A client turn (#319): the tapped chip as the user's bubble, Sentti's label (the thread passes it
 * without the AI tag), then the registered component. Each step it reports is announced once in
 * the turn's own `role="status"` region (whether or not the turn is the latest) and gets the focus
 * on its heading. While a step waits for the API the turn is `aria-busy`, as a streaming answer is
 * (#332). No speaker, stages or retry: nothing here comes from the AI model.
 */
export function ClientTurnView({ turn, label }: { turn: ClientTurn; label: ReactNode }) {
  const { lang } = useSettings()
  const entry = clientTurns[turn.render]
  const Component = entry?.Component
  const body = useRef<HTMLDivElement>(null)
  const article = useRef<HTMLElement>(null)
  const [step, setStep] = useState<{ title: string; count: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const { arm } = useTurnHold(article)

  // The thread lands a new turn below the header; hold it there while an answer above still grows.
  // Only the turn being landed takes the hold: the thread's last turn (the one just pushed, or the
  // last one when the thread comes back from /cards or /bill). An older client turn that mounts
  // again never does, so it cannot pull the page off the last answer.
  useEffect(() => {
    const node = article.current
    const turns = node?.parentElement?.parentElement?.querySelectorAll('article[data-turn]')
    if (node && turns && turns[turns.length - 1] === node) arm(node, landingTop(), true)
  }, [arm])

  const onStep = useCallback((title: string) => setStep((current) => ({ title, count: (current?.count ?? 0) + 1 })), [])

  useEffect(() => {
    const heading = step && body.current?.querySelector<HTMLElement>('[data-step-heading]')
    if (!heading || !article.current) return
    // Someone typing in the composer keeps the focus there; the step is still announced.
    const active = document.activeElement
    const typing = active?.matches('input, textarea, select, [contenteditable="true"]') && !body.current?.contains(active)
    if (!typing) heading.focus({ preventScroll: true })
    if (step.count === 1) return
    // A later step lands at its heading below the header and holds there, unless the heading already
    // sits just below it: a step that replaces a long one (the explanation after the fields) would
    // otherwise leave the reader mid-page. A reader who has scrolled the turn out of view stays put.
    const turnBox = article.current.getBoundingClientRect()
    if (turnBox.bottom <= 0 || turnBox.top >= window.innerHeight) return
    const top = heading.getBoundingClientRect().top
    const below = landingTop()
    if (top < below || top > below + window.innerHeight / 4) {
      landBelowHeader(heading, !prefersReducedMotion())
      arm(heading, below, true)
    } else {
      arm(heading, top)
    }
  }, [step, arm])

  return (
    <article
      ref={article}
      data-turn={turn.id}
      data-client-turn={turn.render}
      aria-busy={busy}
      // Never the browser's scroll anchor: its steps replace each other (a loading block becomes the
      // sample gallery when the thread comes back from /cards), and an anchor inside them would be
      // lost, pushing a later answer down. A later turn anchors instead; above this turn the hold works.
      className="flex flex-col gap-3 [overflow-anchor:none]"
    >
      {/* The same bubble as an ask turn's question (AnswerView). */}
      <p className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-deep px-4 py-3 text-base break-words whitespace-pre-wrap text-on-deep">
        {turn.question}
      </p>
      <div className="flex min-h-11 items-center">{label}</div>
      <div ref={body} className="flex flex-col gap-3">
        {Component && (
          <ClientTurnBoundary
            lang={lang}
            screen={entry.screen ? { path: entry.screen, label: entry.chip(lang) } : undefined}
            onFailed={() => setBusy(false)}
          >
            <Suspense fallback={<Pending onBusy={setBusy} />}>
              <Component turnId={turn.id} onStep={onStep} onBusy={setBusy} />
            </Suspense>
          </ClientTurnBoundary>
        )}
      </div>
      <p role="status" className="sr-only">
        {step?.title ?? ''}
      </p>
    </article>
  )
}

/** While the component's code loads, the turn is busy; the component reports its own state once it runs. */
function Pending({ onBusy }: { onBusy: (busy: boolean) => void }) {
  useEffect(() => onBusy(true), [onBusy])
  return <LoadingBlock lines={3} />
}
