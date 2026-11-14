import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api/client.ts'
import { ApiError } from '../api/errors.ts'
import type { BasketKey, LabelChange, LabelResponse, Num, OverviewResponse, ReviewCard } from '../api/types.ts'
import { BasketStrip } from '../components/BasketStrip.tsx'
import { HeroSummary, TokenText, type NumberMotion } from '../components/cards.tsx'
import { SenttiLabel } from '../components/AnswerView.tsx'
import { ReviewAnswered, ReviewAsking, type ReviewError } from '../components/ReviewCard.tsx'
import { Toast } from '../components/Toast.tsx'
import { BASKETS } from '../lib/baskets.ts'
import { applyChanges, isBasketsCard } from '../lib/changes.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { onAsked } from '../lib/threadEvents.ts'
import { prefersReducedMotion, token, tokenMs } from '../lib/motion.ts'
import { askInThread } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

/** Where the review card is: asked, answered, closed by "Not sure", or gone for good. */
type Phase = { kind: 'asking' } | { kind: 'answered'; basket: BasketKey } | { kind: 'not_sure' } | { kind: 'gone' }

/**
 * The numbers of the latest label response, shown over the overview until the overview
 * refetched after it arrives. `refreshedFrom` is the overview on screen when that refetch was asked.
 */
interface Overlay {
  seq: number
  changes: LabelChange[]
  refreshedFrom: OverviewResponse | null
}

interface Flight {
  seq: number
  basket: BasketKey
  display: string
}

interface ToastState {
  seq: number
  text: string
  rendered: string
  numbers: Record<string, Num>
  undo: boolean
  retry: boolean
  retryUntil: number | null
}

type Motion = NumberMotion & { seq: number }

