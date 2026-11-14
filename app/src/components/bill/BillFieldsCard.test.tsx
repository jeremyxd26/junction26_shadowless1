import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { BillReadResponse } from '../../api/billTypes.ts'
import contract from '../../api/mock/contract-examples.json'
import { strings } from '../../lib/i18n.ts'
import { BillFieldsCard } from './BillFieldsCard.tsx'

const reading = (contract.examples as unknown as Record<string, unknown>)['bill.read_response'] as BillReadResponse
const retry = strings('en').retry

function card(error: { message: string; retryable: boolean } | null): string {
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
