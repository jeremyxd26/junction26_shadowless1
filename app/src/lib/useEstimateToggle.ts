import { useId, useState } from 'react'

/**
 * State for a card that shows the estimate text full width under its header, so the open
 * text never narrows the card title: pass `control` to `<EstimateBadge>` and render
 * `<EstimateNote id={id}>` when `open`.
 */
export function useEstimateToggle() {
  const [open, setOpen] = useState(false)
  const id = useId()
  return { open, id, control: { open, onToggle: () => setOpen((value) => !value), textId: id } }
}
