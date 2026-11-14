// The one-time hint for the header icons and the paperclip: once per visit, kept in memory only (no
// storage, #457), until "Got it" or the first question.
let dismissed = false

export function firstHintDismissed(): boolean {
  return dismissed
}

/** "Got it", or the first question: the hint does not come back, not even after New chat. */
export function dismissFirstHint() {
  dismissed = true
}
