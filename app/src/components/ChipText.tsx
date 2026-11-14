// How a number chip's text may break across lines (#493), kept apart from NumberChip so it can be
// tested without the browser. The text is never changed.
import { Fragment } from 'react'
import { displaySegments } from '../lib/displayParts.ts'

/**
 * The display as is, broken only between the amount and the words after it (#493). Each segment
 * keeps the space that follows it, so kerning is as in one text, and `<wbr>` after it is the only
 * place to break: "€780.00 a month" wraps as "€780.00" / "a month", never "€780.00 a" / "month".
 */
export function DisplayText({ text }: { text: string }) {
  return (
    <span className="[text-wrap:balance]">
      {displaySegments(text).map((segment, index) => (
        <Fragment key={index}>
          {index > 0 && <wbr />}
          <span className="whitespace-nowrap">{segment}</span>
        </Fragment>
      ))}
    </span>
  )
}
