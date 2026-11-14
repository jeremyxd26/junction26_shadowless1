import type { ReactNode } from 'react'
import type { Action, BreakdownCard, Insight, MetricCard, Num, SafeToSpendStatus } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { tokenMs, useCountedText, type Count } from '../lib/motion.ts'
import { askInThread, openEvidence, openWhatIf } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import { useEstimateToggle } from '../lib/useEstimateToggle.ts'
import { EstimateBadge, EstimateNote } from './EstimateBadge.tsx'
import { NumberChip } from './NumberChip.tsx'

/** Flat white card with a thin border, no shadow (DESIGN.md). */
export function CardShell({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-lg border border-line bg-surface p-4 ${className}`}>{children}</section>
}

/** Card titles and row labels: 17/22, bold, brand green. */
export const CARD_TITLE = 'text-card-title font-bold text-brand'

function Chevron() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function ActionButton({ action, onHero = false }: { action: Action; onHero?: boolean }) {
  const className = onHero
    ? 'inline-flex min-h-11 items-center gap-1 text-base font-semibold text-on-hero underline-offset-4 hover:underline'
    : 'inline-flex min-h-11 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint'
  const label = onHero ? (
    <>
      {action.label}
      <Chevron />
    </>
  ) : (
    action.label
  )
  if (action.type === 'open_evidence') {
    return (
      <button type="button" className={className} onClick={() => openEvidence(action.evidence_ref)}>
        {label}
      </button>
    )
  }
  if (action.type === 'ask') {
    return (
      <button type="button" className={className} onClick={() => askInThread(action.prompt)}>
        {label}
      </button>
    )
  }
  if (action.type === 'open_whatif') {
    return (
      <button type="button" className={className} onClick={() => openWhatIf(action.scenario)}>
        {label}
      </button>
    )
  }
  return null
}

/**
 * How the overview's numbers move after a review answer (#35). Keys are the label response's
 * `changes[].key`: `safe_to_spend`, `irregular_reserve` and the basket keys.
 */
export interface NumberMotion {
  /** Counter runs from the `before` value, by key. */
  counts: Record<string, Count>
  /** "was …" hints (the `before` Number), by key, while they show. */
  was: Record<string, Num>
  /** The answer left safe to spend as it was: the hero says "stays the same". */
  steady: boolean
  /** The basket row the purchase moved to, tinted while the hints show. */
  highlight: string | null
  /** The waiting row after an answer: kept while its amount counts to zero, then faded out. */
  waiting: 'keep' | 'leave' | null
}

function Arrow({ down }: { down: boolean }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={`size-4 shrink-0 ${down ? '' : 'rotate-180'}`} fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M12 5v14M6 13l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Check({ className = 'size-4' }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={`shrink-0 ${className}`} fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** The green safe-to-spend block: no border, no shadow, everything white or on-hero-muted. */
const HERO_BLOCK = 'rounded-xl bg-hero p-4 text-on-hero [&_:focus-visible]:outline-mint'

const statusDot: Record<SafeToSpendStatus, string> = {
  ok: 'bg-mint',
  below_usual: 'border-2 border-on-hero-muted',
  nothing_free: 'border-2 border-on-hero-muted',
}

/** The weekly safe-to-spend block: one primary number, one line about the reserve. */
export function HeroCard({ card, motion }: { card: MetricCard; motion?: NumberMotion }) {
  const { t } = useSettings()
  const status = card.status ?? 'ok'
  const reserve = card.components.find((component) => component.key === 'irregular_reserve')
  const wasPrimary = motion?.was.safe_to_spend
  const wasReserve = motion?.was.irregular_reserve
  const estimate = useEstimateToggle()
  return (
    <section className={HERO_BLOCK}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 pt-3">
          <h2 className="text-sm font-semibold text-on-hero-muted">{card.title}</h2>
          {card.subtitle && <p className="text-sm text-on-hero-muted">{card.subtitle}</p>}
        </div>
        {card.estimate && <EstimateBadge estimate={card.estimate} onHero control={estimate.control} />}
      </div>
      {card.estimate && estimate.open && <EstimateNote estimate={card.estimate} id={estimate.id} onHero />}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <NumberChip number={card.primary} size="hero" tone="hero" count={motion?.counts.safe_to_spend} />
        {/* After a review answer: never red, never grey on the green block (DESIGN.md, #35). */}
        {wasPrimary && (
          <span className="motion-fade inline-flex items-center gap-1 text-sm font-semibold text-on-hero-muted">
            <Arrow down={wasPrimary.value > card.primary.value} />
            {t.was(wasPrimary.display)}
          </span>
        )}
        {!wasPrimary && motion?.steady && (
          <span className="motion-fade inline-flex items-center gap-1 text-sm font-semibold text-on-hero-muted">
            <Check />
            {t.staysSame}
          </span>
        )}
      </div>
      <p className="mt-2 flex items-center gap-2 text-sm font-semibold text-on-hero">
        <span aria-hidden="true" className={`size-2.5 rounded-pill ${statusDot[status] ?? statusDot.ok}`} />
        {t.status[status] ?? ''}
      </p>

      {reserve && (
        <p className="mt-3 text-base leading-8 text-on-hero">
          {reserve.label} <NumberChip number={reserve.amount} size="inline" count={motion?.counts.irregular_reserve} />{' '}
          {wasReserve && <span className="motion-fade text-on-hero-muted">({t.was(wasReserve.display)}) </span>}
          {t.keptAside}.
        </p>
      )}

      {card.actions.length > 0 && (
        <div className="mt-2 flex flex-col items-start">
          {card.actions.map((action, index) => (
            <ActionButton key={`${action.type}-${index}`} action={action} onHero />
          ))}
        </div>
      )}
    </section>
  )
}

/**
 * The opening's one big card (the #310 decision, one thought per screen): safe to spend as the
 * API's `display`, a caption chosen by `hero.status`, and a chevron. The whole card opens how the
 * number is made (its evidence: the hero components): the button's `::after` covers the card,
 * and the Estimate badge sits above it, in the flow of the caption row. After a review answer the
 * amount counts to the new value, with "↓ was …" beside it, on the same line, so nothing jumps.
 */
export function HeroSummary({ card, motion }: { card: MetricCard; motion?: NumberMotion }) {
  const { t } = useSettings()
  const primary = card.primary
  const text = useCountedText(primary, motion?.counts.safe_to_spend, tokenMs('--duration-money', 900))
  const count = motion?.counts.safe_to_spend
  const was = motion?.was.safe_to_spend
  const estimate = useEstimateToggle()
  const ref = primary.evidence_ref ?? card.evidence_ref
  const caption = t.heroCaption[card.status ?? 'ok'] ?? t.heroCaption.ok
  const hint = was ? t.was(was.display) : motion?.steady ? t.staysSame : null
  return (
    <section data-opening-part="hero" className="relative rounded-xl bg-hero p-4 text-on-hero [&_:focus-visible]:outline-mint">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <button
          type="button"
          disabled={!ref}
          onClick={() => ref && openEvidence(ref)}
          aria-label={[`${caption}: ${primary.display}`, hint, t.heroHowMade].filter(Boolean).join('. ')}
          className="min-w-0 text-left outline-none after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:after:outline-3 focus-visible:after:outline-offset-2 focus-visible:after:outline-mint"
        >
          {/* 40px at 375 px, down to 28px on a narrow screen or at 200 % zoom. */}
          <span
            key={count?.seq ?? 'static'}
            className={`block text-[clamp(28px,11vw,40px)] font-bold leading-[1.1] tracking-tight tabular-nums ${count ? 'motion-fade' : ''}`}
          >
            {text}
          </span>
        </button>
        {/* The hint's slot is always there, invisible until an answer, so the card never changes
            height when "was …" comes or goes, even where it wraps under the amount. After a review
            answer: never red, never grey on the green block (DESIGN.md, #35). */}
        <span
          aria-hidden={hint ? undefined : true}
          className={`inline-flex items-center gap-1 text-sm font-semibold text-on-hero-muted ${hint ? 'motion-fade' : 'invisible'}`}
        >
          {was ? <Arrow down={was.value > primary.value} /> : <Check />}
          {hint ?? t.was(primary.display)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span aria-hidden="true" className="inline-flex min-w-32 flex-1 items-center gap-1 text-sm font-semibold text-on-hero-muted">
          {caption}
          <Chevron />
        </span>
        {card.estimate && (
          // Above the card's button; the badge keeps its 44px target without making the row taller.
          <div className="relative z-10 -my-2.5 shrink-0">
            <EstimateBadge estimate={card.estimate} onHero control={estimate.control} />
          </div>
        )}
      </div>
      {card.estimate && estimate.open && (
        <div className="relative z-10">
          <EstimateNote estimate={card.estimate} id={estimate.id} onHero />
        </div>
      )}
    </section>
  )
}

/** Shown when the overview has no hero yet (`hero: null`): a clear line instead of an empty slot. */
export function HeroPending() {
  const { t } = useSettings()
  return (
    <section className={HERO_BLOCK}>
      <h2 className="text-sm font-semibold text-on-hero-muted">{t.heroPendingTitle}</h2>
      <div aria-hidden="true" className="mt-3 h-12 w-44 animate-pulse rounded-pill bg-on-hero/15" />
      <p className="mt-3 text-base text-on-hero">{t.heroPending}</p>
    </section>
  )
}

/**
 * The three baskets, always icon + label + colour; a pending purchase shows as a fourth, neutral
 * row. Rows follow DESIGN.md "Basket row": tile, label, the amount on the right, a 6 px bar under it.
 */
export function BasketsCard({ card, motion }: { card: BreakdownCard; motion?: NumberMotion }) {
  const { t } = useSettings()
  // The waiting row is shown only while something waits (or while it fades out after an answer).
  const items = card.items.filter(
    (item) => item.key in BASKETS && !(item.key === 'unclassified' && item.amount.value <= 0 && !motion?.waiting),
  )
  const estimate = useEstimateToggle()
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="baskets-title" tabIndex={-1} className={`${CARD_TITLE} outline-none`}>
            {card.title}
          </h2>
          {card.subtitle && <p className="text-sm text-muted">{card.subtitle}</p>}
        </div>
        {card.estimate && <EstimateBadge estimate={card.estimate} control={estimate.control} />}
      </div>
      {card.estimate && estimate.open && <EstimateNote estimate={card.estimate} id={estimate.id} />}

      <ul className="mt-3 flex flex-col">
        {items.map((item) => {
          const look = BASKETS[item.key]
          const was = motion?.was[item.key]
          const highlighted = motion?.highlight === item.key
          const leaving = item.key === 'unclassified' && motion?.waiting === 'leave'
          return (
            <li
              key={item.key}
              data-basket-row={item.key}
              className={`-mx-2 rounded-md border-b border-line px-2 py-2.5 transition-colors duration-500 last:border-b-0 ${
                highlighted ? look.tint.split(' ')[0] : ''
              } ${leaving ? 'row-leave' : item.key === 'unclassified' ? 'row-enter' : ''}`}
            >
              <div className="flex items-center gap-3">
                <span
                  aria-hidden="true"
                  className={`inline-flex size-10 shrink-0 items-center justify-center rounded-md text-lg font-bold ${look.tint} ${look.color}`}
                >
                  {look.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={`font-semibold leading-5 ${look.color}`}>{item.label}</p>
                  {was && <p className="motion-fade text-xs text-muted">{t.was(was.display)}</p>}
                </div>
                <span data-amount-key={item.key} className="shrink-0">
                  <NumberChip number={item.amount} size="inline" count={motion?.counts[item.key]} />
                </span>
              </div>
              {/* Visual only: the width is the API's share; it glides when the overview is refetched. */}
              <div aria-hidden="true" className="ml-[52px] mt-2 h-1.5 overflow-hidden rounded-pill bg-sunken">
                <div
                  className={`h-full rounded-pill transition-[width] duration-500 ${look.bar}`}
                  style={{ width: `${Math.max(0, Math.min(100, item.share?.value ?? 0))}%` }}
                />
              </div>
            </li>
          )
        })}
      </ul>
      <div className="mt-2 flex items-center justify-between gap-2 text-sm text-muted">
        <span>{card.total.label}</span>
        <NumberChip number={card.total} size="inline" />
      </div>
    </CardShell>
  )
}

const TOKEN = /\{\{(n[0-9]+)\}\}/g

/** Text with number tokens (contract 2.4): each token becomes a chip with the number's `display`. */
export function TokenText({ text, numbers }: { text: string; numbers: Record<string, Num> }) {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0
    if (index > last) parts.push(text.slice(last, index))
    const number = numbers[match[1]]
    parts.push(number ? <NumberChip key={`${match[1]}-${index}`} number={number} size="inline" /> : match[0])
    last = index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

export function InsightCard({ insight }: { insight: Insight }) {
  const estimate = useEstimateToggle()
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-3">
        <h3 className={CARD_TITLE}>{insight.title}</h3>
        {insight.estimate && <EstimateBadge estimate={insight.estimate} control={estimate.control} />}
      </div>
      {insight.estimate && estimate.open && <EstimateNote estimate={insight.estimate} id={estimate.id} />}
      <p className="mt-1 text-base leading-8 text-ink-2">
        <TokenText text={insight.text} numbers={insight.numbers} />
      </p>
      {insight.action && (
        <div className="mt-2">
          <ActionButton action={insight.action} />
        </div>
      )}
    </CardShell>
  )
}
