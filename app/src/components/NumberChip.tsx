import type { Num } from '../api/types.ts'
import { tokenMs, useCountedText, type Count } from '../lib/motion.ts'
import { openEvidence } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

type Size = 'inline' | 'lead' | 'md' | 'hero'
type Tone = 'mint' | 'warning' | 'neutral' | 'hero'

const sizes: Record<Size, string> = {
  // Inline chips sit in running text: the pill is 32px high and an invisible
  // ::after extends the hit area to 44px. min-w-11 (on every size) keeps it 44px wide.
  inline:
    'relative min-h-8 px-2.5 text-[15px] leading-5 align-baseline after:absolute after:-inset-y-1.5 after:inset-x-0 after:content-[""]',
  // In the review question (20px bold text): 36px pill, hit area extended to 44px.
  lead: 'relative min-h-9 px-3 text-[20px] leading-7 align-baseline after:absolute after:-inset-y-1 after:inset-x-0 after:content-[""]',
  md: 'min-h-11 px-3.5 text-base',
  hero: 'min-h-16 px-5 text-[40px] leading-[44px] tracking-tight',
}

const tones: Record<Tone, string> = {
  mint: 'bg-mint-tint text-ink border-mint-line',
  warning: 'bg-warning-tint text-ink border-warning/40',
  neutral: 'bg-waiting-tint text-ink border-line-strong/40',
  // White figures on the green safe-to-spend block (DESIGN.md).
  hero: 'bg-transparent text-on-hero border-on-hero-muted/60',
}

const pressed: Record<Tone, string> = {
  mint: 'hover:border-brand active:bg-mint-line',
  warning: 'hover:border-brand active:bg-mint-line',
  neutral: 'hover:border-brand active:bg-mint-line',
  hero: 'hover:border-on-hero active:bg-on-hero/10',
}

interface Props {
  number: Num
  size?: Size
  tone?: Tone
  /** Count up or down from an earlier value to `number` (a review answer); ends on `display`. */
  count?: Count
}

/**
 * Every number the app shows: the API's `display` string, unchanged, in a pill.
 * With an `evidence_ref` it is a button that opens the evidence sheet.
 */
export function NumberChip({ number, size = 'md', tone = 'mint', count }: Props) {
  const { t } = useSettings()
  const text = useCountedText(number, count, tokenMs('--duration-money', 900))
  const className = `inline-flex min-w-11 items-center justify-center whitespace-nowrap rounded-pill border font-semibold tabular-nums ${sizes[size]} ${tones[tone]}`
  // A new count cross-fades the figure in (the only motion left under reduced motion).
  const shown = count ? (
    <span key={count.seq} className="motion-fade">
      {text}
    </span>
  ) : (
    text
  )

  if (!number.evidence_ref) {
    return <span className={className}>{shown}</span>
  }
  const ref = number.evidence_ref
  return (
    <button
      type="button"
      className={`${className} cursor-pointer transition-colors duration-150 ${pressed[tone]}`}
      aria-label={`${number.label}: ${number.display}. ${t.chipHint}`}
      onClick={() => openEvidence(ref)}
    >
      {shown}
    </button>
  )
}
