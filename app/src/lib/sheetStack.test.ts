import { afterEach, describe, expect, it, vi } from 'vitest'
import { topSheet } from './sheetStack.ts'

// Sheets as their place in the document: overview 1, what-if 2, evidence 3 (App's mount order).
const after = (a: number, b: number) => a > b

describe('topSheet (#516)', () => {
  it('is the sheet that comes last in the document, whatever order they opened in', () => {
    // A deep-linked overview mounts last, once its data is there; it is still under the others.
    expect(topSheet([2, 3, 1], after)).toBe(3)
    expect(topSheet([2, 1], after)).toBe(2)
    expect(topSheet([3, 2], after)).toBe(3)
  })

  it('is the only sheet when one is open, and none when none is', () => {
    expect(topSheet([1], after)).toBe(1)
    expect(topSheet([], after)).toBeNull()
  })
})

/**
 * A minimal element tree for `openSheet` in Node (no DOM in these tests): parent/children, attributes,
 * document order, focus and `contains`. Without `inert` on the prototype the stack uses its
 * `aria-hidden` fallback, which is what these tests read.
 */
class FakeElement {
  parentElement: FakeElement | null = null
  children: FakeElement[] = []
  style: Record<string, string> = { overflow: '' }
  private attrs = new Map<string, string>()
  constructor(readonly name: string) {}
  append(...nodes: FakeElement[]) {
    for (const node of nodes) {
      node.parentElement = this
      this.children.push(node)
    }
    return this
  }
  hasAttribute(name: string) {
    return this.attrs.has(name)
  }
  getAttribute(name: string) {
    return this.attrs.get(name) ?? null
  }
  setAttribute(name: string, value: string) {
    this.attrs.set(name, value)
  }
  removeAttribute(name: string) {
    this.attrs.delete(name)
  }
  contains(other: unknown): boolean {
    for (let node = other as FakeElement | null; node; node = node.parentElement) if (node === this) return true
    return false
  }
  closest(selector: string): FakeElement | null {
    if (this.hasAttribute(selector.replace(/^\[|\]$/g, ''))) return this
    return this.parentElement ? this.parentElement.closest(selector) : null
  }
  get isConnected() {
    return documentStub.body.contains(this)
  }
  focus() {
    documentStub.activeElement = this
  }
  compareDocumentPosition(other: FakeElement) {
    const order: FakeElement[] = []
    const walk = (node: FakeElement) => {
      order.push(node)
      node.children.forEach(walk)
    }
    walk(documentStub.body)
    return order.indexOf(other) > order.indexOf(this) ? 4 : 2 // FOLLOWING : PRECEDING
  }
}

const documentStub = { body: new FakeElement('body'), activeElement: null as FakeElement | null }

/** body > [app, overview sheet, what-if sheet]; each sheet has a panel and a button inside it. */
function page() {
  documentStub.body = new FakeElement('body')
  const app = new FakeElement('app')
  const sheet = (name: string) => {
    const panel = new FakeElement(`${name} panel`)
    return { root: new FakeElement(`${name} root`).append(panel), panel }
  }
  const overview = sheet('overview')
  const whatIf = sheet('what-if')
  const opener = new FakeElement('opener')
  app.append(opener)
  documentStub.body.append(app, overview.root, whatIf.root)
  documentStub.activeElement = documentStub.body
  return { app, overview, whatIf, opener }
}

describe('openSheet with two sheets in the stack (#516)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  async function load() {
    vi.stubGlobal('HTMLElement', FakeElement)
    vi.stubGlobal('Node', { DOCUMENT_POSITION_FOLLOWING: 4 })
    vi.stubGlobal('document', documentStub)
    return import('./sheetStack.ts')
  }
  const hidden = (el: FakeElement) => el.getAttribute('aria-hidden') === 'true'

  it('a sheet that mounts later but sits under the top one never hides the top one or takes its focus', async () => {
    const { openSheet } = await load()
    const { app, overview, whatIf } = page()
    // Deep link ?overview=1&whatif=…: what-if mounts first, the overview mounts later (its data loads).
    const closeWhatIf = openSheet(whatIf.root as unknown as HTMLElement, whatIf.panel as unknown as HTMLElement)
    expect(documentStub.activeElement).toBe(whatIf.panel)
    const closeOverview = openSheet(overview.root as unknown as HTMLElement, overview.panel as unknown as HTMLElement)
    expect(hidden(whatIf.root)).toBe(false)
    expect(hidden(overview.root)).toBe(true)
    expect(hidden(app)).toBe(true)
    expect(documentStub.activeElement).toBe(whatIf.panel)
    expect(documentStub.body.style.overflow).toBe('hidden')

    // Closing the top sheet makes the one under it live and gives it the focus.
    closeWhatIf()
    expect(hidden(overview.root)).toBe(false)
    expect(hidden(app)).toBe(true)
    expect(documentStub.activeElement).toBe(overview.panel)

    closeOverview()
    expect(hidden(app)).toBe(false)
    expect(documentStub.body.style.overflow).toBe('')
  })

  it('a sheet opened on top takes the focus, and closing it gives the focus back to its opener', async () => {
    const { openSheet } = await load()
    const { app, overview, whatIf, opener } = page()
    opener.focus()
    const closeOverview = openSheet(overview.root as unknown as HTMLElement, overview.panel as unknown as HTMLElement)
    expect(documentStub.activeElement).toBe(overview.panel)
    const button = new FakeElement('what-if chip')
    overview.panel.append(button)
    button.focus()
    const closeWhatIf = openSheet(whatIf.root as unknown as HTMLElement, whatIf.panel as unknown as HTMLElement)
    expect(documentStub.activeElement).toBe(whatIf.panel)
    expect(hidden(overview.root)).toBe(true)

    closeWhatIf()
    expect(documentStub.activeElement).toBe(button)
    closeOverview()
    expect(documentStub.activeElement).toBe(opener)
    expect(hidden(app)).toBe(false)
  })
})
