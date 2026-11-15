// Mock mode only (`/cards`): every card example of the contract on one page, so each card
// renderer can be checked at 375 px without a persona that happens to have that card.
// A live build does not include this page (see App.tsx).
import type { BreakdownCard, Card, OverviewResponse, ReviewCard, SafeToSaveCard as SafeToSaveData } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { OpeningContext, type Opening } from '../lib/openingContext.ts'
import { AnswerCard } from '../components/AnswerCard.tsx'
import { BasketStrip } from '../components/BasketStrip.tsx'
import { BillsCards } from '../components/BillsCard.tsx'
import { BillFlow } from '../components/bill/BillFlow.tsx'
import { OverviewSheetContent } from '../components/OverviewSheetContent.tsx'
import { SafeToSaveCard } from '../components/SafeToSaveCard.tsx'
import { MascotGallery } from '../components/voice/MascotGallery.tsx'

const examples = contract.examples as unknown as Record<string, unknown>

/** An opening that asks about the `card.review` purchase, for the pointer's "Show" state. */
const REVIEW_TX = (examples['card.review'] as ReviewCard).tx_ref
const ASKING_OPENING: Opening = {
  reviewTxRef: REVIEW_TX,
  shownReview: { txRef: REVIEW_TX, phase: 'asking' },
  reportReview: () => {},
  answered: null,
  threadReviews: {},
  claimThreadReview: () => {},
  releaseThreadReview: () => {},
  refresh: () => {},
  scrollToReview: () => {},
  pushClientTurn: () => {},
  overview: null,
}

/** The contract has no standalone `bills` example; it is a card of `overview.response`. */
const OVERVIEW_CARDS = (examples['overview.response'] as { cards: Card[] }).cards

/** The baskets breakdown of `overview.response`, for the answer-card shape (#696). */
const OVERVIEW_BASKETS = OVERVIEW_CARDS.find((card): card is BreakdownCard => card.type === 'breakdown')!

/** `card.whatif` with a caveat status; the caveat text is hand-made (no contract example has one). */
const WHATIF_EXAMPLE = examples['card.whatif'] as Card & { result: Record<string, unknown> }
const WHATIF_WITH_CAVEAT = {
  ...WHATIF_EXAMPLE,
  result: { ...WHATIF_EXAMPLE.result, status: 'estimate_with_caveat', caveats: ['Your restaurant spending changes a lot from month to month, so this saving is rough.'] },
} as unknown as Card

/** The baskets breakdown of `overview.response_pending` (a review is pending, so four cells). */
const PENDING_BASKETS = (examples['overview.response_pending'] as { cards: Card[] }).cards.find(
  (card): card is BreakdownCard => card.type === 'breakdown',
)!

/**
 * The same breakdown as the core writes it in Finnish (labels from `core/tools/config.py`, amounts
 * in its FI format), so the strip's longest labels can be checked. The contract has no FI example.
 */
const FI_TEXT: Record<string, { label: string; display: string }> = {
  regular_essentials: { label: 'Säännölliset välttämättömät', display: '1 889,04 € / kk' },
  unexpected_necessities: { label: 'Odottamattomat välttämättömät', display: '341,08 € / kk' },
  everyday_spending: { label: 'Arjen kulutus', display: '600,41 € / kk' },
  unclassified: { label: 'Odottaa vastaustasi', display: '180,07 € / kk' },
}
const PENDING_BASKETS_FI: BreakdownCard = {
  ...PENDING_BASKETS,
  title: 'Mihin rahasi menevät tavallisena kuukautena',
  items: PENDING_BASKETS.items.map((item) => {
    const fi = FI_TEXT[item.key]
    return fi ? { ...item, label: fi.label, amount: { ...item.amount, label: fi.label, display: fi.display } } : item
  }),
}

const SAFE_TO_SAVE = [
  'card.safe_to_save',
  'card.safe_to_save_aleksi',
  'card.safe_to_save_zero',
  'card.safe_to_save_everyday',
] as const

