// Mock mode only (`/cards`): every card example of the contract on one page, so each card
// renderer can be checked at 375 px without a persona that happens to have that card.
// A live build does not include this page (see App.tsx).
import type { Card, SafeToSaveCard as SafeToSaveData } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { AnswerCard } from '../components/AnswerCard.tsx'
import { BillsCards } from '../components/BillsCard.tsx'
import { BillFlow } from '../components/bill/BillFlow.tsx'
import { SafeToSaveCard } from '../components/SafeToSaveCard.tsx'

const examples = contract.examples as unknown as Record<string, unknown>

/** The contract has no standalone `bills` example; it is a card of `overview.response`. */
const OVERVIEW_CARDS = (examples['overview.response'] as { cards: Card[] }).cards

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
      {SAFE_TO_SAVE.map((name) => (
        <section key={name} id={name} aria-label={name} className="flex flex-col gap-2">
          <p className="font-mono text-xs text-muted">{name}</p>
          <SafeToSaveCard card={examples[name] as SafeToSaveData} />
        </section>
      ))}
      <section id="overview.response-bills" aria-label="overview.response bills" className="flex flex-col gap-2">
        <p className="font-mono text-xs text-muted">overview.response → cards[type=bills]</p>
        <BillsCards cards={OVERVIEW_CARDS} />
      </section>
      {/* A review card inside a chat answer: the generic card, no answer buttons (answered in "Sentti asks"). */}
      <section id="card.review-in-answer" aria-label="card.review in an answer" className="flex flex-col gap-2">
        <p className="font-mono text-xs text-muted">card.review → in an answer</p>
        <AnswerCard card={examples['card.review'] as Card} />
      </section>
      <section id="bill-flow" aria-label="bill flow" className="flex flex-col gap-2">
        <p className="font-mono text-xs text-muted">bill flow (section 11, mock)</p>
        <BillFlow />
      </section>
    </div>
  )
}
