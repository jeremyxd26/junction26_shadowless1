import { describe, expect, it } from 'vitest'
import { BillApiError } from '../bill.ts'
import type { BillErrorEnvelope, BillExplainRequest, BillExplainResponse, BillReadResponse } from '../billTypes.ts'
import { createMockBillApi } from './bill.ts'
import { TIGHT_FORECAST } from './billForecast.ts'
import { createMockClient } from './mockClient.ts'
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
    expect(await api.explain(examples['bill.request_fields'] as BillExplainRequest)).toEqual(examples['bill.response_unknown'])
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
    const example = examples['bill.read_response'] as BillReadResponse
    const fi = await api.read({ customer_id: 'CUST00042', language: 'fi', sample_id: 'sample_2' })
    expect(fi).toEqual(example)
    const en = await api.read({ customer_id: 'CUST00042', language: 'en', sample_id: 'sample_2' })
    expect(en).toEqual({
      ...example,
      language: 'en',
      fields: {
        ...example.fields,
        amount: { ...example.fields.amount!, display: '€812.40' },
        due_date: { ...example.fields.due_date!, display: '1 Oct 2026' },
      },
    })
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

  it('opens the evidence of the bill numbers for any persona', async () => {
    const response = examples['bill.response'] as BillExplainResponse
    const client = createMockClient()
    for (const customer of ['CUST00860', 'CUST00042']) {
      const after = await client.evidence(response.safe_to_spend!.after!.evidence_ref!, customer, 'en')
      expect(after.number).toEqual(response.safe_to_spend!.after)
      const change = await client.evidence(response.comparison!.change.evidence_ref!, customer, 'en')
      expect(change.number).toEqual(response.comparison!.change)
    }
  })

  it('gives every forecast status: three from the contract examples, tight from the fixture', async () => {
    const notCovered = examples['bill.response_not_covered'] as BillExplainResponse
    expect((await api.explain(examples['bill.request'] as BillExplainRequest)).forecast?.status).toBe('covered')
    const request = examples['bill.request_fields'] as BillExplainRequest
    expect((await api.explain(request)).forecast?.status).toBe('outside_forecast')
    // The contract's own typed bill, and the typed-fallback sample's payee, get the contract's not_covered.
    const typed = {
      ...request,
      fields: { payee: notCovered.bill.payee!, iban: notCovered.bill.iban, reference: notCovered.bill.reference, amount: '700.00', due_date: notCovered.bill.due_date },
    }
    expect(await api.explain(typed)).toEqual(notCovered)
    const water = await api.explain({ ...request, fields: { ...request.fields!, payee: 'Esimerkki Vesi Oy' } })
    expect(water.forecast).toEqual(notCovered.forecast)
    const energy = await api.explain({ ...request, fields: { ...request.fields!, payee: 'Esimerkki Energia Oy' } })
    expect(energy.forecast).toEqual(TIGHT_FORECAST)
  })

  it('keeps the provisional tight forecast within the contract rules', () => {
    const { before, counted, after, shortfall, chip } = TIGHT_FORECAST
    expect(Math.round((before!.value - counted!.value) * 100) / 100).toBe(after!.value)
    // A bill outside the forecast's bills takes its whole amount: the bill's amount Number (11.2).
    expect(counted!.method).toBe('user_input@1')
    expect(counted!.evidence_ref).toBeNull()
    expect(shortfall).toBeNull()
    expect(chip).toBeNull()
  })
})
