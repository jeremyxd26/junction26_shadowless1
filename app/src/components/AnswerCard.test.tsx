import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Card } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { AnswerCard } from './AnswerCard.tsx'
import type { PeerData } from './PeerCard.tsx'
import type { ProfileData } from './ProfileCard.tsx'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const examples = contract.examples as unknown as Record<string, unknown>
const profile = examples['card.profile'] as ProfileData
const peer = examples['card.peer'] as PeerData
const bills = (examples['overview.response'] as { cards: Card[] }).cards.find((card) => card.type === 'bills')!
const render = (card: Card) => renderToStaticMarkup(<AnswerCard card={card} />)
/** Text as it appears in the markup (an apostrophe is escaped). */
const escape = (text: string) => text.replaceAll("'", '&#x27;')

describe('AnswerCard: profile, peer and bills', () => {
  // The tests run in Node: the chips read duration tokens, the URL and the reduced-motion setting.
  beforeAll(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
    vi.stubGlobal('window', {
      location: new URL('http://localhost/'),
      matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
      addEventListener() {},
      removeEventListener() {},
    })
  })
  afterAll(() => vi.unstubAllGlobals())

  it('profile (#684): the name in normal weight, the traits, the deciding feature large and three rows; no title, no description', () => {
    const html = render(profile)
    expect(html).toContain(`<p class="mt-2 text-lg leading-7 text-ink">${profile.profile.label}</p>`)
    // The title restates the question and the description is the answer's sentence.
    expect(html).not.toContain(escape(profile.title))
    expect(html).not.toContain(profile.profile.description)
    for (const trait of profile.traits) expect(html).toContain(trait.label)
    const [deciding, ...rest] = [...profile.features].sort((a, b) => Number(b.decides_label) - Number(a.decides_label))
    expect(html.slice(html.indexOf('data-answer-main'))).toContain(deciding.value.display)
    for (const feature of rest.slice(0, 3)) expect(html).toContain(feature.value.display)
    expect(html.split('data-figure-row').length - 1).toBe(Math.min(3, rest.length))
    // The period once, as a caption.
    expect(html).toContain(`data-answer-caption="" class="min-w-0 flex-1 text-xs text-muted">${deciding.value.period.label}</p>`)
  })

  it('peer (#684): you as the main number, then the median, the gap and the percentile', () => {
    const html = render(peer)
    for (const number of [peer.you, peer.peer_median, peer.vs_median, peer.percentile]) {
      expect(html).toContain(number.display)
    }
    expect(html.split('data-figure-row').length - 1).toBe(3)
    // Its title names what is compared, so it stays, in the normal weight (not CARD_TITLE).
    expect(html).toContain(`<p class="mt-2 text-lg leading-7 text-ink">${escape(peer.title)}</p>`)
  })

  it('peer without a comparable group: only the note, no numbers', () => {
    const html = render({ ...peer, peer_group: { ...peer.peer_group, comparable: false } } as PeerData)
    expect(html).toContain(escape(peer.note))
    expect(html).not.toContain(peer.you.display)
    expect(html).not.toContain(peer.peer_median.display)
  })

  it('bills: its bills and total', () => {
    const html = render(bills)
    const items = (bills as unknown as { items: { label: string; typical_month: { display: string } }[] }).items
    expect(items.length).toBeGreaterThan(0)
    for (const item of items) expect(html).toContain(escape(item.label))
    expect(html).toContain((bills as unknown as { total: { display: string } }).total.display)
  })

  it('an unknown type still gets the generic frame with its title', () => {
    const html = render({ ...profile, type: 'stores', title: 'Where you shop' } as unknown as Card)
    expect(html).toContain('Where you shop')
    expect(html).not.toContain(profile.profile.description)
  })

  it('peer: the gap has its visible label', () => {
    expect(render(peer)).toContain(`>${peer.vs_median.label}</span>`)
  })

  it('a number without an evidence ref is plain text, not a button; with one it opens its evidence (#684: no pill)', () => {
    const html = render({ ...peer, vs_median: { ...peer.vs_median, evidence_ref: null } } as PeerData)
    // A plain span with the 44 px ::after target, and no button named after the number.
    expect(html).toMatch(/<span class="inline-flex items-center[^"]*after:-inset-y-2\.5[^"]*">/)
    expect(html).not.toContain(`aria-label="${peer.vs_median.label}: `)
    // With a ref it opens the evidence: a button with the label in its accessible name.
    expect(render(peer)).toMatch(new RegExp(`<button[^>]*aria-label="${peer.vs_median.label}: ${peer.vs_median.display}`))
    expect(render(peer)).not.toContain('rounded-pill border font-semibold')
  })

  it('what-if (#684): the monthly saving large, then the week, the year and the baseline', () => {
    const whatif = examples['card.whatif'] as Card & {
      result: Record<'saving_per_month' | 'saving_per_week' | 'saving_per_year' | 'baseline_per_month', { display: string }>
    }
    const html = render(whatif)
    expect(html.slice(html.indexOf('data-answer-main'))).toContain(whatif.result.saving_per_month.display)
    for (const key of ['saving_per_week', 'saving_per_year', 'baseline_per_month'] as const) expect(html).toContain(whatif.result[key].display)
    expect(html.split('data-figure-row').length - 1).toBe(3)
    expect(html).not.toContain(whatif.title)
  })

  it('what-if not offered: no "€0.00" headline, the frame with its title as before', () => {
    const whatif = examples['card.whatif'] as Card & { result: Record<string, unknown> & { saving_per_month: { display: string } } }
    const html = render({ ...whatif, result: { ...whatif.result, status: 'not_offered' } } as unknown as Card)
    expect(html).toContain(whatif.title)
    expect(html).not.toContain('data-answer-main')
  })

  it('safe to save at 0 (#684 review): the reason amount is the first row, still three rows', () => {
    for (const name of ['card.safe_to_save_zero', 'card.safe_to_save_everyday']) {
      const save = examples[name] as Card & {
        reason: { category: { label: string } | null; amount: { label: string; display: string } }
      }
      expect(save.reason).toBeTruthy()
      const html = render(save)
      const rows = html.split('data-figure-row').slice(1)
      expect(rows).toHaveLength(3)
      expect(rows[0]).toContain(`>${save.reason.category?.label ?? save.reason.amount.label}</span>`)
      expect(rows[0]).toContain(`aria-label="${save.reason.amount.label}: ${save.reason.amount.display}`)
    }
  })

  it('safe to spend (#684): four secondary numbers are cut to three rows', () => {
    const hero = (examples['overview.response'] as { hero: Card & { secondary: { display: string }[] } }).hero
    expect(hero.secondary.length).toBeGreaterThan(3)
    expect(render(hero).split('data-figure-row').length - 1).toBe(3)
  })

  it('a fact card has no source label (#685)', () => {
    const html = render({ ...profile, estimate: null } as ProfileData)
    expect(html).not.toContain('From your transactions')
    expect(render({ ...profile, type: 'stores', estimate: null } as unknown as Card)).not.toContain('From your transactions')
  })

  it('baskets breakdown (#696): the total large, the baskets as rows, no green pills', () => {
    const baskets = (examples['overview.response'] as { cards: Card[] }).cards.find(
      (card) => card.type === 'breakdown' && (card as unknown as { items: { key: string }[] }).items.some((item) => item.key === 'regular_essentials'),
    ) as Card & { total: { display: string }; items: { label: string }[] }
    const html = render(baskets)
    expect(html).toContain('data-answer-main')
    expect(html).toContain(baskets.total.display)
    const rows = html.split('data-figure-row').slice(1)
    expect(rows.length).toBe(Math.min(3, baskets.items.length))
    // The baskets come first, so the cap keeps them rather than a comparison row.
    baskets.items.slice(0, rows.length).forEach((item, index) => expect(rows[index]).toContain(escape(item.label)))
    expect(html).not.toContain('bg-mint')
    expect(html).not.toContain(`<h3`)
  })

  it('bills (#696): the total due before payday large, at most three bills as rows', () => {
    const html = render(bills)
    expect(html).toContain('data-answer-main')
    const rows = html.split('data-figure-row').slice(1)
    const items = (bills as unknown as { items: unknown[] }).items
    expect(rows.length).toBe(Math.min(3, items.length))
    expect(html).not.toContain('bg-mint')
  })

  it('what-if with a caveat (#696): its caveats under the numbers, as the sheet shows them; a plain estimate shows none', () => {
    const whatif = examples['card.whatif'] as Card & { result: Record<string, unknown> }
    const caveat = 'Your restaurant spending changes a lot from month to month.'
    const withCaveat = render({ ...whatif, result: { ...whatif.result, status: 'estimate_with_caveat', caveats: [caveat] } } as unknown as Card)
    expect(withCaveat).toContain('data-answer-caveats')
    expect(withCaveat).toContain(escape(caveat))
    expect(withCaveat).toContain('data-answer-main')
    const notOffered = render({ ...whatif, result: { ...whatif.result, status: 'not_offered', caveats: [caveat] } } as unknown as Card)
    expect(notOffered).toContain(escape(caveat))
    expect(notOffered).not.toContain('data-answer-main')
    const plain = render({ ...whatif, result: { ...whatif.result, status: 'estimate', caveats: [caveat] } } as unknown as Card)
    expect(plain).not.toContain('data-answer-caveats')
  })

  it('review in an answer (#696): the white frame of the answer card, the amount as the one main number, answer buttons kept', () => {
    const review = examples['card.review'] as Card & { amount: { display: string }; options: { label: { en: string } }[] }
    const html = render(review)
    expect(html).toContain('data-answer-main')
    expect(html).not.toContain('bg-deep')
    expect(html).toContain(review.amount.display)
    for (const option of review.options) expect(html).toContain(escape(option.label.en))
  })

  it('bills and safe to save in an answer draw no action of their own (the chat shows them as chips)', () => {
    const billsAction = (bills.actions[0] as { label: string }).label
    expect(render(bills)).not.toContain(billsAction)
    const safeToSave = examples['card.safe_to_save'] as Card
    expect(safeToSave.actions.length).toBeGreaterThan(0)
    const html = render(safeToSave)
    for (const action of safeToSave.actions) expect(html).not.toContain(`>${action.label}<`)
  })
})
