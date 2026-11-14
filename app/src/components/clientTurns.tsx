// Client turns (#319): Sentti turns the app draws itself, without POST /api/ask. A chip in the
// opening pushes one into the thread: the chip's text becomes the user's bubble, and the
// registered component draws Sentti's part. The bill flow (#332) is the first one.
import { lazy, type ComponentType } from 'react'
import { BILL_LIVE } from '../api/bill.ts'
import { api } from '../api/client.ts'
import type { Language } from '../api/types.ts'
import { billStrings } from '../lib/billStrings.ts'

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
  Component: ComponentType<ClientTurnProps>
}

/** The registry: `render` key → the component that draws the turn. */
export const clientTurns: Record<string, ClientTurnEntry> = {
  // "Show Sentti a bill" (#332): gallery → reading → fields → explanation → Add to payments, in the
  // thread. Only where the bills match the persona: in mock mode, or live with the core's bills on.
  // The flow's code loads with the first bill turn, as `/bill` and `/cards` load it.
  bill: {
    chip: (lang) => billStrings(lang).chip,
    visible: () => api.mode === 'mock' || BILL_LIVE,
    screen: '/bill',
    Component: lazy(() => import('./bill/BillFlow.tsx').then((module) => ({ default: module.BillFlow }))),
  },
}

/** The registry keys whose chips the opening shows under its overview row, in this order. */
export const openingChips: string[] = ['bill']
