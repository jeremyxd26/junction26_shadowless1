import type { Num } from '../api/types.ts'
import { chipWrapping } from '../lib/displayParts.ts'
import { DisplayText } from './ChipText.tsx'
import { tokenMs, useCountedText, type Count } from '../lib/motion.ts'
import { openEvidence } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

type Size = 'inline' | 'lead' | 'md' | 'lg' | 'hero'
type Tone = 'mint' | 'warning' | 'neutral' | 'hero' | 'plain'

const sizes: Record<Size, string> = {
  // Inline chips sit in running text: the pill is 32px high and an invisible
  // ::after extends the hit area to 44px. min-w-11 (on every size) keeps it 44px wide.
  inline:
    'relative min-h-8 px-2.5 text-(length:--text-sm) leading-(--text-sm--line-height) align-baseline after:absolute after:-inset-y-1.5 after:inset-x-0 after:content-[""]',
  // In the review question (20px bold text): a 36px pill, its hit area extended to 44px.
  lead: 'relative min-h-9 px-2.5 text-[19px] leading-6 align-baseline after:absolute after:-inset-y-1 after:inset-x-0 after:content-[""]',
  md: 'min-h-11 px-3.5 text-base',
  // Headline of a white card (safe to save): the 30/34 amount token, fits "€12,345.67 a month" at 375 px.
  // The amount of a large chip never breaks, so with very large text its size is capped by the
  // screen width (11vw / 15.5vw); at normal text size, 320 px and up, the cap is never reached (#493).
  lg: 'min-h-14 px-4 text-[length:min(var(--text-review-amount),11vw)] leading-(--text-review-amount--line-height) tracking-tight',
  hero: 'min-h-16 px-5 text-[length:min(var(--text-hero),15.5vw)] leading-(--text-hero--line-height) tracking-tight',
}

/**
 * The `plain` tone of a chat answer (#684): the number as text, no pill. Inline it takes the size
 * of the text around it; an invisible ::after keeps the 44 px target. `lg` is the answer's one
 * main number.
 */
const plainSizes: Record<Size, string> = {
  inline: 'relative align-baseline after:absolute after:-inset-x-2 after:-inset-y-2.5 after:content-[""]',
  lead: 'relative align-baseline after:absolute after:-inset-x-2 after:-inset-y-2 after:content-[""]',
  md: 'min-h-11',
  lg: 'min-h-11 text-[length:min(var(--text-review-amount),11vw)] leading-(--text-review-amount--line-height) tracking-tight',
  hero: 'min-h-16 text-[length:min(var(--text-hero),15.5vw)] leading-(--text-hero--line-height) tracking-tight',
}

const tones: Record<Tone, string> = {
  mint: 'bg-mint-tint text-ink border-mint-line',
  warning: 'bg-warning-tint text-ink border-warning/40',
  neutral: 'bg-waiting-tint text-ink border-line-strong/40',
  // White figures on the green safe-to-spend block (DESIGN.md).
  hero: 'bg-transparent text-on-hero border-on-hero-muted/60',
  // No colour of its own: the caller's text colour (ink, or a change's tone).
  plain: '',
}

const pressed: Record<Tone, string> = {
  mint: 'hover:border-brand active:bg-mint-line',
  warning: 'hover:border-brand active:bg-mint-line',
  neutral: 'hover:border-brand active:bg-mint-line',
  hero: 'hover:border-on-hero active:bg-on-hero/10',
  // A thin underline says it opens its transactions; it is not the glossary's dotted one.
  plain: 'underline decoration-current/35 decoration-1 underline-offset-4 hover:decoration-current',
}

interface Props {
  number: Num
  size?: Size
  tone?: Tone
  /** Count up or down from an earlier value to `number` (a review answer); ends on `display`. */
  count?: Count
  /**
   * An inline-size chip that stands on its own (a row's amount, not part of a sentence) may wrap
   * like the larger sizes. Chips in running text never wrap.
   */
  wrap?: boolean
}

/**
 * Every number the app shows: the API's `display` string, unchanged, in a pill.
 * With an `evidence_ref` it is a button that opens the evidence sheet.
 */
export function NumberChip({ number, size = 'md', tone = 'mint', count, wrap = false }: Props) {
  const { t } = useSettings()
  const text = useCountedText(number, count, tokenMs('--duration-money', 900))
  // Chips in running text never wrap. A standalone chip may wrap its display at a space outside the
  // amount ("€1,080.55" / "a month") when its container is too narrow, e.g. at 200 % text (#493).
  const inText = (size === 'inline' || size === 'lead') && !wrap
  const wrapping = chipWrapping(inText)
  const className =
    tone === 'plain'
      ? `inline-flex items-center ${wrapping} font-semibold tabular-nums ${plainSizes[size]}`
      : `inline-flex min-w-11 items-center justify-center ${wrapping} rounded-pill border font-semibold tabular-nums ${sizes[size]} ${tones[tone]}`
  const body = inText ? text : <DisplayText text={text} />
  // A new count cross-fades the figure in (the only motion left under reduced motion).
  const shown = count ? (
    <span key={count.seq} className="motion-fade">
      {body}
    </span>
  ) : (
    body
  )

  if (!number.evidence_ref) {
    return <span className={className}>{shown}</span>
  }
  const ref = number.evidence_ref
  return (
    <button
      type="button"
      className={`${className} cursor-pointer transition-colors duration-(--duration-fast) ${pressed[tone]}`}
      aria-label={`${number.label}: ${number.display}. ${t.chipHint}`}
      onClick={() => openEvidence(ref)}
    >
      {shown}
    </button>
  )
}
