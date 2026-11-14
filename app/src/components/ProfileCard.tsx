// The `profile` answer card (contract section 3): "What kind of spender am I?".
import type { ReactNode } from 'react'
import type { Card, Num } from '../api/types.ts'
import { CardShell } from './cards.tsx'
import { NumberChip } from './NumberChip.tsx'

export type ProfileData = Card & {
  type: 'profile'
  profile: { key: string; label: string; description: string }
  traits: { key: string; label: string; note: string }[]
  features: { key: string; decides_label: boolean; value: Num }[]
}

/** The profile's name, its one-sentence description, the traits, and the feature numbers as chips. */
export function ProfileCard({ card, header }: { card: ProfileData; header: ReactNode }) {
  // The features that decide the profile come first; otherwise the API's order.
  const features = [...card.features].sort((a, b) => Number(b.decides_label) - Number(a.decides_label))
  return (
    <CardShell>
      {header}
      <p className="mt-3 text-xl leading-7 font-bold text-ink">{card.profile.label}</p>
      <p className="mt-1 text-base text-ink-2">{card.profile.description}</p>

      {card.traits.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {card.traits.map((trait) => (
            <li key={trait.key} className="rounded-md bg-sunken px-3 py-2">
              <p className="text-sm font-semibold text-ink">{trait.label}</p>
              <p className="text-sm text-muted">{trait.note}</p>
            </li>
          ))}
        </ul>
      )}

      {features.length > 0 && (
        <ul className="mt-3 flex flex-col">
          {features.map((feature) => (
            // With large text the chip moves under the label instead of running past the card (#541).
            <li
              key={feature.key}
              className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line py-1"
            >
              <span
                className={`min-w-[min(5rem,100%)] flex-1 basis-0 text-sm ${feature.decides_label ? 'font-semibold text-ink' : 'text-muted'}`}
              >
                {feature.value.label}
              </span>
              <span className="ml-auto max-w-full shrink-0">
                <NumberChip number={feature.value} size="inline" wrap />
              </span>
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  )
}
