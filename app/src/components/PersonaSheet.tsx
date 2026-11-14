import type { Language, Persona } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'
import { BottomSheet } from './BottomSheet.tsx'

interface Props {
  personas: Persona[]
  onPick: (customerId: string) => void
  onLanguage: (lang: Language) => void
  onClose: () => void
}

/** Demo controls: which synthetic customer and which language. */
export function PersonaSheet({ personas, onPick, onLanguage, onClose }: Props) {
  const { t, lang, customerId } = useSettings()
  return (
    <BottomSheet title={t.personaTitle} onClose={onClose}>
      <p className="text-sm text-muted">{t.personaHint}</p>
      <ul className="mt-3 flex flex-col gap-2">
        {personas.map((persona) => {
          const selected = persona.customer_id === customerId
          return (
            <li key={persona.customer_id}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onPick(persona.customer_id)}
                className={`flex min-h-14 w-full flex-col items-start rounded-lg border px-3 py-2 text-left ${
                  selected ? 'border-brand bg-mint-tint' : 'border-line bg-surface hover:border-line-strong'
                }`}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="font-semibold text-ink">{persona.display_name}</span>
                  <span className="text-sm text-muted">{persona.profile.label}</span>
                </span>
                <span className="text-sm text-ink-2">{persona.tagline}</span>
              </button>
            </li>
          )
        })}
      </ul>
      <fieldset className="mt-5">
        <legend className="text-sm font-semibold text-ink">{t.language}</legend>
        <div className="mt-2 flex gap-2">
          {(['en', 'fi'] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={lang === option}
              onClick={() => onLanguage(option)}
              className={`min-h-11 min-w-16 rounded-pill border px-4 font-semibold ${
                lang === option ? 'border-brand bg-mint-tint text-ink' : 'border-line bg-surface text-ink'
              }`}
            >
              {option === 'en' ? 'English' : 'Suomi'}
            </button>
          ))}
        </div>
      </fieldset>
    </BottomSheet>
  )
}