export default function CardGallery() {
  return (
    <div className="flex flex-col gap-8 pb-4">
      <p className="text-sm text-muted">
        Contract {contract.contract_version} card examples (mock mode only).
      </p>
      {/* The overview sheet's content (#320): Sanna (the lead persona, the demo start), Aino (with
          insights) and the no-hero example. */}
      {(['overview.response_pending', 'overview.response', 'overview.response_no_hero'] as const).map((name) => (
        <section key={name} id={`${name}-sheet`} aria-label={`${name} overview sheet content`} className="flex flex-col gap-2">
          <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">{name} → OverviewSheetContent</p>
          <OverviewSheetContent overview={examples[name] as OverviewResponse} />
        </section>
      ))}
      {/* The basket strip (#312) in its three places: a full strip (the answer to "Where did my
          money go?" and the overview sheet), the same in Finnish, and the mini row of Sentti's
          answer after "Needed" / "My choice", which carries the flight targets. */}
      <section id="overview.response_pending-strip" aria-label="overview.response_pending basket strip" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">overview.response_pending → BasketStrip</p>
        <BasketStrip card={PENDING_BASKETS} />
      </section>
      <section id="overview.response_pending-strip-fi" aria-label="overview.response_pending basket strip, Finnish" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">overview.response_pending → BasketStrip (FI texts)</p>
        <BasketStrip card={PENDING_BASKETS_FI} />
      </section>
      <section id="overview.response_pending-strip-mini" aria-label="overview.response_pending mini basket row" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">{'overview.response_pending → BasketStrip keys=[unclassified, unexpected_necessities] title=null flight'}</p>
        <BasketStrip card={PENDING_BASKETS} keys={['unclassified', 'unexpected_necessities']} title={null} flight />
      </section>
      {SAFE_TO_SAVE.map((name) => (
        <section key={name} id={name} aria-label={name} className="flex flex-col gap-2">
          <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">{name}</p>
          <SafeToSaveCard card={examples[name] as SafeToSaveData} />
        </section>
      ))}
      {/* Safe to save inside a chat answer (#477): the card draws no actions there (AnswerView does). */}
      <section id="card.safe_to_save-answer" aria-label="card.safe_to_save in an answer" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">card.safe_to_save → in an answer</p>
        <AnswerCard card={examples['card.safe_to_save'] as Card} />
      </section>
      <section id="overview.response-bills" aria-label="overview.response bills" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">overview.response → cards[type=bills]</p>
        <BillsCards cards={OVERVIEW_CARDS} />
      </section>
      {/* Answer cards with their own renderers (#264): profile, peer, and bills inside an answer. */}
      {(['card.profile', 'card.peer'] as const).map((name) => (
        <section key={name} id={`${name}-answer`} aria-label={`${name} in an answer`} className="flex flex-col gap-2">
          <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">{name} → in an answer</p>
          <AnswerCard card={examples[name] as Card} />
        </section>
      ))}
      <section id="bills-answer" aria-label="bills in an answer" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">overview.response → cards[type=bills] → in an answer</p>
        {OVERVIEW_CARDS.filter((card) => card.type === 'bills').map((card) => (
          <AnswerCard key={card.card_id} card={card} />
        ))}
      </section>
      {/* The baskets breakdown inside a chat answer (#696): the answer-card shape, like the bills above. */}
      <section id="baskets-answer" aria-label="baskets breakdown in an answer" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">overview.response → cards[type=breakdown] → in an answer</p>
        <AnswerCard card={OVERVIEW_BASKETS} />
      </section>
      {/* A what-if with caveats inside a chat answer (#696): the contract has no example with one, so
          the card.whatif example gets a status and a caveat here; the caveats show as the sheet shows them. */}
      <section id="card.whatif-caveat-answer" aria-label="card.whatif with a caveat in an answer" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">card.whatif (status estimate_with_caveat, hand-made caveat) → in an answer</p>
        <AnswerCard card={WHATIF_WITH_CAVEAT} />
      </section>
      {/* A review card inside a chat answer (#318, #450): when nobody shows the question (here: no
          opening), the answer shows the card with its answer buttons; when the opening shows it,
          only a line and "Show". */}
      <section id="card.review-in-answer" aria-label="card.review in an answer" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">card.review → in an answer (nobody shows it: the card itself)</p>
        <AnswerCard card={examples['card.review'] as Card} />
      </section>
      <section id="card.review-in-answer-asking" aria-label="card.review in an answer, opening asks" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">card.review → in an answer (the opening shows it: a pointer)</p>
        <OpeningContext.Provider value={ASKING_OPENING}>
          <AnswerCard card={examples['card.review'] as Card} />
        </OpeningContext.Provider>
      </section>
      <section id="bill-flow" aria-label="bill flow" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">bill flow (section 11, mock)</p>
        <BillFlow />
      </section>
      {/* Sentti's mascot for the voice mode (#798, #811): five states, EN and FI, 160 and 96 px. */}
      <section id="sentti-mascot" aria-label="Sentti mascot states" className="flex flex-col gap-2">
        <p className="font-mono text-xs [overflow-wrap:anywhere] text-muted">SenttiMascot → idle, listening, thinking, speaking, celebrate</p>
        <MascotGallery />
      </section>
    </div>
  )
}
