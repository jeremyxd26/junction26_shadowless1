// The stack of open bottom sheets (#440, #516). Sheets open by a tap or straight from the URL
// (`?overview=1&whatif=…&evidence=…`), and then mount in any order: a deep-linked overview mounts
// last, once its data is there. So no sheet decides on mount whether it is on top. Every open and
// close recomputes the top sheet, the one whose root comes last in the document (App mounts the
// overview, then what-if, then evidence, so that is the URL's stacking order). Only that sheet
// keeps the page behind inert and holds the focus; the page stays unscrollable while any is open.

/** The sheet that comes last of all, by `after(a, b)`: a is after b in the document. */
export function topSheet<T>(sheets: readonly T[], after: (a: T, b: T) => boolean): T | null {
  let top: T | null = null
  for (const sheet of sheets) if (top === null || after(sheet, top)) top = sheet
  return top
}

interface OpenSheet {
  root: HTMLElement
  panel: HTMLElement
  /** What had the focus when the sheet opened; it gets it back when the sheet closes from the top. */
  previous: HTMLElement | null
}

const SUPPORTS_INERT = typeof HTMLElement !== 'undefined' && 'inert' in HTMLElement.prototype
const open: OpenSheet[] = []
let top: OpenSheet | null = null
let showBackground: () => void = () => {}
let bodyOverflow: string | null = null

/**
 * Makes everything beside the sheet unreachable: `inert` on the siblings of the sheet and of each
 * of its ancestors up to `body` (the app, the toast, the sheets below it, anything portalled to
 * `body`), or `aria-hidden` where `inert` is not supported. Returns the undo. A node marked
 * `data-sheet-keep` stays live: the host notice, which shows above every sheet and whose
 * `role="status"` must still be announced and tappable.
 */
function hideBackground(sheet: HTMLElement): () => void {
  const changed: HTMLElement[] = []
  for (let keep: HTMLElement = sheet; keep.parentElement && keep !== document.body; keep = keep.parentElement) {
    for (const node of Array.from(keep.parentElement.children)) {
      if (node === keep || !(node instanceof HTMLElement) || node.hasAttribute('data-sheet-keep')) continue
      if (SUPPORTS_INERT ? node.inert : node.getAttribute('aria-hidden') === 'true') continue
      if (SUPPORTS_INERT) node.inert = true
      else node.setAttribute('aria-hidden', 'true')
      changed.push(node)
    }
  }
  return () => {
    for (const node of changed) {
      if (SUPPORTS_INERT) node.inert = false
      else node.removeAttribute('aria-hidden')
    }
  }
}

const after = (a: OpenSheet, b: OpenSheet) => Boolean(b.root.compareDocumentPosition(a.root) & Node.DOCUMENT_POSITION_FOLLOWING)

/** Re-applies the background and the focus for the current top sheet. */
function restack() {
  showBackground()
  showBackground = () => {}
  const next = topSheet(open, after)
  if (next) showBackground = hideBackground(next.root)
  // A new top sheet takes the focus, unless it is in there already; a sheet that mounts under the
  // top one (a deep-linked overview) leaves the focus where it is.
  if (next && next !== top && !next.panel.contains(document.activeElement)) next.panel.focus()
  top = next
  if (open.length > 0 && bodyOverflow === null) {
    bodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } else if (open.length === 0 && bodyOverflow !== null) {
    document.body.style.overflow = bodyOverflow
    bodyOverflow = null
  }
}

/** Registers an open sheet; returns its close, which also gives the focus back. */
export function openSheet(root: HTMLElement, panel: HTMLElement): () => void {
  const sheet: OpenSheet = { root, panel, previous: document.activeElement as HTMLElement | null }
  open.push(sheet)
  restack()
  return () => {
    const wasTop = top === sheet
    const index = open.indexOf(sheet)
    if (index >= 0) open.splice(index, 1)
    // The background becomes reachable again before the focus goes back to it.
    restack()
    if (!wasTop) return
    const back = sheet.previous
    if (back && back.isConnected && !back.closest('[inert]') && (top === null || top.panel.contains(back))) back.focus()
    else top?.panel.focus()
  }
}
