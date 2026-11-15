import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { BillReadResponse } from '../../api/billTypes.ts'
import contract from '../../api/mock/contract-examples.json'
import { strings } from '../../lib/i18n.ts'
import { BillFieldsCard } from './BillFieldsCard.tsx'

const reading = (contract.examples as unknown as Record<string, unknown>)['bill.read_response'] as BillReadResponse
const retry = strings('en').retry

function card(error: { message: string; retryable: boolean; until?: number | null } | null): string {
  return renderToStaticMarkup(<BillFieldsCard reading={reading} busy={false} error={error} onConfirm={() => {}} />)
}

describe('BillFieldsCard errors', () => {
  it('shows a 422 invalid_bill message without Try again (not retryable)', () => {
    const message = 'This barcode does not pass its check. Compare it with the paper bill, or type the fields.'
    const html = card({ message, retryable: false })
    expect(html).toContain(message)
    expect(html).not.toContain(`>${retry}</button>`)
  })

  it('offers Try again for a retryable error, and shows no error block without one', () => {
    expect(card({ message: 'No connection. Try again.', retryable: true })).toContain(`>${retry}</button>`)
    expect(card(null)).not.toContain('role="alert"')
  })
})

describe('BillFieldsCard: a 429 with Retry-After', () => {
  it('holds Try again back with the wait, disabled, until the time has passed', () => {
    const html = card({ message: 'Too many tries.', retryable: true, until: Date.now() + 30_000 })
    const button = /<button[^>]*>Try again in (\d+) s<\/button>/.exec(html)
    expect(button).not.toBeNull()
    expect(Number(button![1])).toBeGreaterThanOrEqual(29)
    expect(button![0]).toContain('disabled=""')
    // Only the message is the alert: the ticking countdown is outside it, so it is not announced every second.
    const alert = /<p role="alert"[^>]*>([\s\S]*?)<\/p>/.exec(html)
    expect(alert?.[1]).toBe('Too many tries.')
    expect(html.match(/role="alert"/g)).toHaveLength(1)
    // A wait that is over leaves the plain, enabled Try again.
    expect(card({ message: 'Too many tries.', retryable: true, until: Date.now() - 1000 })).toContain(`>${retry}</button>`)
  })
})

describe('BillFieldsCard: checked marks and notes (contract 0.3.7)', () => {
  const checkedWord = 'Checked'
  it('marks only the fields that came back checked: IBAN and reference in the contract reading', () => {
    const html = card(null)
    const marks = html.split(checkedWord).length - 1
    // The explanation line "Checked means …" names the word once; every mark adds one.
    expect(marks).toBe(1 + 2)
  })

  it('shows a field note under the field as the API sent it', () => {
    const note = 'This reference number does not pass its check. Compare it with the paper bill.'
    const withNote: BillReadResponse = structuredClone(reading)
    withNote.fields.reference = { ...withNote.fields.reference!, status: 'unchecked', note }
    const html = renderToStaticMarkup(<BillFieldsCard reading={withNote} busy={false} error={null} onConfirm={() => {}} />)
    expect(html).toContain(note)
    expect(html.split(checkedWord).length - 1).toBe(1 + 1)
  })
})

describe('BillFieldsCard: a failed check digit stays the most visible thing (the review)', () => {
  it('shows the warning first, repeats it over the button, and the button says Explain anyway', () => {
    const withFail: BillReadResponse = structuredClone(reading)
    withFail.fields.reference = { ...withFail.fields.reference!, status: 'unchecked', note: 'This reference number does not pass its check.' }
    const html = renderToStaticMarkup(<BillFieldsCard reading={withFail} busy={false} error={null} onConfirm={() => {}} />)
    expect(html).toContain('role="alert"')
    expect(html).toContain('The reference number does not pass its check digit.')
    expect(html.split('Check the reference number before paying.').length - 1).toBe(2)
    expect(html).toContain('>Explain anyway</button>')
    expect(html).not.toContain('Looks right, explain it')
  })

  it('without a failed check: no warning, "Looks right, explain it"', () => {
    const html = card(null)
    expect(html).not.toContain('before paying')
    expect(html).toContain('>Looks right, explain it</button>')
  })
})
