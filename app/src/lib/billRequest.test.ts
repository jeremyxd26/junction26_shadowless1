import { describe, expect, it } from 'vitest'
import type { BillExplainRequest, BillReadResponse } from '../api/billTypes.ts'
import contract from '../api/mock/contract-examples.json'
import {
  buildExplainRequest,
  firstProblemField,
  initialInputs,
  normaliseAmount,
  problemOnReadField,
  type FieldInputs,
} from './billRequest.ts'

const examples = contract.examples as unknown as Record<string, unknown>
const reading = examples['bill.read_response'] as BillReadResponse
const barcodeRequest = examples['bill.request'] as BillExplainRequest
const fieldsRequest = examples['bill.request_fields'] as BillExplainRequest

const base = { customerId: 'CUST00042', language: 'en' as const }

describe('buildExplainRequest', () => {
  it('sends the confirmed barcode with the payee beside it when nothing else was edited', () => {
    const result = buildExplainRequest({ ...base, reading, inputs: initialInputs(reading) })
    expect(result).toEqual({ ok: true, request: barcodeRequest })
  })

  it('keeps the barcode when only the payee was corrected, and sends an empty payee as null', () => {
    const renamed = buildExplainRequest({ ...base, reading, inputs: { ...initialInputs(reading), payee: ' Esimerkki Koti Oy ' } })
    expect(renamed).toEqual({ ok: true, request: { ...barcodeRequest, payee: 'Esimerkki Koti Oy' } })
    const empty = buildExplainRequest({ ...base, reading, inputs: { ...initialInputs(reading), payee: '' } })
    expect(empty).toEqual({ ok: true, request: { ...barcodeRequest, payee: null } })
  })

  it('switches to the five fields when the amount was edited, with the comma made a dot', () => {
    const inputs = { ...initialInputs(reading), amount: '812,04' }
    const result = buildExplainRequest({ ...base, reading, inputs })
    expect(result).toEqual({
      ok: true,
      request: {
        customer_id: 'CUST00042',
        language: 'en',
        barcode: null,
        payee: null,
        fields: { payee: 'Esimerkki Asunnot Oy', iban: 'FI2112345600000785', reference: '1232', amount: '812.04', due_date: '2026-10-01' },
      },
    })
  })

  it('builds the contract fields request from typed fields (the typed fallback)', () => {
    const inputs: FieldInputs = { ...fieldsRequest.fields! }
    expect(initialInputs(null)).toEqual({ payee: '', iban: '', reference: '', amount: '', due_date: '' })
    expect(buildExplainRequest({ ...base, reading: null, inputs })).toEqual({ ok: true, request: fieldsRequest })
  })

  it('never sends payee beside fields, nor the read objects', () => {
    const result = buildExplainRequest({ ...base, reading, inputs: { ...initialInputs(reading), reference: '1245' } })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.request.payee).toBeNull()
    expect(result.request.barcode).toBeNull()
    expect(Object.values(result.request.fields!).every((value) => typeof value === 'string')).toBe(true)
  })

  it('reports empty and over-long fields instead of sending them', () => {
    const inputs: FieldInputs = { payee: '', iban: 'F'.repeat(43), reference: '', amount: '', due_date: '' }
    expect(buildExplainRequest({ ...base, reading: null, inputs })).toEqual({
      ok: false,
      missingCustomer: false,
      problems: { payee: 'required', iban: 'too_long', reference: 'required', amount: 'required', due_date: 'required' },
    })
  })

  it('sends nothing without a customer', () => {
    const result = buildExplainRequest({ ...base, customerId: null, reading, inputs: initialInputs(reading) })
    expect(result).toEqual({ ok: false, problems: {}, missingCustomer: true })
  })

  it('does not use a barcode longer than 80 characters', () => {
    const long = structuredClone(reading)
    long.fields.barcode!.value = '4'.repeat(81)
    const result = buildExplainRequest({ ...base, reading: long, inputs: initialInputs(long) })
    expect(result.ok && result.request.barcode).toBe(null)
  })
})

describe('normaliseAmount', () => {
  it.each([
    ['145', '145'],
    ['145,5', '145.5'],
    [' 812,40 ', '812.40'],
    ['100000', '100000'],
    ['100000.00', '100000.00'],
    ['0.01', '0.01'],
    ['099999', '99999'],
    ['000000.50', '0.50'],
    ['007', '7'],
  ])('accepts %j as %j', (typed, amount) => {
    expect(normaliseAmount(typed)).toEqual({ amount })
  })

  it.each([
    ['', 'required'],
    ['12.345', 'amount_format'],
    ['1 000', 'amount_format'],
    ['€12', 'amount_format'],
    ['-5', 'amount_format'],
    ['0,00', 'amount_range'],
    ['0', 'amount_range'],
    ['00.00', 'amount_range'],
    ['100000.01', 'amount_range'],
    ['200000', 'amount_range'],
  ])('refuses %j (%s)', (typed, problem) => {
    expect(normaliseAmount(typed)).toEqual({ problem })
  })
})

describe('a read value that fails validation', () => {
  it('reports an out-of-range read amount when there is no barcode, on the read field', () => {
    const noBarcode = structuredClone(reading)
    noBarcode.fields.barcode = null
    noBarcode.fields.amount = { ...noBarcode.fields.amount!, value: '150000.00', display: '150 000,00 €' }
    const result = buildExplainRequest({ ...base, reading: noBarcode, inputs: initialInputs(noBarcode) })
    expect(result).toEqual({ ok: false, missingCustomer: false, problems: { amount: 'amount_range' } })
    if (result.ok) return
    expect(problemOnReadField(result.problems, noBarcode)).toBe(true)
    expect(firstProblemField(result.problems)).toBe('amount')
  })

  it('reports a read payee over 70 characters on the barcode path', () => {
    const long = structuredClone(reading)
    long.fields.payee = { ...long.fields.payee!, value: 'E'.repeat(71), display: 'E'.repeat(71) }
    const result = buildExplainRequest({ ...base, reading: long, inputs: initialInputs(long) })
    expect(result).toEqual({ ok: false, missingCustomer: false, problems: { payee: 'too_long' } })
    if (result.ok) return
    expect(problemOnReadField(result.problems, long)).toBe(true)
  })

  it('does not ask for edit mode when the problem is on a field that was not read', () => {
    const missing = structuredClone(reading)
    missing.fields.barcode = null
    missing.fields.reference = null
    const result = buildExplainRequest({ ...base, reading: missing, inputs: initialInputs(missing) })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problems).toEqual({ reference: 'required' })
    expect(problemOnReadField(result.problems, missing)).toBe(false)
    expect(firstProblemField({ due_date: 'required', iban: 'too_long' })).toBe('iban')
    expect(firstProblemField({})).toBeNull()
  })
})
