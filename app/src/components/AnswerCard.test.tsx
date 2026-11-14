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

  it('profile: the name, the description, the traits and every feature number as its display', () => {
    const html = render(profile)
    expect(html).toContain(profile.profile.label)
    expect(html).toContain(profile.profile.description)
    for (const trait of profile.traits) expect(html).toContain(trait.label)
    for (const feature of profile.features) expect(html).toContain(feature.value.display)
  })

  it('peer: you against the median, with the gap, the percentile and the group size', () => {
    const html = render(peer)
    for (const number of [peer.you, peer.peer_median, peer.vs_median, peer.percentile, peer.peer_group.size]) {
      expect(html).toContain(number.display)
    }
    expect(html).toContain(peer.peer_group.label)
    expect(html).toContain(escape(peer.note))
  })

  it('peer without a comparable group: only the note, no numbers', () => {
    const html = render({ ...peer, peer_group: { ...peer.peer_group, comparable: false } } as PeerData)
    expect(html).toContain(escape(peer.note))
    expect(html).not.toContain(peer.you.display)
    expect(html).not.toContain(peer.peer_median.display)
  })

  it('bills: the bills card with its bills and total', () => {
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

  it('peer: the gap has its visible label, and the large chip has a medium twin for narrow screens', () => {
    const html = render(peer)
    expect(html).toContain(`>${peer.vs_median.label}</span>`)
    expect(html).toContain('hidden min-[360px]:inline-flex')
    expect(html).toContain('inline-flex min-[360px]:hidden')
  })

  it('a number without an evidence ref is a plain chip, not a button', () => {
    const html = render({ ...peer, vs_median: { ...peer.vs_median, evidence_ref: null } } as PeerData)
    expect(html).toContain(`<span class="inline-flex min-w-11`)
    expect(html).toMatch(new RegExp(`<span class="inline-flex min-w-11[^"]*">${peer.vs_median.display}</span>`))
    expect(html).not.toMatch(new RegExp(`<button[^>]*>${peer.vs_median.display}</button>`))
    // With a ref it opens the evidence: a button with the label in its accessible name.
    expect(render(peer)).toMatch(new RegExp(`<button[^>]*aria-label="${peer.vs_median.label}: ${peer.vs_median.display}`))
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
