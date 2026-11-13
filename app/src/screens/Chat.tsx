import { navigate } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

/** Placeholder for the chat stream (POST /api/ask), which is a separate issue. */
export function Chat({ question }: { question: string | null }) {
  const { t } = useSettings()
  return (
    <div className="flex flex-col gap-4 pb-4">
      {question && (
        <p className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-deep px-4 py-3 text-base text-on-deep">{question}</p>
      )}
      <p className="max-w-[85%] rounded-xl rounded-bl-sm border border-line bg-surface px-4 py-3 text-base text-ink-2">
        {t.chatSoon}
      </p>
      <button
        type="button"
        onClick={() => navigate('/')}
        className="mt-2 min-h-12 self-stretch rounded-pill bg-mint px-5 font-semibold text-ink hover:bg-mint-hover"
      >
        {t.toOverview}
      </button>
    </div>
  )
}
