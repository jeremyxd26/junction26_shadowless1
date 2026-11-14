// A question was sent in the thread (typed, a chip or `?q=`). The opening listens, so its Undo
// toast does not linger while the customer keeps talking (#315).
const ASKED = 'sentti:asked'

export function notifyAsked() {
  window.dispatchEvent(new Event(ASKED))
}

/** Calls `onAsked` for every question sent in the thread; returns the unsubscribe. */
export function onAsked(onAsked: () => void): () => void {
  window.addEventListener(ASKED, onAsked)
  return () => window.removeEventListener(ASKED, onAsked)
}
