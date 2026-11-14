import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Language } from '../api/types.ts'
import { strings } from '../lib/i18n.ts'
import { OpeningContext, type Opening } from '../lib/openingContext.ts'
import { SettingsContext } from '../lib/settings.ts'
import { clientTurnRequest, clientTurns } from './clientTurns.tsx'
import { ComposerBillButton } from './ComposerBillButton.tsx'
import { composerBillAction } from './composerBill.ts'

const visible = clientTurns.bill.visible

function render(lang: Language, opening: Opening | null) {
  return renderToStaticMarkup(
    <SettingsContext.Provider value={{ lang, customerId: 'CUST00860', t: strings(lang) }}>
      <OpeningContext.Provider value={opening}>
        <ComposerBillButton />
      </OpeningContext.Provider>
    </SettingsContext.Provider>,
  )
}

describe("the composer's paperclip (#705)", () => {
  afterEach(() => {
    clientTurns.bill.visible = visible
  })

  it("pushes the bill turn through the chip's path, with the chip's name, in EN and FI", () => {
    for (const [lang, name] of [
      ['en', 'Show Sentti a bill'],
      ['fi', 'Näytä Sentille lasku'],
    ] as const) {
      const opening = { pushClientTurn: vi.fn() }
      const action = composerBillAction(opening, lang)
      expect(action?.label).toBe(name)
      action?.onPress()
      action?.onPress()
      // The same request as the opening's chip each time: one bill turn, a second tap brings it back.
      expect(opening.pushClientTurn).toHaveBeenCalledTimes(2)
      expect(opening.pushClientTurn).toHaveBeenNthCalledWith(1, { question: name, render: 'bill', id: 'bill' })
      expect(opening.pushClientTurn).toHaveBeenNthCalledWith(2, clientTurnRequest('bill', lang))
    }
  })

  it('shows only where the bill chip shows, and only in the thread', () => {
    const opening = { pushClientTurn: vi.fn() }
    expect(composerBillAction(opening, 'en')).not.toBeNull()
    expect(composerBillAction(null, 'en')).toBeNull()
    clientTurns.bill.visible = () => false
    expect(composerBillAction(opening, 'en')).toBeNull()
    expect(render('en', opening as unknown as Opening)).toBe('')
  })

  it('is a 44 px button named like the chip, with no file input', () => {
    const html = render('fi', { pushClientTurn: vi.fn() } as unknown as Opening)
    expect(html).toMatch(/^<button type="button" aria-label="Näytä Sentille lasku" class="[^"]*size-\[44px\]/)
    expect(html).not.toMatch(/<input|type="file"/)
    expect(render('en', null)).toBe('')
  })
})
