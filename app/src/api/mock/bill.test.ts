import { describe, expect, it } from 'vitest'
import { BillApiError } from '../bill.ts'
import type { BillErrorEnvelope, BillExplainRequest, BillExplainResponse, BillReadResponse } from '../billTypes.ts'
import { createMockBillApi } from './bill.ts'
import contract from './contract-examples.json'

const examples = contract.examples as unknown as Record<string, unknown>
const api = createMockBillApi()

async function rejection(promise: Promise<unknown>): Promise<BillApiError> {
  try {
    await promise
  } catch (error) {
    if (error instanceof BillApiError) return error
    throw error
  }
  throw new Error('expected a BillApiError')
}

describe('bill mock', () => {
  it('answers the contract requests with the contract responses', async () => {
    expect(await api.explain(examples['bill.request'] as BillExplainRequest)).toEqual(examples['bill.response'])
    expect(await api.explain(examples['bill.request_fields'] as BillExplainRequest)).toEqual(
      examples['bill.response_unknown'] as BillExplainResponse,
    )
  })

  it('answers another 54-digit barcode with the contract error, reason included', async () => {
    const barcode = (examples['bill.request'] as BillExplainRequest).barcode!.replace(/1$/, '2')
    const error = await rejection(
      api.explain({ customer_id: 'CUST00042', language: 'en', barcode, payee: null, fields: null }),
    )
    const envelope = (examples['bill.error'] as BillErrorEnvelope).error
    expect(error.status).toBe(422)
    expect(error.code).toBe(envelope.code)
    expect(error.message).toBe(envelope.message)
    expect(error.reason).toBe(envelope.reason)
  })

  it('refuses a barcode beside fields, and a short barcode', async () => {
    const fields = (examples['bill.request_fields'] as BillExplainRequest).fields
    const both = await rejection(api.explain({ customer_id: 'CUST00042', language: 'fi', barcode: '1', payee: null, fields }))
    expect(both.reason).toBe('one_of_barcode_or_fields')
    const short = await rejection(
      api.explain({ customer_id: 'CUST00042', language: 'en', barcode: '4211 2345', payee: null, fields: null }),
    )
    expect(short.reason).toBe('barcode_length')
  })

  it('reads the housing sample as the contract reading in the language of the request, and the third sample as unavailable', async () => {
    for (const language of ['fi', 'en'] as const) {
      const reading = await api.read({ customer_id: 'CUST00042', language, sample_id: 'sample_2' })
      expect(reading).toEqual({ ...(examples['bill.read_response'] as BillReadResponse), language })
    }
    const unavailable = await rejection(api.read({ customer_id: 'CUST00042', language: 'en', sample_id: 'sample_3' }))
    expect(unavailable.status).toBe(503)
    expect(unavailable.code).toBe('model_unavailable')
  })

  it('lists fictional samples with inline images only', async () => {
    const { samples } = await api.samples('en')
    expect(samples.length).toBeGreaterThanOrEqual(3)
    for (const sample of samples) {
      expect(sample.image_url.startsWith('data:image/svg+xml')).toBe(true)
      expect(sample.title).toMatch(/Esimerkki/)
    }
  })
})
