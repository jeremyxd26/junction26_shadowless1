// Keeping the keyboard inside an open bottom sheet (#440). The decision is a pure function, so it is
// tested without a DOM; BottomSheet supplies the focusable elements and the active one.

/** What can take the focus inside a sheet, in DOM order. Hidden and disabled elements are filtered by the caller. */
export const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Where Tab (or Shift+Tab with `shift`) must move the focus so it stays inside the sheet, or null
 * when the browser's own move already stays inside. With nothing focusable, the panel itself keeps
 * the focus.
 */
export function trapTarget<T>(items: readonly T[], active: T | null, shift: boolean, panel: T): T | null {
  if (items.length === 0) return panel
  const index = active === null ? -1 : items.indexOf(active)
  const first = items[0]
  const last = items[items.length - 1]
  if (shift) return index <= 0 ? last : null
  return index === -1 || index === items.length - 1 ? first : null
}

/**
 * Whether this sheet closes on a keydown: Escape, not handled yet by another sheet, and this sheet
 * is the top dialog (#513). Every open sheet listens on `window`; the first one to close marks the
 * event handled, so one Escape closes exactly one sheet even when the dialogs change under it
 * (a deep-linked overview mounts late, so its listener runs after the top sheet already closed).
 */
export function escapeCloses<T>(event: { key: string; defaultPrevented: boolean }, dialogs: ArrayLike<T>, panel: T | null): boolean {
  if (event.key !== 'Escape' || event.defaultPrevented || panel === null) return false
  return dialogs.length > 0 && dialogs[dialogs.length - 1] === panel
}
