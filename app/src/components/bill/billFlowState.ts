// The bill flow's steps as a pure reducer: gallery → reading → fields → explaining → explanation.
// No bill field is ever written to the URL or history: the whole state lives here, in memory.
import type { BillExplainRequest, BillExplainResponse, BillReadResponse } from '../../api/billTypes.ts'

/** A message from the API (already localised) and whether trying again may help. */
export interface FlowError {
  message: string
  retryable: boolean
}

export type FlowState =
  | { step: 'gallery'; error: FlowError | null; lastSampleId: string | null }
  | { step: 'reading'; sampleId: string }
  /** `reading: null` is the typed fallback (the reader is unavailable, 503 `model_unavailable`). */
  | { step: 'fields'; sampleId: string | null; reading: BillReadResponse | null; error: FlowError | null }
  | { step: 'explaining'; sampleId: string | null; reading: BillReadResponse | null; request: BillExplainRequest }
  | { step: 'explanation'; request: BillExplainRequest; response: BillExplainResponse }

export type FlowEvent =
  | { type: 'pick'; sampleId: string }
  | { type: 'read_ok'; sampleId: string; reading: BillReadResponse }
  | { type: 'read_unavailable'; sampleId: string }
  | { type: 'read_failed'; sampleId: string; error: FlowError }
  | { type: 'confirm'; request: BillExplainRequest }
  | { type: 'explain_ok'; response: BillExplainResponse }
  /** Any explain error: back to the fields with the message (a 422 `invalid_bill` included). */
  | { type: 'explain_failed'; error: FlowError }
  | { type: 'back' }

export const initialFlow: FlowState = { step: 'gallery', error: null, lastSampleId: null }

export function flowReducer(state: FlowState, event: FlowEvent): FlowState {
  switch (event.type) {
    case 'pick':
      return state.step === 'gallery' ? { step: 'reading', sampleId: event.sampleId } : state
    case 'read_ok':
      // A late answer for a sample the user has left is ignored.
      if (state.step !== 'reading' || state.sampleId !== event.sampleId) return state
      return { step: 'fields', sampleId: event.sampleId, reading: event.reading, error: null }
    case 'read_unavailable':
      if (state.step !== 'reading' || state.sampleId !== event.sampleId) return state
      return { step: 'fields', sampleId: event.sampleId, reading: null, error: null }
    case 'read_failed':
      if (state.step !== 'reading' || state.sampleId !== event.sampleId) return state
      return { step: 'gallery', error: event.error, lastSampleId: event.sampleId }
    case 'confirm':
      if (state.step !== 'fields') return state
      return { step: 'explaining', sampleId: state.sampleId, reading: state.reading, request: event.request }
    case 'explain_ok':
      if (state.step !== 'explaining') return state
      return { step: 'explanation', request: state.request, response: event.response }
    case 'explain_failed':
      if (state.step !== 'explaining') return state
      return { step: 'fields', sampleId: state.sampleId, reading: state.reading, error: event.error }
    case 'back':
      return initialFlow
  }
}
