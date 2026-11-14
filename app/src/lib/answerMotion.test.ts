import { describe, expect, it } from 'vitest'
import contract from '../api/mock/contract-examples.json'
import type { BasketKey, LabelChange, LabelResponse } from '../api/types.ts'
import { answerChanges, answerMotion } from './answerMotion.ts'

const examples = contract.examples as unknown as Record<string, LabelResponse>
const needed = examples['label.response']
const wanted = examples['label.response_wanted']

const motionOf = (response: LabelResponse) =>
  answerMotion(answerChanges(response), response.review_state === 'answered', response.label?.basket as BasketKey, false, 1)
const changeOf = (response: LabelResponse, key: string) =>
  response.changes.find((change) => change.key === key) as LabelChange
const keys = (changes: LabelChange[]) => changes.map((change) => change.key)

const spend = changeOf(needed, 'safe_to_spend')

describe('only changes[] move the opening numbers, never effect.items (#317)', () => {
  it('My choice (label.response_wanted): safe to spend stays the same, with no "was" hint for it', () => {
    const motion = motionOf(wanted)
    expect(motion.steady).toBe(true)
    expect(motion.was).not.toHaveProperty('safe_to_spend')
    expect(motion.counts).not.toHaveProperty('safe_to_spend')
    expect(keys(answerChanges(wanted))).toEqual(keys(wanted.changes))
  })

  it('effect.items naming an unchanged safe to spend do not reach the counters or the hero', () => {
    const same: LabelChange = { key: 'safe_to_spend', label: spend.label, before: spend.before, after: spend.before }
    const withEffect: LabelResponse = {
      ...wanted,
      effect: { items: [same, ...wanted.changes], text: '', text_rendered: '', numbers: {} },
    }
    const motion = motionOf(withEffect)
    expect(keys(answerChanges(withEffect))).toEqual(keys(wanted.changes))
    expect(motion.steady).toBe(true)
    expect(motion.was).not.toHaveProperty('safe_to_spend')
  })

  it(`Needed (label.response) still counts safe to spend ${spend.before.display} → ${spend.after.display}`, () => {
    const motion = motionOf(needed)
    expect(motion.steady).toBe(false)
    expect(motion.counts.safe_to_spend.from).toEqual(spend.before)
    expect(motion.was.safe_to_spend).toEqual(spend.before)
    expect(changeOf({ ...needed, changes: answerChanges(needed) }, 'safe_to_spend').after).toEqual(spend.after)
    expect(motion.highlight).toBe('unexpected_necessities')
  })

  it('an undo moves the numbers back without hints, and nothing moves when nothing changed', () => {
    const undo = examples['label.response_undo']
    const motion = answerMotion(answerChanges(undo), false, 'unexpected_necessities', false, 2)
    expect(motion.was).toEqual({})
    expect(motion.steady).toBe(false)
    expect(motion.highlight).toBeNull()
    expect(answerChanges({ ...needed, changed: false })).toEqual([])
  })
})
