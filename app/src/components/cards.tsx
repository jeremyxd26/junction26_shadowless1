import type { ReactNode } from 'react'
import type { Action, Insight, MetricCard, Num, SafeToSpendStatus } from '../api/types.ts'
import { useCountedText, usePrefersReducedMotion, type Count } from '../lib/motion.ts'
import { hostScreenTarget, openHostScreen } from '../lib/hostActions.ts'
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
  if (action.type === 'open_host_screen') {
    // Into the bank app's own screen (#268); a target the app does not know renders nothing.
    const target = hostScreenTarget(action.target)
    if (!target) return null
    return (
      <button type="button" className={className} onClick={() => openHostScreen(target)}>
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
      {card.estimate && estimate.open && <EstimateNote estimate={card.estimate} id={estimate.id} onHero result={card.primary} />}

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
 * The opening's key line (Renat's light redesign): no card, safe to spend as the API's `display` in large light
 * text, centred, with the caption chosen by `hero.status` and a chevron under it, and a small Estimate badge.
 * The amount's button opens how the number is made (its evidence: the hero components); its `::after` covers the
 * block, and the Estimate badge sits above it. After a review answer the amount counts to the new value, with
 * "↓ was …" in a line of its own whose room is always kept, so nothing jumps during the count (the video scene).
 */
export function HeroSummary({ card, motion, pending = false }: { card: MetricCard; motion?: NumberMotion; pending?: boolean }) {
  const { t } = useSettings()
  // While a review answer is on its way (#965): a soft breathing, or a still 60 % under reduced motion.
  const reduced = usePrefersReducedMotion()
  const primary = card.primary
  // A short, calm count after a review answer (Renat, #958: 400 ms); instant under reduced motion.
  const text = useCountedText(primary, motion?.counts.safe_to_spend, 400)
  const count = motion?.counts.safe_to_spend
  const was = motion?.was.safe_to_spend
  const estimate = useEstimateToggle()
  const ref = primary.evidence_ref ?? card.evidence_ref
  const caption = t.heroCaption[card.status ?? 'ok'] ?? t.heroCaption.ok
  const hint = was ? t.was(was.display) : motion?.steady ? t.staysSame : null
  return (
    <section data-opening-part="hero" aria-busy={pending || undefined} className="relative flex flex-col items-center pt-1 text-center">
      <button
        type="button"
        disabled={!ref}
        onClick={() => ref && openEvidence(ref)}
        aria-label={[`${caption}: ${primary.display}`, hint, t.heroAfter, t.heroHowMade].filter(Boolean).join('. ')}
        className="min-w-0 outline-none after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:after:outline-3 focus-visible:after:outline-offset-2 focus-visible:after:outline-brand"
      >
        {/* 56px at 375 px, down to 40px on a narrow screen or at 200 % zoom. */}
        <span
          key={count?.seq ?? 'static'}
          className={`block text-[clamp(40px,15vw,56px)] font-light leading-[1.05] tracking-tight text-ink tabular-nums ${count ? 'motion-fade' : ''} ${
            pending ? (reduced ? 'opacity-60' : 'hero-pending') : ''
          }`}
        >
          {text}
        </span>
      </button>
      {/* The caption and the Estimate badge share one row (#945: room for the basket bar); the badge sits above the
          block's button and keeps its 44px target. */}
      <div className="mt-1 flex flex-wrap items-center justify-center gap-x-2">
        <span aria-hidden="true" className="inline-flex items-center gap-0.5 text-base font-semibold text-brand">
          {caption}
          <Chevron />
        </span>
        {card.estimate && (
          <div className="relative z-10 -my-2">
            <EstimateBadge estimate={card.estimate} control={estimate.control} />
          </div>
        )}
      </div>
      {/* The hint's line is always there, invisible until an answer, so the block never changes height when
          "was …" comes or goes. After a review answer: never red (DESIGN.md, #35). */}
      <span
        aria-hidden={hint ? undefined : true}
        className={`mt-1 inline-flex items-center gap-1 text-sm font-semibold text-muted ${hint ? 'motion-fade' : 'invisible'}`}
      >
        {was ? <Arrow down={was.value > primary.value} /> : <Check />}
        {hint ?? t.was(primary.display)}
      </span>
      {card.estimate && estimate.open && (
        <div className="relative z-10 mt-2 w-full text-left">
          <EstimateNote estimate={card.estimate} id={estimate.id} result={primary} />
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
      {/* Pulses only when motion is welcome; under reduced motion the placeholder stands still (#881). */}
      <div aria-hidden="true" className="mt-3 h-12 w-44 motion-safe:animate-pulse rounded-pill bg-on-hero/15" />
      <p className="mt-3 text-base text-on-hero">{t.heroPending}</p>
    </section>
  )
}

const TOKEN = /\{\{(n[0-9]+)\}\}/g

/**
 * Text with number tokens (contract 2.4): each token becomes a chip with the number's `display`;
 * a chat answer passes `plain` for numbers as text, without the pill (#684).
 */
export function TokenText({ text, numbers, plain = false }: { text: string; numbers: Record<string, Num>; plain?: boolean }) {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0
    if (index > last) parts.push(text.slice(last, index))
    const number = numbers[match[1]]
    parts.push(number ? <NumberChip key={`${match[1]}-${index}`} number={number} size="inline" tone={plain ? 'plain' : 'mint'} /> : match[0])
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
