import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client.ts'
import { ApiError } from '../api/errors.ts'
import type { BasketKey, LabelChange, LabelResponse, Num, OverviewResponse, ReviewCard } from '../api/types.ts'
import { HeroSummary, TokenText, type NumberMotion } from '../components/cards.tsx'
import { SenttiLabel } from '../components/AnswerView.tsx'
import { ReviewAnswered, ReviewAsking, type ReviewError } from '../components/ReviewCard.tsx'
import { Toast } from '../components/Toast.tsx'
import { answerChanges, answerMotion } from '../lib/answerMotion.ts'
import { BASKETS } from '../lib/baskets.ts'
import { applyChanges, isBasketsCard } from '../lib/changes.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { onAsked } from '../lib/threadEvents.ts'
import { prefersReducedMotion, tokenMs } from '../lib/motion.ts'
import { useOpening, type ShownReview } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { BasketBar } from '../components/BasketBar.tsx'
import { OpeningChips } from '../components/OpeningChips.tsx'

/** Where the review card is: asked, answered, closed by "Not sure", or gone for good. */
type Phase =
  | { kind: 'asking' }
  // `label`: the basket's name as the label response gave it, for answers that point here (#452).
  | { kind: 'answered'; basket: BasketKey; label: string }
  | { kind: 'not_sure' }
  | { kind: 'gone' }

/**
 * The numbers of the latest label response, shown over the overview until the overview
 * refetched after it arrives. `refreshedFrom` is the overview on screen when that refetch was asked.
 */
interface Overlay {
  seq: number
  changes: LabelChange[]
  refreshedFrom: OverviewResponse | null
}

interface ToastState {
  seq: number
  text: string
  rendered: string
  numbers: Record<string, Num>
  undo: boolean
  retry: boolean
  retryUntil: number | null
  /**
   * The answer came with `effect`: while Sentti's reply is on screen it shows that confirmation, so
   * there is no visual toast. The live region still reads the message.
   */
  silent: boolean
  /** "Not sure" closed the card: Undo brings the question back (client only, nothing was sent). */
  restore?: boolean
}

type Motion = NumberMotion & { seq: number }

/** How long "was …" hints and the row tint stay after an answer (DESIGN.md). */
const HINT_MS = 6000
/** How long a toast with no action (the undo confirmation) stays; screen readers got it at once. */
const NOTE_MS = 4000
/** How long the answer's toast stays; its Undo is also on the answered card. */
const TOAST_MS = 6000
/** How long the "Not sure" toast with its Undo stays. */
const RESTORE_MS = 5000

/**
 * Sentti's opening turn in the thread on `/` (OpeningTurn): this week's picture, the review
 * question, then questions to ask, which are sent in the same thread. OpeningTurn keeps one
 * mounted instance per persona, because the review state, its timers and the overlay live here.
 */
