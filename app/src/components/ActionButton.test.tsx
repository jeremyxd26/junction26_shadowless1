import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Action } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { ActionButton } from './cards.tsx'

const action = contract.examples['action.open_host_screen'] as Action & { type: 'open_host_screen' }

describe('ActionButton: open_host_screen', () => {
  it("renders a 44 px button with the response's label for a known target", () => {
    const html = renderToStaticMarkup(<ActionButton action={action} />)
    expect(html).toMatch(/^<button type="button"/)
    expect(html).toContain('min-h-11')
    expect(html).toContain('>See monthly saving in S-mobiili</button>')
  })

  it('renders nothing for a target the app does not know', () => {
    expect(renderToStaticMarkup(<ActionButton action={{ ...action, target: 'savings_account' }} />)).toBe('')
  })
})