/** How long "was …" hints and the row tint stay after an answer (DESIGN.md). */
const HINT_MS = 6000
/** How long a toast with no action (the undo confirmation) stays; screen readers got it at once. */
const NOTE_MS = 4000
/** How long the answer's toast stays; its Undo is also on the answered card. */
const TOAST_MS = 6000
/** Keys whose "was …" hint is shown: the hero, its reserve and the basket the purchase moved to. */
const HINTED = new Set(['safe_to_spend', 'irregular_reserve', 'regular_essentials', 'unexpected_necessities', 'everyday_spending'])

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
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState<BasketKey | 'undo' | null>(null)
  const [error, setError] = useState<ReviewError | null>(null)
  const [overlay, setOverlay] = useState<Overlay | null>(null)
  const [motion, setMotion] = useState<Motion | null>(null)
  const [flight, setFlight] = useState<Flight | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  // The toast of an answer waits for the amount to land; `shownToast` is the run it belongs to.
  const [shownToast, setShowToast] = useState<number | null>(null)
  // Sentti's short reply under the question (#317): mounted at the tap, before the API answers, so
  // the mini basket row the amount flies into is on screen when the answer arrives.
  const [reply, setReply] = useState<BasketKey | null>(null)
  // The answer's own confirmation (`effect`, contract 0.3.2), shown in the reply when the core sends it.
  const [replyNote, setReplyNote] = useState<{ text: string; numbers: Record<string, Num> } | null>(null)
  const replyRef = useRef<HTMLDivElement>(null)

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

  /** The flight's milestones: counters of the basket rows start, the amount lands, the pill is gone. */
  const onFlight = useCallback(
    (run: number, event: 'start' | 'land' | 'done') => {
      if (event === 'start') {
        setMotion((current) =>
          current && current.seq === run
            ? {
                ...current,
                counts: Object.fromEntries(
                  Object.entries(current.counts).map(([key, count]) => [key, { ...count, run: true }]),
                ),
              }
            : current,
        )
      } else if (event === 'land') {
        // The waiting row folds away, then the toast comes up (so it never covers the fold).
        later(250, () =>
          setMotion((current) => (current && current.seq === run ? { ...current, waiting: 'leave' } : current)),
        )
        later(250 + 450, () => {
          setMotion((current) => (current && current.seq === run ? { ...current, waiting: null } : current))
          setShowToast(run)
          hideToastLater(run)
          refreshAfter(run)
        })
      } else {
        setFlight((current) => (current && current.seq === run ? null : current))
      }
    },
    [later, refreshAfter, hideToastLater],
  )

  function apply(response: LabelResponse, asked: BasketKey | null) {
    for (const id of timers.current) window.clearTimeout(id)
    timers.current = []
    const run = ++seq.current
    const reduced = prefersReducedMotion()
    // `effect.items` (contract 0.3.2) has the shape of `changes[]`; where it names a number, it wins.
    const effectItems = response.effect?.items ?? []
    const merged = [
      ...response.changes.filter((change) => !effectItems.some((item) => item.key === change.key)),
      ...effectItems,
    ]
    const changes = response.changed ? merged : []
    if (changes.length > 0) setOverlay({ seq: run, changes, refreshedFrom: null })

    const answered = response.review_state === 'answered' && asked !== null
    const basket = (response.label?.basket ?? asked) as BasketKey
    // Only Sentti's reply holds the flight's cells; a basket card in a later answer never does.
    const hasWaitingRow = replyRef.current?.querySelector('[data-amount-key="unclassified"]') != null
    const flies =
      answered &&
      !reduced &&
      hasWaitingRow &&
      changes.some((change) => change.key === 'unclassified') &&
      changes.some((change) => change.key === basket)

    const counts = Object.fromEntries(
      changes.map((change) => [
        change.key,
        // Basket rows start counting when the amount leaves the waiting row.
        { seq: run, from: change.before, run: !flies || !(change.key in BASKETS) },
      ]),
    )
    const was = answered
      ? Object.fromEntries(changes.filter((change) => HINTED.has(change.key)).map((change) => [change.key, change.before]))
      : {}
    setMotion({
      seq: run,
      counts,
      was,
      steady: answered && changes.length > 0 && !changes.some((change) => change.key === 'safe_to_spend'),
      highlight: answered ? basket : null,
      waiting: flies ? 'keep' : null,
    })

    setToast({
      seq: run,
      text: response.message.text,
      rendered: response.message.text_rendered,
      numbers: response.message.numbers,
      undo: answered,
      retry: false,
      retryUntil: null,
    })
    focusCard.current = true
    if (answered) {
      setPhase({ kind: 'answered', basket })
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

    if (flies) {
      setShowToast(null)
      setFlight({ seq: run, basket, display: card?.amount.display ?? '' })
    } else {
      setShowToast(run)
      if (answered) hideToastLater(run)
      later(reduced ? 0 : tokenMs('--duration-money', 900) + 100, () => refreshAfter(run))
    }
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
        setToast({ seq: run, text: message, rendered: message, numbers: {}, undo: false, retry: retryable, retryUntil: until })
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
      // The card is gone: the next thing on the screen is the first question chip.
      document.querySelector<HTMLElement>('[data-turn="opening"] ul[aria-label] button')?.focus({ preventScroll: true })
    })
  }

  const visibleToast = toast && shownToast === toast.seq ? toast : null
  const baskets = view.cards.find(isBasketsCard)
  const replyLabel = reply ? baskets?.items.find((item) => item.key === reply)?.label : undefined

  return (
    <div className="flex flex-col gap-3">
      {/* One thought per screen (#310): the greeting in one line; the AI disclosure is behind the
          header's ⓘ. Baskets, bills, safe to save, insights and what-if are in answers and the
          overview sheet, not here. */}
      <p className="text-xl font-semibold leading-7 text-ink">{view.greeting}</p>
      {view.hero && <HeroSummary card={view.hero} motion={motion ?? undefined} />}

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
        />
      )}
      {card && phase.kind === 'answered' && (
        <ReviewAnswered
          ref={cardRef}
          card={card}
          basket={phase.basket}
          onUndo={busy === null ? () => void send(null) : undefined}
        />
      )}

      {reply && baskets && (
        // Sentti's short reply: where the purchase went, and the mini row the amount flies into.
        <div ref={replyRef} data-opening-part="reply" className="card-enter flex flex-col gap-2">
          <SenttiLabel s={chatStrings(lang)} />
          <div className="rounded-lg border border-line bg-surface p-4">
            <p className="mb-2 text-base font-bold text-ink">
              {t.movedTo} <span aria-hidden="true">{BASKETS[reply]?.icon}</span> {replyLabel}
            </p>
            {replyNote && (
              <p className="mb-2 text-sm leading-8 text-ink-2">
                <TokenText text={replyNote.text} numbers={replyNote.numbers} />
              </p>
            )}
            <BasketStrip card={baskets} motion={motion ?? undefined} keys={['unclassified', reply]} title={null} flight />
          </div>
        </div>
      )}

      {view.suggested_questions.length > 0 && (
        // The first three questions as sent, stacked; each is asked in this thread.
        <ul aria-label={t.questionsLabel} className="flex flex-col items-start gap-2">
          {view.suggested_questions.slice(0, 3).map((question) => (
            <li key={question}>
              <button
                type="button"
                onClick={() => askInThread(question)}
                className="min-h-11 rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-medium text-ink hover:bg-mint"
              >
                {question}
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Screen readers hear the label response's message with its numbers written out. */}
      <p role="status" className="sr-only">
        {visibleToast?.rendered ?? ''}
      </p>
      {visibleToast && (
        <Toast
          text={visibleToast.text}
          numbers={visibleToast.numbers}
          onUndo={visibleToast.undo && busy === null ? () => void send(null) : undefined}
          onRetry={visibleToast.retry ? () => void send(null) : undefined}
          retryUntil={visibleToast.retryUntil}
          onClose={() => setToast(null)}
        />
      )}
      {flight && <FlyingAmount flight={flight} scope={replyRef} onEvent={onFlight} />}
    </div>
  )
}

const BASKET_COLOUR: Record<string, string> = {
  regular_essentials: '--color-basket-essentials',
  unexpected_necessities: '--color-basket-unexpected',
  everyday_spending: '--color-basket-everyday',
}

/**
 * The purchase amount, as a pill, flies from the "Waiting for your answer" row to the basket
 * it was answered into (`--duration-flight`, `--ease-expressive`); its border turns to the
 * basket's colour. Decoration only: hidden from screen readers, never shown with reduced motion.
 */
function FlyingAmount({
  flight,
  scope,
  onEvent,
}: {
  flight: Flight
  /** Sentti's reply: the flight's cells are looked up inside it only. */
  scope: RefObject<HTMLElement | null>
  onEvent: (run: number, event: 'start' | 'land' | 'done') => void
}) {
  const pill = useRef<HTMLSpanElement>(null)
  const [landed, setLanded] = useState(false)
  const { seq: run, basket } = flight

  useLayoutEffect(() => {
    const element = pill.current
    const source = scope.current?.querySelector<HTMLElement>('[data-amount-key="unclassified"]')
    const target = scope.current?.querySelector<HTMLElement>(`[data-amount-key="${basket}"]`)
    let cancelled = false
    const animations: Animation[] = []

    if (!element || !source || !target) {
      onEvent(run, 'start')
      onEvent(run, 'land')
      onEvent(run, 'done')
      return
    }

    const fly = () => {
      if (cancelled) return
      const from = source.getBoundingClientRect()
      const to = target.getBoundingClientRect()
      const width = element.offsetWidth
      const height = element.offsetHeight
      const x0 = from.right - width
      const y0 = from.top + (from.height - height) / 2
      const dx = to.right - width - x0
      const dy = to.top + (to.height - height) / 2 - y0
      element.style.left = `${x0}px`
      element.style.top = `${y0}px`
      element.style.visibility = 'visible'
      onEvent(run, 'start')
      const flightAnimation = element.animate(
        [
          { transform: 'translate(0, 0) scale(1)', borderColor: token('--color-waiting') },
          { transform: `translate(${dx / 2 - 40}px, ${dy / 2}px) scale(1.08)`, offset: 0.5 },
          { transform: `translate(${dx}px, ${dy}px) scale(1)`, borderColor: token(BASKET_COLOUR[basket]) },
        ],
        { duration: tokenMs('--duration-flight', 600), easing: token('--ease-expressive') || 'ease-in-out', fill: 'forwards' },
      )
      animations.push(flightAnimation)
      flightAnimation.finished
        .then(() => {
          if (cancelled) return
          setLanded(true)
          onEvent(run, 'land')
          const fade = element.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 250, delay: 250, fill: 'forwards' })
          animations.push(fade)
          return fade.finished.then(() => {
            if (!cancelled) onEvent(run, 'done')
          })
        })
        .catch(() => undefined)
    }

    // The flight never moves the page: a question asked meanwhile must stay in view. When the rows
    // are not on screen (above the header or where the toast comes up), the amount does not fly
    // and the numbers simply change.
    // The visible band, measured now: under the header and above the composer. The toast comes up
    // only after the landing, so it does not cover the flight.
    const header = document.querySelector('header')?.getBoundingClientRect().bottom ?? 0
    const floor = document.getElementById('chat-input')?.closest('form')?.getBoundingClientRect().top ?? window.innerHeight
    const rows = [source, target].map((element) => element.closest('li')?.getBoundingClientRect())
    if (rows.some((box) => !box || box.top < header || box.bottom > floor)) {
      onEvent(run, 'start')
      onEvent(run, 'land')
      onEvent(run, 'done')
      return
    }
    fly()
    return () => {
      cancelled = true
      for (const animation of animations) animation.cancel()
    }
  }, [run, basket, scope, onEvent])

  return createPortal(
    <span
      ref={pill}
      aria-hidden="true"
      style={{ visibility: 'hidden' }}
      className="pointer-events-none fixed left-0 top-0 z-50 inline-flex items-center gap-1.5 whitespace-nowrap rounded-pill border-2 border-waiting bg-surface py-1 pl-2 pr-3 text-[15px] font-bold tabular-nums text-ink shadow-float"
    >
      <span className="text-base">{landed ? BASKETS[basket]?.icon : '?'}</span>
      {flight.display}
    </span>,
    document.body,
  )
}
