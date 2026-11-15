// The opening's three-basket bar (#945): segments as wide as the API's shares, a legend with icons, names and shares.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { BreakdownCard, OverviewResponse } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { isBasketsCard } from '../lib/changes.ts'
import { strings } from '../lib/i18n.ts'
import { SettingsContext } from '../lib/settings.ts'
import { BasketBar } from './BasketBar.tsx'

const overview = (contract.examples as unknown as Record<string, OverviewResponse>)['overview.response']
const card = overview.cards.find(isBasketsCard) as BreakdownCard

function render(lang: 'en' | 'fi', c: BreakdownCard = card) {
  return renderToStaticMarkup(createElement(SettingsContext, { value: { lang, customerId: 'CUST00860', t: strings(lang) } }, createElement(BasketBar, { card: c })))
}

describe('the three-basket bar (#945)', () => {
  it('draws one segment per basket with a share, as wide as the share, in the basket colours, and a legend', () => {
    const html = render('en')
    const withShare = card.items.filter((item) => item.share && item.share.value > 0)
    expect(html.match(/style="width:/g)).toHaveLength(withShare.length)
    for (const item of withShare) expect(html).toContain(`width:${item.share?.value}%`)
    expect(html).toContain('bg-basket-essentials')
    expect(html).toContain('bg-basket-everyday')
    for (const name of ['Regular', 'Everyday']) expect(html).toContain(name)
    const regular = card.items.find((item) => item.key === 'regular_essentials')
    expect(html).toContain(`>${regular?.share?.display}</span>`)
  })

  it('is one button of 44 px whose name summarises the split and says where it leads', () => {
    const html = render('en')
    expect(html.match(/<button/g)).toHaveLength(1)
    expect(html).toMatch(/aria-label="Where your money went: [^"]*Regular essentials [^"]*\. Where did my money go\?"/)
    expect(html).toContain('min-h-11')
    expect(html).toContain('data-opening-part="baskets"')
    expect(render('fi')).toContain('aria-label="Mihin rahasi menivät:')
  })

  it('shows nothing without shares', () => {
    expect(render('en', { ...card, items: card.items.map((item) => ({ ...item, share: null })) })).toBe('')
  })
})
