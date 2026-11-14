import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import contract from '../api/mock/contract-examples.json'
import { strings } from '../lib/i18n.ts'
import { SettingsContext } from '../lib/settings.ts'
import { AboutButton, AboutSheet } from './Header.tsx'

const examples = contract.examples as unknown as Record<string, { ai_disclosure: string }>
const DISCLOSURE = examples['overview.response'].ai_disclosure

describe('the AI disclosure behind the header badge (#685)', () => {
  it('the badge stays visible, with an ⓘ, in one real button with an accessible name', () => {
    const html = renderToStaticMarkup(<AboutButton onOpen={() => {}} />)
    expect(html).toMatch(/^<button type="button" aria-haspopup="dialog" aria-label="Sentti, AI\. About Sentti" class="[^"]*min-h-11/)
    expect(html).toContain('>AI</span>')
    expect(html).toContain('data-icon="info"')
    // The ⓘ is drawn, not read: the button's name already says what it opens.
    expect(html).toMatch(/<svg data-icon="info" aria-hidden="true"/)
  })

  it('the accessible name follows the language', () => {
    const fi = { lang: 'fi' as const, customerId: null, t: strings('fi') }
    const html = renderToStaticMarkup(
      <SettingsContext.Provider value={fi}>
        <AboutButton onOpen={() => {}} />
      </SettingsContext.Provider>,
    )
    expect(html).toContain('aria-label="Sentti, tekoäly. Tietoa Senttistä"')
  })

  it("the sheet it opens is a labelled dialog with the ready response's ai_disclosure", () => {
    expect(DISCLOSURE).toBeTruthy()
    const html = renderToStaticMarkup(<AboutSheet disclosure={DISCLOSURE} onClose={() => {}} />)
    expect(html).toContain('role="dialog"')
    expect(html).toContain('aria-modal="true"')
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(html)?.[1]
    expect(labelledBy).toBeTruthy()
    expect(html).toContain(`id="${labelledBy}"`)
    expect(html).toContain('>About Sentti<')
    expect(html).toContain(`>${DISCLOSURE}</p>`)
  })

  it("without an overview the sheet shows the app's own fallback text", () => {
    const fallback = strings('en').disclosure
    expect(renderToStaticMarkup(<AboutSheet disclosure={fallback} onClose={() => {}} />)).toContain(`>${fallback}</p>`)
  })
})
