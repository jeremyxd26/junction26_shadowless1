import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { BottomSheet } from './BottomSheet.tsx'

describe('the bottom sheet grabber', () => {
  const html = renderToStaticMarkup(
    <BottomSheet title="What if" onClose={() => {}}>
      <p>content</p>
    </BottomSheet>,
  )

  it('is centred on the sheet, 36 x 4 px and rounded, in a 56 px tall drag strip', () => {
    expect(html).toMatch(
      /<div data-sheet-handle="" aria-hidden="true" class="flex h-14 [^"]*items-center justify-center[^"]*"><div class="h-1 w-9 rounded-pill [^"]*"><\/div><\/div>/,
    )
  })

  it('keeps the close button and the labelled dialog; the title row drags too', () => {
    expect(html).toContain('role="dialog" aria-modal="true"')
    expect(html).toMatch(/<button type="button" aria-label="Close" class="group absolute top-2 right-2.5 inline-flex size-11/)
    // A 36 px circle inside the 44 px target: inset from the sheet's rounded corner (#942).
    expect(html).toContain('class="inline-flex size-9 items-center justify-center rounded-pill bg-sunken')
    expect(html).toMatch(/<h2 id="[^"]+" data-sheet-handle="" class="[^"]*">What if<\/h2>/)
  })
})
