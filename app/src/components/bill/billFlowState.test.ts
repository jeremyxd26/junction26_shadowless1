import { describe, expect, it } from 'vitest'
import type { BillExplainRequest, BillExplainResponse, BillReadResponse } from '../../api/billTypes.ts'
import contract from '../../api/mock/contract-examples.json'
import { ApiError } from '../../api/errors.ts'
import { flowReducer, initialFlow, toFlowError, type FlowState } from './billFlowState.ts'

const examples = contract.examples as unknown as Record<string, unknown>
const reading = examples['bill.read_response'] as BillReadResponse
const request = examples['bill.request'] as BillExplainRequest
const response = examples['bill.response'] as BillExplainResponse
const error = { message: 'Something went wrong. Try again.', retryable: true }

function run(...events: Parameters<typeof flowReducer>[1][]): FlowState {
  return events.reduce(flowReducer, initialFlow)
}

describe('bill flow steps', () => {
  it('runs gallery → reading → fields → explaining → explanation', () => {
    expect(run({ type: 'pick', sampleId: 'sample_2' })).toEqual({ step: 'reading', sampleId: 'sample_2' })
    const fields = run({ type: 'pick', sampleId: 'sample_2' }, { type: 'read_ok', sampleId: 'sample_2', reading })
    expect(fields).toEqual({ step: 'fields', sampleId: 'sample_2', reading, notice: null, error: null })
    const explaining = flowReducer(fields, { type: 'confirm', request })
    expect(explaining).toMatchObject({ step: 'explaining', request, reading })
    expect(flowReducer(explaining, { type: 'explain_ok', response })).toEqual({ step: 'explanation', request, response })
  })

  it('offers typed fields with the server message when the reader is unavailable', () => {
    const message = 'Reading the bill is not available right now.'
    const state = run({ type: 'pick', sampleId: 'sample_3' }, { type: 'read_unavailable', sampleId: 'sample_3', message })
    expect(state).toEqual({ step: 'fields', sampleId: 'sample_3', reading: null, notice: message, error: null })
  })

  it('returns to the gallery with the message when reading fails, remembering the sample for a retry', () => {
    const state = run({ type: 'pick', sampleId: 'sample_1' }, { type: 'read_failed', sampleId: 'sample_1', error })
    expect(state).toEqual({ step: 'gallery', error, lastSampleId: 'sample_1' })
  })

  it('ignores a late reading for a sample the user has left', () => {
    const left = run({ type: 'pick', sampleId: 'sample_1' }, { type: 'back' })
    expect(flowReducer(left, { type: 'read_ok', sampleId: 'sample_1', reading })).toBe(left)
    const other = run({ type: 'pick', sampleId: 'sample_1' }, { type: 'back' }, { type: 'pick', sampleId: 'sample_2' })
    expect(flowReducer(other, { type: 'read_ok', sampleId: 'sample_1', reading })).toBe(other)
  })

  it('goes back to the fields, keeping the reading, when explaining fails', () => {
    const state = run(
      { type: 'pick', sampleId: 'sample_2' },
      { type: 'read_ok', sampleId: 'sample_2', reading },
      { type: 'confirm', request },
      { type: 'explain_failed', error },
    )
    expect(state).toEqual({ step: 'fields', sampleId: 'sample_2', reading, notice: null, error })
  })

  it('sends the current fields on "Try again": a new confirm, not the failed request', () => {
    const failed = run(
      { type: 'pick', sampleId: 'sample_2' },
      { type: 'read_ok', sampleId: 'sample_2', reading },
      { type: 'confirm', request },
      { type: 'explain_failed', error },
    )
    const edited = { ...request, payee: 'Esimerkki Koti Oy' }
    expect(flowReducer(failed, { type: 'confirm', request: edited })).toMatchObject({ step: 'explaining', request: edited })
  })

  it('starts over on back', () => {
    const state = run({ type: 'pick', sampleId: 'sample_2' }, { type: 'read_ok', sampleId: 'sample_2', reading }, { type: 'back' })
    expect(state).toBe(initialFlow)
  })
})

describe('toFlowError', () => {
  const now = 5_000_000
  it('keeps the wait of a 429 as the time Try again opens', () => {
    const limited = new ApiError(429, { code: 'rate_limited', message: 'Wait a moment.', retryable: true }, 30)
    expect(toFlowError(limited, 'fallback', now)).toEqual({ message: 'Wait a moment.', retryable: true, until: now + 30_000 })
  })

  it('has no wait without Retry-After, and turns anything else into the retryable fallback', () => {
    const plain = new ApiError(500, { code: 'internal', message: 'Something went wrong.', retryable: true })
    expect(toFlowError(plain, 'fallback', now).until).toBeNull()
    expect(toFlowError(new Error('x'), 'fallback', now)).toEqual({ message: 'fallback', retryable: true, until: null })
  })
})
