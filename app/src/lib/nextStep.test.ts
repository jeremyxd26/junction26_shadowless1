import { describe, expect, it } from 'vitest'
import type { Action, AskDone, Card } from '../api/types.ts'
import { nextStep } from './nextStep.ts'

const evidence: Action = { type: 'open_evidence', label: 'How is this calculated?', evidence_ref: 'ev_1' }
const whatif: Action = { type: 'open_whatif', label: 'Try 20% less on restaurants', scenario: { selection: { kind: 'category', value: 'Restaurants' }, cut_pct: 20 } }
const bank: Action = { type: 'open_host_screen', label: 'Contact S-Pankki', target: 'contact_bank' }
const unknownScreen: Action = { type: 'open_host_screen', label: 'Somewhere', target: 'nowhere' }

const done = (over: Partial<AskDone> = {}): AskDone =>
  ({ answer_id: 'a', outcome: 'answered', text: '', text_rendered: '', cited: [], follow_ups: ['How could I save more?'], lesson: null, refusal: null, clarify: null, warnings: [], actions: [], ...over }) as AskDone
const card = (actions: Action[]): Card => ({ card_id: 'c', type: 'metric', title: 't', subtitle: null, evidence_ref: null, estimate: null, actions }) as unknown as Card

describe('the one next step (#684)', () => {
  it("takes the answer's own action first (the way to a human)", () => {
    expect(nextStep(done({ actions: [bank] }), [card([whatif])])).toEqual({ kind: 'action', action: bank })
  })

  it('then a card action that leads somewhere, before a follow-up and before "how is this calculated"', () => {
    expect(nextStep(done(), [card([evidence, whatif])])).toEqual({ kind: 'action', action: whatif })
  })

  it('then the first follow-up, before the evidence action', () => {
    expect(nextStep(done(), [card([evidence])])).toEqual({ kind: 'question', question: 'How could I save more?' })
  })

  it('then the evidence action, and nothing when the response carries nothing', () => {
    expect(nextStep(done({ follow_ups: [] }), [card([evidence])])).toEqual({ kind: 'action', action: evidence })
    expect(nextStep(done({ follow_ups: [] }), [card([])])).toBeNull()
    expect(nextStep(null, [card([whatif])])).toBeNull()
  })

  it('skips a host screen the app does not know, and a refusal takes no card action', () => {
    expect(nextStep(done({ follow_ups: [] }), [card([unknownScreen])])).toBeNull()
    expect(nextStep(done({ outcome: 'refused', follow_ups: [] }), [card([whatif])])).toBeNull()
  })

  it('a clarification offers only its own action: its options are the answer', () => {
    expect(nextStep(done({ outcome: 'clarify' }), [card([whatif])])).toBeNull()
  })
})

describe("Maxim's decision on the way to a human (#696)", () => {
  it('a refusal keeps only the way to a human, even with follow-ups', () => {
    expect(nextStep(done({ outcome: 'refused', actions: [bank] }), [card([whatif])])).toEqual({ kind: 'action', action: bank })
  })

  it('a fallback offers its first follow-up, and the way to a human only without one', () => {
    expect(nextStep(done({ outcome: 'fallback', actions: [bank] }), [])).toEqual({ kind: 'question', question: 'How could I save more?' })
    expect(nextStep(done({ outcome: 'fallback', actions: [bank], follow_ups: ['  '] }), [])).toEqual({ kind: 'action', action: bank })
  })

  it('so does the "not yet" answer (a clarification with the way to a human); the general clarification still offers nothing', () => {
    expect(nextStep(done({ outcome: 'clarify', actions: [bank] }), [])).toEqual({ kind: 'question', question: 'How could I save more?' })
    expect(nextStep(done({ outcome: 'clarify', actions: [bank], follow_ups: [] }), [])).toEqual({ kind: 'action', action: bank })
    expect(nextStep(done({ outcome: 'clarify' }), [])).toBeNull()
  })
})

describe('the next step after the review of #710', () => {
  // The "not yet" answer as the core sends it (orchestrator `_clarify`, rules NOT_YET_OPTIONS):
  // `clarify` with options, `follow_ups: []`, and the way to a human in `actions`.
  const notYet = (over: Partial<AskDone> = {}) =>
    done({
      outcome: 'clarify',
      follow_ups: [],
      clarify: { question: "I can't answer that one yet. Try one of these:", options: ['How much did I spend last month?', 'How much did I spend on restaurants last month?'] },
      actions: [bank],
      ...over,
    })

  it('a "not yet" answer with options: the options are its follow-ups, so no "Contact S-Pankki" on the latest answer', () => {
    expect(nextStep(notYet(), [])).toBeNull()
  })

  it('a "not yet" answer without options offers the way to a human', () => {
    expect(nextStep(notYet({ clarify: { question: 'Not yet.', options: [] } }), [])).toEqual({ kind: 'action', action: bank })
  })

  it('on an older turn the questions are hidden, so a fallback or a "not yet" answer keeps the way to a human', () => {
    expect(nextStep(done({ outcome: 'fallback', actions: [bank] }), [], false)).toEqual({ kind: 'action', action: bank })
    expect(nextStep(notYet(), [], false)).toEqual({ kind: 'action', action: bank })
  })

  it('an older answered turn still shows no follow-up (as before)', () => {
    expect(nextStep(done(), [card([evidence])], false)).toBeNull()
  })

  it('a refusal without the way to a human offers nothing, not a follow-up', () => {
    expect(nextStep(done({ outcome: 'refused' }), [card([whatif])])).toBeNull()
  })
})

