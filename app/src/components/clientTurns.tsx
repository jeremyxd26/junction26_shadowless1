// Client turns (#319): Sentti turns the app draws itself, without POST /api/ask. A chip in the
// opening pushes one into the thread: the chip's text becomes the user's bubble, and the
// registered component draws Sentti's part. The bill flow (#332) is the first one.
import { lazy, type ComponentType } from 'react'
import { BILL_LIVE } from '../api/bill.ts'
import { api } from '../api/client.ts'
import type { Language } from '../api/types.ts'
import { billStrings } from '../lib/billStrings.ts'
import type { ClientTurnRequest } from '../lib/thread.ts'
import { LessonTurn } from './lesson/LessonTurn.tsx'
import { lessonStrings } from './lesson/lessonStrings.ts'

/** What the thread gives a registered component. */
export interface ClientTurnProps {
  /** The turn's id in the thread (`data-turn`). */
  turnId: number
  /**
   * Call it when a step is on screen (the first one included), with the step's title. The turn
   * announces the title once in its `role="status"` region and moves focus to the step's heading,
   * the element with `data-step-heading` and `tabIndex={-1}`.
   */
  onStep: (title: string) => void
  /** Call it with true while a step waits for the API, false once it is shown; the turn sets `aria-busy`. */
  onBusy: (busy: boolean) => void
}

export interface ClientTurnEntry {
  /** The chip's text, which also becomes the user's bubble. */
  chip: (lang: Language) => string
  /** Whether the chip shows, for example only in mock mode or behind a flag. */
  visible: () => boolean
  /** The same content as a screen of its own; the turn links to it when its code fails to load. */
  screen?: string
  /** Loads the component's code ahead of the first tap (#728): the same import `Component` uses. */
  prefetch?: () => Promise<unknown>
  Component: ComponentType<ClientTurnProps>
}

/** The bill flow's code: one import, shared by the prefetch and the first bill turn. */
function loadBillFlow() {
  return import('./bill/BillFlow.tsx')
}

/** The registry: `render` key → the component that draws the turn. */
export const clientTurns: Record<string, ClientTurnEntry> = {
  // "Show Sentti a bill" (#332): gallery → reading → fields → explanation → Add to payments, in the
  // thread. Only where the bills match the persona: in mock mode, or live with the core's bills on.
  // The flow's code is its own chunk, loaded at idle once the opening shows (#728), so a tab left
  // open across a redeploy (which deletes the old chunks) already has it when the bill is tapped.
  bill: {
    chip: (lang) => billStrings(lang).chip,
    visible: () => api.mode === 'mock' || BILL_LIVE,
    screen: '/bill',
    prefetch: loadBillFlow,
    Component: lazy(() => loadBillFlow().then((module) => ({ default: module.BillFlow }))),
  },
  // "Lesson of the day" (#703): a question about the user's own number, then the reveal. Always
  // shown; a profile without a lesson gets one sentence instead.
  lesson: { chip: (lang) => lessonStrings(lang).chip, visible: () => true, Component: LessonTurn },
}

/** The registry keys whose chips the opening shows under its overview row, in this order. */
export const openingChips: string[] = ['bill']

/** What a tap on `key`'s chip (or the composer's paperclip, #705) pushes: its text, its component, one turn per key. */
export function clientTurnRequest(key: string, lang: Language): ClientTurnRequest {
  return { question: clientTurns[key].chip(lang), render: key, id: key }
}

let prefetched = false

/**
 * Loads the code of every visible client turn once, when the browser is idle after the opening has
 * rendered (#728). A tab left open across a redeploy then needs no old chunk when the bill is tapped,
 * and the first tap is instant. A failed prefetch is left to the turn's own error boundary.
 */
export function prefetchClientTurns() {
  if (prefetched) return
  prefetched = true
  const run = () => {
    for (const entry of Object.values(clientTurns)) {
      if (entry.prefetch && entry.visible()) entry.prefetch().catch(() => {})
    }
  }
  if (typeof window.requestIdleCallback === 'function') window.requestIdleCallback(run, { timeout: 4000 })
  else window.setTimeout(run, 1500)
}
