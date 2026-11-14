// How a number chip's text may break across lines (#493), kept apart from NumberChip so it can be
// tested without the browser. The text is never changed.
import { Fragment } from 'react'
import { displayParts } from '../lib/displayParts.ts'

/** The display as is, broken only between the amount and the words after it (#493). */
export function DisplayText({ text }: { text: string }) {
  // Each part (the amount, then the words after it) stays whole; the only place to break is the
  // plain space between them, so "€780.00 a month" wraps as "€780.00" / "a month", never
  // "€780.00 a" / "month". The text itself is unchanged.
  return (
    <span className="[text-wrap:balance]">
      {displayParts(text).map((part, index) => {
        const [, before, body, after] = /^(\s*)([\s\S]*?)(\s*)$/.exec(part.text) ?? ['', '', part.text, '']
        return (
          <Fragment key={index}>
            {before}
            {body && <span className="whitespace-nowrap">{body}</span>}
            {after}
          </Fragment>
        )
      })}
    </span>
  )
}
