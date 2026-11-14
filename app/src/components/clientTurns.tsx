// Client turns (#319): Sentti turns the app draws itself, without POST /api/ask. A chip in the
// opening pushes one into the thread: the chip's text becomes the user's bubble, and the
// registered component draws Sentti's part. The bill flow (#332) is the first one.
import type { ComponentType } from 'react'
import type { Language } from '../api/types.ts'

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
}

export interface ClientTurnEntry {
  /** The chip's text, which also becomes the user's bubble. */
  chip: (lang: Language) => string
  /** Whether the chip shows, for example only in mock mode or behind a flag. */
  visible: () => boolean
  Component: ComponentType<ClientTurnProps>
}

/** The registry: `render` key → the component that draws the turn. */
export const clientTurns: Record<string, ClientTurnEntry> = {}

/** The registry keys whose chips the opening shows after its suggested questions, in this order. */
export const openingChips: string[] = []