export function Overview({ overview, onRefresh }: { overview: OverviewResponse; onRefresh: () => void }) {
  const { t, lang, customerId } = useSettings()
  // The question asked when the screen opened. It stays here after the answer (the refetched
  // overview no longer lists it) and comes back if the answer is undone while the review is open.
  const [card] = useState<ReviewCard | null>(() => overview.reviews[0] ?? null)
  const [phase, setPhase] = useState<Phase>({ kind: 'asking' })
  // Tell the thread which review card the opening shows (#450): answers point to it only then.
  // Once answered, the basket goes with it, so those answers say where the purchase went (#452).
  const reportReview = useOpening()?.reportReview
  useEffect(() => {
    if (!reportReview) return
    const shown: ShownReview | null = !card
      ? null
      : phase.kind === 'asking'
        ? { txRef: card.tx_ref, phase: 'asking' }
        : phase.kind === 'answered'
          ? { txRef: card.tx_ref, phase: 'answered', basketKey: phase.basket, basketLabel: phase.label }
          : null
    reportReview(shown)
    return () => reportReview(null)
  }, [reportReview, card, phase])
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState<BasketKey | 'undo' | null>(null)
  const [error, setError] = useState<ReviewError | null>(null)
  const [overlay, setOverlay] = useState<Overlay | null>(null)
  const [motion, setMotion] = useState<Motion | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  // `shownToast`: the run whose toast may show (an answer's, a "Not sure" or an error's).
  const [shownToast, setShowToast] = useState<number | null>(null)
  // Sentti's short reply under the question (#317): mounted at the tap, before the API answers. Its text only:
  // no basket strip and no flying amount (Renat, #958).
  const [reply, setReply] = useState<BasketKey | null>(null)
  // The answer's own confirmation (`effect`, contract 0.3.2), shown in the reply when the core sends it.
  const [replyNote, setReplyNote] = useState<{ text: string; numbers: Record<string, Num> } | null>(null)

  const seq = useRef(0)
  const timers = useRef<number[]>([])
  const lastRequest = useRef<BasketKey | null>(null)
  const focusCard = useRef(false)
  const cardRef = useRef<HTMLElement>(null)
  const overviewRef = useRef(overview)
  useEffect(() => {
    overviewRef.current = overview
  }, [overview])

  const later = useCallback((ms: number, run: () => void) => {
    timers.current.push(window.setTimeout(run, ms))
  }, [])
  useEffect(
    () => () => {
      for (const id of timers.current) window.clearTimeout(id)
    },
    [],
  )

  /** Refetch the overview in the background; the overlay gives way once the new data is here. */
  const refreshAfter = useCallback(
    (run: number) => {
      setOverlay((current) =>
        current && current.seq === run ? { ...current, refreshedFrom: overviewRef.current } : current,
      )
      onRefresh()
    },
    [onRefresh],
  )

  const labels = useMemo(() => {
    const names: Record<string, string> = {}
    if (card) names.unclassified = card.current_basket.label
    return names
  }, [card])
  const overlayLive = overlay && !(overlay.refreshedFrom && overlay.refreshedFrom !== overview)
  const view = useMemo(
    () => (overlay && overlayLive ? applyChanges(overview, overlay.changes, labels) : overview),
    [overview, overlay, overlayLive, labels],
  )

  // A question sent in the thread closes the toast: it must not linger while the customer talks.
  useEffect(() => onAsked(() => setToast(null)), [])

  useEffect(() => {
    if (!focusCard.current) return
    focusCard.current = false
    cardRef.current?.focus({ preventScroll: true })
  }, [phase])

  /**
   * The answer's toast goes by itself after a while, so it does not cover Sentti's reply: Undo stays
   * on the answered card (#315). A toast with an error and Retry stays until it is closed.
   */
  const hideToastLater = useCallback(
    (run: number) => later(TOAST_MS, () => setToast((current) => (current && current.seq === run ? null : current))),
    [later],
  )

  function apply(response: LabelResponse, asked: BasketKey | null) {
    for (const id of timers.current) window.clearTimeout(id)
    timers.current = []
    const run = ++seq.current
    const reduced = prefersReducedMotion()
    // The hero, counters and overlay follow `changes[]` only; `effect` is the reply's text.
    const changes = answerChanges(response)
    if (changes.length > 0) setOverlay({ seq: run, changes, refreshedFrom: null })

    const answered = response.review_state === 'answered' && asked !== null
    const basket = (response.label?.basket ?? asked) as BasketKey
    // Three calm signals only (Renat, #958): the question folds to its answered line, the hero counts with its
    // "was" line, and the basket bar eases to the new split. Nothing flies.
    setMotion(answerMotion(changes, answered, basket, false, run))

    // When Sentti's reply shows the answer's own confirmation (`effect`, contract 0.3.2), there is
    // no visual toast over it: Undo stays on the answered card, and the live region reads the whole
    // message (`text_rendered`) once. Without `effect`, or without the reply (no baskets card), the
    // toast works as before.
    setToast({
      seq: run,
      text: response.message.text,
      rendered: response.message.text_rendered,
      numbers: response.message.numbers,
      undo: answered,
      retry: false,
      retryUntil: null,
      silent: answered && Boolean(response.effect),
    })
    focusCard.current = true
    if (answered) {
      // The basket's name from the API: the label response, else the overview's baskets card.
      const label =
        response.label?.label ??
        overviewRef.current.cards.find(isBasketsCard)?.items.find((item) => item.key === basket)?.label ??
        ''
      setPhase({ kind: 'answered', basket, label })
      setReply(basket)
      setReplyNote(response.effect ? { text: response.effect.text, numbers: response.effect.numbers } : null)
      later(HINT_MS, () =>
        setMotion((current) =>
          current && current.seq === run ? { ...current, was: {}, steady: false, highlight: null } : current,
        ),
      )
    } else {
      setPhase(response.review_state === 'pending' ? { kind: 'asking' } : { kind: 'gone' })
      setReply(null)
      setReplyNote(null)
      // The undo confirmation has no action, so it may go: it would cover the answer buttons.
      later(NOTE_MS, () => setToast((current) => (current && current.seq === run ? null : current)))
    }

    setShowToast(run)
    if (answered) hideToastLater(run)
    later(reduced ? 0 : tokenMs('--duration-money', 900) + 100, () => refreshAfter(run))
  }

  async function send(basket: BasketKey | null) {
    if (!card || !customerId || busy) return
    lastRequest.current = basket
    setBusy(basket ?? 'undo')
    setError(null)
    if (basket !== null) setReply(basket)
    try {
      const response = await api.label({ customer_id: customerId, tx_ref: card.tx_ref, basket, language: lang })
      apply(response, basket)
    } catch (caught) {
      // Nothing was saved, so the reply mounted at the tap goes (an undo keeps the answered reply).
      if (basket !== null) setReply(null)
      if (caught instanceof ApiError && caught.code === 'tx_ref_not_found') {
        // The review expired: remove the card quietly and show the overview as it is now.
        setPhase({ kind: 'gone' })
        setToast(null)
        onRefresh()
        return
      }
      // Nothing moved: the card (or the toast, for an undo) says so and offers a retry when it may help.
      const message = caught instanceof ApiError ? caught.message : t.reviewSaveFailed
      const retryable = caught instanceof ApiError ? caught.retryable : true
      // A 429 (or 503) may say how long to wait: Retry stays off until then.
      const wait = caught instanceof ApiError ? caught.retryAfter : null
      const until = wait ? Date.now() + wait * 1000 : null
      if (basket === null) {
        const run = ++seq.current
        setToast({ seq: run, text: message, rendered: message, numbers: {}, undo: false, retry: retryable, retryUntil: until, silent: false })
        setShowToast(run)
      } else {
        setError({ message, retryable, until })
      }
    } finally {
      setBusy(null)
    }
  }

  function notSure() {
    setClosing(true)
    later(prefersReducedMotion() ? 0 : tokenMs('--duration-base', 250), () => {
      setClosing(false)
      setPhase({ kind: 'not_sure' })
      // A way back (Renat's review): an Undo toast for 5 s, and "Change answer" on the line left behind.
      const run = ++seq.current
      setToast({ seq: run, text: t.reviewHidden, rendered: t.reviewHidden, numbers: {}, undo: false, retry: false, retryUntil: null, silent: false, restore: true })
      setShowToast(run)
      later(RESTORE_MS, () => setToast((current) => (current && current.seq === run ? null : current)))
      document.querySelector<HTMLElement>('[data-review-change]')?.focus({ preventScroll: true })
    })
  }

  /** Brings the question back after "Not sure" (the toast's Undo or "Change answer"). */
  function restoreQuestion() {
    setToast(null)
    setPhase({ kind: 'asking' })
  }

  const visibleToast = toast && shownToast === toast.seq ? toast : null
  const baskets = view.cards.find(isBasketsCard)
  const replyLabel = reply ? baskets?.items.find((item) => item.key === reply)?.label : undefined
  // The reply's own condition below: a silent toast stays silent only while the reply shows.
  const replyShown = Boolean(reply && baskets)

  return (
    <div className="flex flex-col gap-3">
      {/* One thought per screen (#310): the greeting in one line; the AI disclosure is behind the
          header's ⓘ. Baskets, bills, safe to save, insights and what-if are in answers and the
          overview sheet, not here. */}
      <p className="pt-1 text-center text-base text-ink-2">{view.greeting}</p>
      {view.hero && <HeroSummary card={view.hero} motion={motion ?? undefined} />}
      {/* The three baskets at a glance (Renat, #945): one slim bar under the key line, a tap asks where the money went. */}
      {baskets && <BasketBar card={baskets} />}

      {card && phase.kind === 'asking' && (
        <ReviewAsking
          ref={cardRef}
          card={card}
          busy={busy === 'undo' ? null : busy}
          error={error}
          leaving={closing}
          onAnswer={(basket) => void send(basket)}
          onNotSure={notSure}
          onRetry={() => void send(lastRequest.current)}
          bubble
        />
      )}
      {card && phase.kind === 'not_sure' && (
        <div className="flex flex-wrap items-center justify-between gap-x-3 rounded-lg border border-line bg-surface px-3 py-1">
          <span className="text-sm text-ink-2">{t.reviewSkipped}</span>
          <button
            type="button"
            data-review-change=""
            onClick={restoreQuestion}
            className="min-h-11 px-1 text-sm font-semibold text-brand underline underline-offset-4"
          >
            {t.reviewChange}
          </button>
        </div>
      )}
      {card && phase.kind === 'answered' && (
        <ReviewAnswered
          ref={cardRef}
          card={card}
          basket={phase.basket}
          onUndo={busy === null ? () => void send(null) : undefined}
          bubble
        />
      )}

      {reply && baskets && (
        // Sentti's short reply: the answer's own words, nothing else (Renat, #958).
        <div data-opening-part="reply" className="card-enter flex flex-col gap-2">
          <SenttiLabel s={chatStrings(lang)} />
          <div className="rounded-lg border border-line bg-surface p-3">
            {/* With `effect`, its text says it all; the client title is for older cores. */}
            {replyNote ? (
              <p className="text-base leading-7 text-ink">
                <TokenText text={replyNote.text} numbers={replyNote.numbers} />
              </p>
            ) : (
              <p className="text-base font-bold text-ink">
                {t.movedTo} <span aria-hidden="true">{BASKETS[reply]?.icon}</span> {replyLabel}
              </p>
            )}
          </div>
        </div>
      )}

      <OpeningChips />

      {/* Screen readers hear the label response's message with its numbers written out. */}
      <p role="status" className="sr-only">
        {visibleToast?.rendered ?? ''}
      </p>
      {visibleToast && !(visibleToast.silent && replyShown) && (
        <Toast
          text={visibleToast.text}
          numbers={visibleToast.numbers}
          onUndo={visibleToast.restore ? restoreQuestion : visibleToast.undo && busy === null ? () => void send(null) : undefined}
          onRetry={visibleToast.retry ? () => void send(null) : undefined}
          retryUntil={visibleToast.retryUntil}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  )
}
