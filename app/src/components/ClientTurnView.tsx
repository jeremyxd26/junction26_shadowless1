import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import type { ClientTurn } from '../lib/thread.ts'
import { clientTurns } from './clientTurns.tsx'

/**
 * A client turn (#319): the tapped chip as the user's bubble, Sentti's label (the thread passes it
 * without the AI tag), then the registered component. Each step it reports is announced once in
 * the turn's own `role="status"` region (whether or not the turn is the latest) and gets the focus
 * on its heading. No speaker, stages or retry: nothing here comes from the API.
 */
export function ClientTurnView({ turn, label }: { turn: ClientTurn; label: ReactNode }) {
  const Component = clientTurns[turn.render]?.Component
  const body = useRef<HTMLDivElement>(null)
  const [step, setStep] = useState<{ title: string; count: number } | null>(null)
  const onStep = useCallback((title: string) => setStep((current) => ({ title, count: (current?.count ?? 0) + 1 })), [])

  useEffect(() => {
    const heading = step && body.current?.querySelector<HTMLElement>('[data-step-heading]')
    if (!heading) return
    // Someone typing in the composer keeps the focus there; the step is still announced.
    const active = document.activeElement
    if (active?.matches('input, textarea, select, [contenteditable="true"]') && !body.current?.contains(active)) return
    heading.focus({ preventScroll: true })
    // The thread brings a new turn to the top itself; a later step may start lower down.
    if (step.count > 1) heading.scrollIntoView({ block: 'nearest' })
  }, [step])

  return (
    <article data-turn={turn.id} data-client-turn={turn.render} className="flex scroll-mt-16 flex-col gap-3">
      {/* The same bubble as an ask turn's question (AnswerView). */}
      <p className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-deep px-4 py-3 text-base break-words whitespace-pre-wrap text-on-deep">
        {turn.question}
      </p>
      <div className="flex min-h-11 items-center">{label}</div>
      <div ref={body} className="flex flex-col gap-3">
        {Component && <Component turnId={turn.id} onStep={onStep} />}
      </div>
      <p role="status" className="sr-only">
        {step?.title ?? ''}
      </p>
    </article>
  )
}
