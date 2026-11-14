import { describe, expect, it } from 'vitest'
import { escapeCloses, trapTarget } from './focusTrap.ts'

const panel = 'panel'
const items = ['close', 'chip', 'link']

describe('trapTarget', () => {
  it('moves Tab from the last element of an open sheet to the first one', () => {
    expect(trapTarget(items, 'link', false, panel)).toBe('close')
  })

  it('moves Shift+Tab from the first element to the last one', () => {
    expect(trapTarget(items, 'close', true, panel)).toBe('link')
  })

  it('leaves a move between inner elements to the browser', () => {
    expect(trapTarget(items, 'close', false, panel)).toBeNull()
    expect(trapTarget(items, 'link', true, panel)).toBeNull()
  })

  it('takes the focus from the panel itself (or from outside) to the first or the last element', () => {
    expect(trapTarget(items, panel, false, panel)).toBe('close')
    expect(trapTarget(items, null, true, panel)).toBe('link')
  })

  it('keeps the focus on the panel when nothing in the sheet is focusable', () => {
    expect(trapTarget([], null, false, panel)).toBe(panel)
    expect(trapTarget([], panel, true, panel)).toBe(panel)
  })
})

describe('escapeCloses (#513)', () => {
  const overview = { name: 'overview' }
  const whatIf = { name: 'what-if' }
  const escape = (defaultPrevented = false) => ({ key: 'Escape', defaultPrevented })

  it('closes only the top sheet', () => {
    expect(escapeCloses(escape(), [overview, whatIf], whatIf)).toBe(true)
    expect(escapeCloses(escape(), [overview, whatIf], overview)).toBe(false)
  })

  it('ignores an Escape that another sheet handled, even if this sheet is now the top one', () => {
    // The what-if sheet closed first; the late overview listener then sees itself on top.
    expect(escapeCloses(escape(true), [overview], overview)).toBe(false)
  })

  it('ignores other keys and a sheet without a panel', () => {
    expect(escapeCloses({ key: 'Enter', defaultPrevented: false }, [overview], overview)).toBe(false)
    expect(escapeCloses(escape(), [overview], null)).toBe(false)
    expect(escapeCloses(escape(), [], overview)).toBe(false)
  })
})
