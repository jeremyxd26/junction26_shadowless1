// Mock mode only (`/cards`): every card example of the contract on one page, so each card
// renderer can be checked at 375 px without a persona that happens to have that card.
// A live build does not include this page (see App.tsx).
import type { SafeToSaveCard as SafeToSaveData } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { SafeToSaveCard } from '../components/SafeToSaveCard.tsx'

const examples = contract.examples as unknown as Record<string, unknown>

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
    </div>
  )
}
