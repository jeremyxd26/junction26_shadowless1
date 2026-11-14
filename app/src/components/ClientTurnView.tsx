import { Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { prefersReducedMotion } from '../lib/motion.ts'
import type { ClientTurn } from '../lib/thread.ts'
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
  const Component = clientTurns[turn.render]?.Component
  const body = useRef<HTMLDivElement>(null)
  const [step, setStep] = useState<{ title: string; count: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const article = useRef<HTMLElement>(null)

  // An answer above may still be streaming when this turn arrives (#332). Keep this turn where the
  // reader sees it while something above changes height: the browser's scroll anchoring loses its
  // anchor when the answer swaps its skeleton for a card, and Safari has none. A scroll by the
  // reader (or the thread's own scroll to a new turn) is left alone.
  useEffect(() => {
    const node = article.current
    if (!node) return
    let top = node.getBoundingClientRect().top
    let scrolledAt = 0
    let ownScrollY: number | null = null
    const onScroll = () => {
      if (ownScrollY === window.scrollY) ownScrollY = null
      else scrolledAt = performance.now()
      top = node.getBoundingClientRect().top
    }
    const observer = new ResizeObserver(() => {
      const moved = node.getBoundingClientRect().top - top
      const inView = top >= 0 && top < window.innerHeight
      if (moved !== 0 && inView && performance.now() - scrolledAt > 150) {
        window.scrollBy(0, moved)
        ownScrollY = window.scrollY
      }
      top = node.getBoundingClientRect().top
    })
    window.addEventListener('scroll', onScroll, { passive: true })
    observer.observe(document.body)
    return () => {
      window.removeEventListener('scroll', onScroll)
      observer.disconnect()
    }
  }, [])
  const onStep = useCallback((title: string) => setStep((current) => ({ title, count: (current?.count ?? 0) + 1 })), [])

  useEffect(() => {
    const heading = step && body.current?.querySelector<HTMLElement>('[data-step-heading]')
    if (!heading) return
    // Someone typing in the composer keeps the focus there; the step is still announced.
    const active = document.activeElement
    if (active?.matches('input, textarea, select, [contenteditable="true"]') && !body.current?.contains(active)) return
    heading.focus({ preventScroll: true })
    // The thread brings a new turn to the top itself. A later step starts at its heading, under the
    // header, unless the heading already sits just below it: a step that replaces a long one (the
    // explanation after the fields) would otherwise leave the reader somewhere in the middle.
    const { top } = heading.getBoundingClientRect()
    const header = parseFloat(getComputedStyle(heading).scrollMarginTop) || 0
    if (step.count > 1 && (top < header || top > header + window.innerHeight / 4)) {
      heading.scrollIntoView({ block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
    }
  }, [step])

  return (
    <article
      ref={article}
      data-turn={turn.id}
      data-client-turn={turn.render}
      aria-busy={busy}
      className="flex scroll-mt-16 flex-col gap-3"
    >
      {/* The same bubble as an ask turn's question (AnswerView). */}
      <p className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-deep px-4 py-3 text-base break-words whitespace-pre-wrap text-on-deep">
        {turn.question}
      </p>
      <div className="flex min-h-11 items-center">{label}</div>
      <div ref={body} className="flex flex-col gap-3 [&_[data-step-heading]]:scroll-mt-16">
        {Component && (
          <Suspense fallback={<LoadingBlock lines={3} />}>
            <Component turnId={turn.id} onStep={onStep} onBusy={setBusy} />
          </Suspense>
        )}
      </div>
      <p role="status" className="sr-only">
        {step?.title ?? ''}
      </p>
    </article>
  )
}
