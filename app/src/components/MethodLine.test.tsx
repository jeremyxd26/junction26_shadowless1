import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { EvidenceResponse } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { MethodLine } from './EvidenceSheet.tsx'

const examples = contract.examples as unknown as Record<string, unknown>
const evidences = Object.entries(examples)
  .filter(([name]) => name.startsWith('evidence.response'))
  .map(([, value]) => value as EvidenceResponse)

describe('the evidence sheet method line (#557)', () => {
  it('shows the method name and never the internal method id', () => {
    expect(evidences.length).toBeGreaterThan(0)
    for (const evidence of evidences) {
      const html = renderToStaticMarkup(<MethodLine method={evidence.method} />)
      expect(html).not.toContain('@1')
      expect(html).not.toContain(evidence.method.id)
      if (evidence.method.name) expect(html).toContain(evidence.method.name)
    }
  })

  it('shows nothing without a name', () => {
    expect(renderToStaticMarkup(<MethodLine method={{ name: '' }} />)).toBe('')
    expect(renderToStaticMarkup(<MethodLine method={{ name: '  ' }} />)).toBe('')
  })
})
