import { shownSources } from '../lib/answerSources.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { useSettings } from '../lib/settings.ts'

/**
 * Where a knowledge answer comes from (the done event's `sources`, #922), shown under the answer like a chat
 * assistant cites: a small "Sources" label and up to three mint pill chips, a globe, the publisher in bold and the
 * title cut to fit. A tap opens the page in a new tab. Chips wrap on a narrow screen; 44 px targets.
 */
export function AnswerSources({ sources }: { sources: unknown }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const list = shownSources(sources)
  if (list.length === 0) return null
  return (
    <section aria-label={s.sources} className="card-enter flex flex-col gap-1.5">
      <p className="text-xs font-semibold text-muted">{s.sources}</p>
      <ul className="flex flex-wrap gap-2">
        {list.map((source) => (
          <li key={source.url} className="max-w-full min-w-0">
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={s.sourceLabel(source.publisher, source.title)}
              className="inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-pill border border-mint-line bg-mint-tint px-3 text-sm text-ink hover:border-brand"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4 shrink-0 text-brand" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <circle cx="12" cy="12" r="9" />
                <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
              </svg>
              <span className="shrink-0 font-bold">{source.publisher}</span>
              {source.title && <span className="min-w-0 max-w-[12rem] truncate text-ink-2">{source.title}</span>}
            </a>
          </li>
        ))}
      </ul>
    </section>
  )
}
