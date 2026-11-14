// Client turns (#319): Sentti turns the app draws itself, without POST /api/ask. A chip in the
// opening pushes one into the thread: the chip's text becomes the user's bubble, and the
// registered component draws Sentti's part. The bill flow (#332) is the first one.
import { useEffect, useState, type ComponentType } from 'react'
import type { Language } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'

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

// PLACEHOLDER for the #319 screenshots only; the last commit of the PR removes it.
function Placeholder({ onStep }: ClientTurnProps) {
  const { lang } = useSettings()
  const [step, setStep] = useState(1)
  const fi = lang === 'fi'
  const title = fi ? `Vaihe ${step}/2` : `Step ${step} of 2`
  useEffect(() => onStep(title), [title, onStep])
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <h3 data-step-heading tabIndex={-1} className="text-lg font-bold text-ink">
        {title}
      </h3>
      <p className="text-base text-ink-2">
        {fi ? 'Väliaikainen asiakasvuoro: ei kutsua palvelimelle.' : 'A placeholder client turn: nothing is sent to the server.'}
      </p>
      {step === 1 && (
        <button
          type="button"
          onClick={() => setStep(2)}
          className="inline-flex min-h-11 items-center self-start rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand"
        >
          {fi ? 'Seuraava' : 'Next'}
        </button>
      )}
    </div>
  )
}

/** The registry: `render` key → the component that draws the turn. */
export const clientTurns: Record<string, ClientTurnEntry> = {
  placeholder: { chip: (lang) => (lang === 'fi' ? 'Näytä väliaikainen vuoro' : 'Show a placeholder turn'), visible: () => true, Component: Placeholder },
}

/** The registry keys whose chips the opening shows after its suggested questions, in this order. */
export const openingChips: string[] = ['placeholder']
