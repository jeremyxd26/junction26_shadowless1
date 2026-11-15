import type { ReactNode } from 'react'

interface Props<T extends string> {
  items: { key: T; label: string; extra?: ReactNode }[]
  value: T
  onChange: (key: T) => void
  label: string
  className?: string
}

/**
 * Two or more tabs on a light track with a white pill that slides to the selected one (eased with the
 * design tokens; at once under reduced motion). Each tab keeps a 44 px target (a 36 px pill + ::after).
 */
export function SegmentedTabs<T extends string>({ items, value, onChange, label, className = '' }: Props<T>) {
  const at = Math.max(0, items.findIndex((item) => item.key === value))
  return (
    <div role="tablist" aria-label={label} className={`relative grid rounded-pill bg-sunken p-1 ${className}`} style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
      <span
        aria-hidden="true"
        className="absolute inset-y-1 left-1 rounded-pill bg-surface shadow-sm transition-transform duration-(--duration-base) ease-(--ease-standard)"
        style={{ width: `calc((100% - 0.5rem) / ${items.length})`, transform: `translateX(${at * 100}%)` }}
      />
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={value === item.key}
          onClick={() => onChange(item.key)}
          className={`relative z-10 min-h-9 rounded-pill text-[0.9375rem] font-semibold transition-colors after:absolute after:inset-x-0 after:-inset-y-1 after:content-[''] ${
            value === item.key ? 'text-ink' : 'text-ink-2 hover:text-ink'
          }`}
        >
          {item.label}
          {item.extra}
        </button>
      ))}
    </div>
  )
}
