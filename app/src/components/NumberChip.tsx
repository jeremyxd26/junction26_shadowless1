import type { Num } from '../api/types.ts'
import { openEvidence } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

type Size = 'inline' | 'md' | 'hero'
type Tone = 'mint' | 'warning' | 'neutral'

const sizes: Record<Size, string> = {
  // Inline chips sit in running text: the pill is 32px high and an invisible
  // ::after extends the hit area to 44px. min-w-11 (on every size) keeps it 44px wide.
  inline:
    'relative min-h-8 px-2.5 text-[15px] leading-5 align-baseline after:absolute after:-inset-y-1.5 after:inset-x-0 after:content-[""]',
  md: 'min-h-11 px-3.5 text-base',
  hero: 'min-h-16 px-5 text-[40px] leading-[44px] tracking-tight',
}

const tones: Record<Tone, string> = {
  mint: 'bg-mint-tint text-ink border-mint-line',
  warning: 'bg-warning-tint text-ink border-warning/40',
  neutral: 'bg-waiting-tint text-ink border-line-strong/40',
}

interface Props {
  number: Num
  size?: Size
  tone?: Tone
}

/**
 * Every number the app shows: the API's `display` string, unchanged, in a pill.
 * With an `evidence_ref` it is a button that opens the evidence sheet.
 */
export function NumberChip({ number, size = 'md', tone = 'mint' }: Props) {
  const { t } = useSettings()
  const className = `inline-flex min-w-11 items-center justify-center whitespace-nowrap rounded-pill border font-semibold tabular-nums ${sizes[size]} ${tones[tone]}`

  if (!number.evidence_ref) {
    return <span className={className}>{number.display}</span>
  }
  const ref = number.evidence_ref
  return (
    <button
      type="button"
      className={`${className} cursor-pointer transition-colors duration-150 hover:border-brand active:bg-mint-line`}
      aria-label={`${number.label}: ${number.display}. ${t.chipHint}`}
      onClick={() => openEvidence(ref)}
    >
      {number.display}
    </button>
  )
}
