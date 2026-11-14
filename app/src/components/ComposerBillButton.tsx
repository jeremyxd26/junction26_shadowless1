import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { composerBillAction } from './composerBill.ts'

/**
 * A paperclip in the composer that shows Sentti a sample bill (#705): the same client turn as the
 * opening's chip, with the same name. No file input: only the sample gallery. 44 px at any text
 * size, so the input keeps its room at 200 % text.
 */
export function ComposerBillButton() {
  const { lang } = useSettings()
  const action = composerBillAction(useOpening(), lang)
  if (!action) return null
  return (
    <button
      type="button"
      onClick={action.onPress}
      aria-label={action.label}
      className="inline-flex size-[44px] shrink-0 items-center justify-center rounded-pill text-brand hover:bg-mint-tint focus-visible:outline-mint"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[24px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
      </svg>
    </button>
  )
}
