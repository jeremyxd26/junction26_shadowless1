// What `HostNotice` (components/HostNotice.tsx) listens to, kept out of the component file.
import { HANDOVER_EVENT } from './hostActions.ts'

/**
 * Calls `onShow` for every hand-over that no host took (`HANDOVER_EVENT` from `handOver`).
 * Returns the unsubscribe function. `target` is `window` in the app, a stub in tests.
 */
export function onHandOverWithoutHost(onShow: () => void, target: EventTarget = window): () => void {
  target.addEventListener(HANDOVER_EVENT, onShow)
  return () => target.removeEventListener(HANDOVER_EVENT, onShow)
}
