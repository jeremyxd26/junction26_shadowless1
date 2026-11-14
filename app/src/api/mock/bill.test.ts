import { describe, expect, it } from 'vitest'
import { BillApiError } from '../bill.ts'
import type { BillErrorEnvelope, BillExplainRequest, BillExplainResponse, BillReadResponse } from '../billTypes.ts'
import { createMockBillApi } from './bill.ts'
import { FORECASTS } from './billForecast.ts'
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
    // Until `mocks:sync` brings contract 0.3.4, the examples have no `forecast`: the mock adds the
    // provisional one (see billForecast.ts). After the sync the examples' own forecast is used.
    const matched = examples['bill.response'] as BillExplainResponse
    const unknown = examples['bill.response_unknown'] as BillExplainResponse
    expect(await api.explain(examples['bill.request'] as BillExplainRequest)).toEqual({
      ...matched,
      forecast: matched.forecast ?? FORECASTS.covered,
    })
    expect(await api.explain(examples['bill.request_fields'] as BillExplainRequest)).toEqual({
      ...unknown,
      forecast: unknown.forecast ?? FORECASTS.outside_forecast,
    })
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

  it('reads the housing sample as the unchanged contract reading in both languages, and the third sample as unavailable', async () => {
    for (const language of ['fi', 'en'] as const) {
      const reading = await api.read({ customer_id: 'CUST00042', language, sample_id: 'sample_2' })
      expect(reading).toEqual(examples['bill.read_response'] as BillReadResponse)
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

  it('attaches a forecast for every status: the contract cases and the provisional ones', async () => {
    const barcode = await api.explain(examples['bill.request'] as BillExplainRequest)
    expect(barcode.forecast?.status).toBe('covered')
    const request = examples['bill.request_fields'] as BillExplainRequest
    const typed = await api.explain(request)
    expect(typed.forecast).toEqual(FORECASTS.outside_forecast)
    const water = await api.explain({ ...request, fields: { ...request.fields!, payee: 'Esimerkki Vesi Oy' } })
    expect(water.forecast?.status).toBe('not_covered')
    expect(water.forecast?.chip).toEqual({ type: 'ask', label: 'See your balance forecast', prompt: 'Will my money last until payday?' })
    const energy = await api.explain({ ...request, fields: { ...request.fields!, payee: 'Esimerkki Energia Oy' } })
    expect(energy.forecast?.status).toBe('tight')
    expect(energy.forecast?.chip).toBeNull()
  })

  it('keeps the provisional forecasts within the contract rules', () => {
    for (const forecast of Object.values(FORECASTS)) {
      if (forecast.status === 'outside_forecast') {
        expect([forecast.before, forecast.counted, forecast.after, forecast.shortfall]).toEqual([null, null, null, null])
        continue
      }
      const { before, counted, after } = forecast
      expect(Math.round((before!.value - counted!.value) * 100) / 100).toBe(after!.value)
      expect(forecast.chip !== null).toBe(forecast.status === 'not_covered')
      expect(forecast.shortfall !== null).toBe(forecast.status === 'not_covered')
    }
  })
})
