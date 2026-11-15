import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { BottomSheet } from './BottomSheet.tsx'

describe('the bottom sheet grabber', () => {
  const html = renderToStaticMarkup(
    <BottomSheet title="What if" onClose={() => {}}>
      <p>content</p>
    </BottomSheet>,
  )

  it('is centred on the sheet, 36 x 4 px and rounded, in a 44 px tall drag strip', () => {
    expect(html).toMatch(
      /<div data-sheet-handle="" aria-hidden="true" class="flex h-11 [^"]*items-center justify-center[^"]*"><div class="h-1 w-9 rounded-pill [^"]*"><\/div><\/div>/,
    )
  })

  it('keeps the close button and the labelled dialog; the title row drags too', () => {
    expect(html).toContain('role="dialog" aria-modal="true"')
    expect(html).toMatch(/<button type="button" aria-label="Close" class="absolute top-0 right-2 inline-flex size-11/)
    expect(html).toMatch(/<h2 id="[^"]+" data-sheet-handle="" class="[^"]*">What if<\/h2>/)
  })
})
