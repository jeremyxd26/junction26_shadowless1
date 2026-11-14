// The bill flow's steps as a pure reducer: gallery → reading → fields → explaining → explanation.
// No bill field is ever written to the URL or history: the whole state lives here, in memory.
import type { BillExplainRequest, BillExplainResponse, BillReadResponse } from '../../api/billTypes.ts'
import { ApiError } from '../../api/errors.ts'

/** A message from the API (already localised) and whether trying again may help. */
export interface FlowError {
  message: string
  retryable: boolean
  /** The time (`Date.now()`) the server's `Retry-After` allows the next try (a 429); null or absent when it gave none. */
  until?: number | null
}

/** An API error as the flow keeps it; anything else becomes `fallback`, retryable. */
export function toFlowError(error: unknown, fallback: string, now: number = Date.now()): FlowError {
  if (error instanceof ApiError) {
    // A 429 `rate_limited` carries `Retry-After`: Try again stays off until then.
    const until = error.retryAfter ? now + error.retryAfter * 1000 : null
    return { message: error.message, retryable: error.retryable, until }
  }
  return { message: fallback, retryable: true, until: null }
}

export type FlowState =
  | { step: 'gallery'; error: FlowError | null; lastSampleId: string | null }
  | { step: 'reading'; sampleId: string }
  /**
   * `reading: null` is the typed fallback; `notice` is then the server's 503 `model_unavailable`
   * message, shown above the empty fields.
   */
  | {
      step: 'fields'
      sampleId: string | null
      reading: BillReadResponse | null
      notice: string | null
      /** The last explain error; the fields card shows it, and "Try again" re-sends the current fields. */
      error: FlowError | null
    }
  | {
      step: 'explaining'
      sampleId: string | null
      reading: BillReadResponse | null
      notice: string | null
      request: BillExplainRequest
    }
  | { step: 'explanation'; request: BillExplainRequest; response: BillExplainResponse }

export type FlowEvent =
  | { type: 'pick'; sampleId: string }
  | { type: 'read_ok'; sampleId: string; reading: BillReadResponse }
  | { type: 'read_unavailable'; sampleId: string; message: string }
  | { type: 'read_failed'; sampleId: string; error: FlowError }
  | { type: 'confirm'; request: BillExplainRequest }
  | { type: 'explain_ok'; response: BillExplainResponse }
  /** Any explain error: back to the fields with the message (a 422 `invalid_bill` included). */
  | { type: 'explain_failed'; error: FlowError }
  | { type: 'back' }

export const initialFlow: FlowState = { step: 'gallery', error: null, lastSampleId: null }

/** The step titles the flow reports, in the UI language (`billStrings`). */
export interface StepTitles {
  galleryTitle: string
  reading: string
  confirmTitle: string
  typeTitle: string
  explaining: string
}

/**
 * What a client turn hears about the step (#332): its title, announced once and the text of the
 * focused heading, and whether it waits for the API (the turn's `aria-busy`).
 */
export function flowStep(state: FlowState, s: StepTitles): { title: string; waiting: boolean } {
  switch (state.step) {
    case 'gallery':
      return { title: s.galleryTitle, waiting: false }
    case 'reading':
      return { title: s.reading, waiting: true }
    case 'fields':
      return { title: state.reading ? s.confirmTitle : s.typeTitle, waiting: false }
    case 'explaining':
      return { title: s.explaining, waiting: true }
    case 'explanation':
      return { title: state.response.match.text, waiting: false }
  }
}

export function flowReducer(state: FlowState, event: FlowEvent): FlowState {
  switch (event.type) {
    case 'pick':
      return state.step === 'gallery' ? { step: 'reading', sampleId: event.sampleId } : state
    case 'read_ok':
      // A late answer for a sample the user has left is ignored.
      if (state.step !== 'reading' || state.sampleId !== event.sampleId) return state
      return { step: 'fields', sampleId: event.sampleId, reading: event.reading, notice: null, error: null }
    case 'read_unavailable':
      if (state.step !== 'reading' || state.sampleId !== event.sampleId) return state
      return { step: 'fields', sampleId: event.sampleId, reading: null, notice: event.message, error: null }
    case 'read_failed':
      if (state.step !== 'reading' || state.sampleId !== event.sampleId) return state
      return { step: 'gallery', error: event.error, lastSampleId: event.sampleId }
    case 'confirm':
      if (state.step !== 'fields') return state
      return { step: 'explaining', sampleId: state.sampleId, reading: state.reading, notice: state.notice, request: event.request }
    case 'explain_ok':
      if (state.step !== 'explaining') return state
      return { step: 'explanation', request: state.request, response: event.response }
    case 'explain_failed':
      if (state.step !== 'explaining') return state
      return {
        step: 'fields',
        sampleId: state.sampleId,
        reading: state.reading,
        notice: state.notice,
        error: event.error,
      }
    case 'back':
      return initialFlow
  }
}
