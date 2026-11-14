import type { Component, Num, SafeToSaveCard as SafeToSaveData, SafeToSaveReason } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'
import { ActionButton, CARD_TITLE, CardShell } from './cards.tsx'
import { useEstimateToggle } from '../lib/useEstimateToggle.ts'
import { EstimateBadge, EstimateNote } from './EstimateBadge.tsx'
import { NumberChip } from './NumberChip.tsx'

const SIGN: Record<Component['operation'], string> = { add: '+', subtract: '−' }

/**
 * Components exactly as the API lists them: label, sign and chip. The app never adds
 * them up; `total` only repeats a number the API already sent (the headline), and the
 * caller passes it only when that number is the rows' result.
 */
function ComponentRows({ components, total }: { components: Component[]; total?: { label: string; number: Num } }) {
  return (
    <ul className="mt-3 flex flex-col">
      {components.map((component, index) => (
        // With large text the amount moves under the label instead of running past the card (#493).
        <li key={component.key} className="flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-1 py-1.5">
          <span className="min-w-[min(4rem,100%)] flex-1 basis-0 text-base text-ink-2">
            {(index > 0 || component.operation === 'subtract') && (
              <span className="mr-1.5 font-semibold text-ink">{SIGN[component.operation]}</span>
            )}
            {component.label}
          </span>
          <span className="ml-auto max-w-full shrink-0">
            <NumberChip number={component.amount} />
          </span>
        </li>
      ))}
      {total && (
        <li className="mt-1 flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line pt-2">
          <span className="min-w-[min(4rem,100%)] flex-1 basis-0 text-base font-bold text-ink">
            <span className="mr-1.5">=</span>
            {total.label}
          </span>
          <span className="ml-auto max-w-full shrink-0">
            <NumberChip number={total.number} />
          </span>
        </li>
      )}
    </ul>
  )
}

/** Why a typical month leaves nothing: the API's text, then the amount as a chip. */
function Reason({ reason }: { reason: SafeToSaveReason }) {
  return (
    <div className="mt-3 rounded-md bg-sunken p-3">
      <p className="text-base text-ink-2">{reason.text}</p>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 text-sm font-semibold text-ink">{reason.category?.label ?? reason.amount.label}</span>
        <NumberChip number={reason.amount} />
      </div>
    </div>
  )
}

/**
 * The headline a week and a day (contract 0.3.5, #477): two smaller chips on one line under the
 * month, each the API's `display` and each opening its own evidence. A chip in running text is
 * 32 px with a 44 px hit area; the line is 44 px, so the hit areas stay inside it. Only figures:
 * nothing here names the bank's screen or product, and the S-mobiili button is further down.
 */
function Scales({ weekly, daily }: { weekly?: Num; daily?: Num }) {
  return (
    <div data-save-scales="" className="mt-2 flex min-h-11 flex-wrap items-center gap-x-2 gap-y-3 text-sm text-muted">
      {weekly && <NumberChip number={weekly} size="inline" wrap />}
      {/* The dot goes with the day, so with large text a wrapped line starts "· €6.07 a day". */}
      {daily && (
        <span className="inline-flex max-w-full items-center gap-x-2">
          {weekly && <span aria-hidden="true">·</span>}
          <NumberChip number={daily} size="inline" wrap />
        </span>
      )}
    </div>
  )
}

/**
 * The safe-to-save card (contract section 3): what a typical month leaves, and the money in
 * the account beyond what is needed until payday. Used on the overview and in chat answers.
 * It never says where to put money, and it is never added to safe to spend.
 */
export function SafeToSaveCard({ card }: { card: SafeToSaveData }) {
  const { t } = useSettings()
  const estimate = useEstimateToggle()
  return (
    <div className="flex flex-col gap-3">
      <CardShell>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 pt-2">
            <h2 className={CARD_TITLE}>{card.title}</h2>
            {card.subtitle && <p className="text-sm text-muted">{card.subtitle}</p>}
          </div>
          {card.estimate && (
            <EstimateBadge
              estimate={card.estimate}
              control={estimate.control}
            />
          )}
        </div>
        {card.estimate && estimate.open && <EstimateNote estimate={card.estimate} id={estimate.id} />}

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          <NumberChip number={card.monthly} size="lg" />
          <span className="text-sm text-muted">{card.monthly.period.label}</span>
        </div>
        {(card.weekly || card.daily) && <Scales weekly={card.weekly} daily={card.daily} />}

        {/* "= monthly" only when it really is the result of the rows. When the month is clamped
            to 0 (a reason is sent), the rows would not add up to it, so the reason explains the 0. */}
        <ComponentRows
          components={card.monthly_components}
          total={!card.reason && card.monthly.value > 0 ? { label: card.title, number: card.monthly } : undefined}
        />

        {card.reason && <Reason reason={card.reason} />}

        {card.actions.length > 0 && (
          <div data-card-actions="" className="mt-3 flex flex-wrap gap-2">
            {card.actions.map((action, index) => (
              <ActionButton key={`${action.type}-${index}`} action={action} />
            ))}
          </div>
        )}
      </CardShell>

      <CardShell>
        <h3 className={CARD_TITLE}>{card.stock.label}</h3>
        <p className="text-sm text-muted">{card.stock.period.label}</p>
        <div className="mt-2">
          <NumberChip number={card.stock} size="lg" />
        </div>
        <p className="mt-2 text-base text-ink-2">{card.stock_explanation}</p>
        <ComponentRows components={card.stock_components} />
      </CardShell>

      <p className="px-1 text-sm text-muted">{t.saveSeparate}</p>
    </div>
  )
}
