// The forecast balance on the bill's due date (#462, contract 0.3.4 `forecast`): before → after as
// chips from `display`, the shortfall when there is one, the sentence as plain text, and for
// `not_covered` the response's ask chip. The tone is an icon and a word with the colour, never
// colour alone; no wording blames the user. `outside_forecast` shows only the sentence.
import type { BillForecast as Forecast } from '../../api/billTypes.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { useSettings } from '../../lib/settings.ts'
import { QUESTION_CHIP } from '../AnswerView.tsx'
import { CARD_TITLE, CardShell } from '../cards.tsx'
import { NumberChip } from '../NumberChip.tsx'

const TONE: Record<string, { icon: string; className: string }> = {
  covered: { icon: '✓', className: 'bg-mint-tint text-brand' },
  tight: { icon: '!', className: 'bg-warning-tint text-warning' },
  not_covered: { icon: '!', className: 'bg-warning-tint text-warning' },
}

interface Props {
  forecast: Forecast
  /** Asks a question in the thread (the path of every ask chip); no history entry. */
  onAsk: (question: string) => void
}

export function BillForecast({ forecast, onAsk }: Props) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  const tone = TONE[forecast.status]
  const word = s.forecastStatus[forecast.status]
  const outside = forecast.status === 'outside_forecast'
  return (
    <CardShell>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h3 className={CARD_TITLE}>{s.forecastTitle}</h3>
        {tone && word && (
          <span className={`inline-flex items-center gap-1 rounded-pill px-2.5 py-0.5 text-sm font-bold ${tone.className}`}>
            <span aria-hidden="true">{tone.icon}</span>
            {word}
          </span>
        )}
      </div>

      {!outside && forecast.before && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="sr-only">{forecast.before.label}</span>
          <NumberChip number={forecast.before} />
          {forecast.after && (
            <>
              <span aria-hidden="true" className="text-muted">
                →
              </span>
              <span className="sr-only">{forecast.after.label}</span>
              <NumberChip number={forecast.after} tone={forecast.status === 'covered' ? 'mint' : 'warning'} />
            </>
          )}
        </div>
      )}
      {!outside && forecast.shortfall && (
        <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2">
          <span>{forecast.shortfall.label}</span>
          <NumberChip number={forecast.shortfall} size="inline" tone="warning" />
        </p>
      )}

      <p className="mt-2 text-base text-ink-2">{forecast.text}</p>

      {forecast.status === 'not_covered' && forecast.chip?.type === 'ask' && (
        <div className="mt-3">
          <button type="button" className={QUESTION_CHIP} onClick={() => onAsk(forecast.chip!.prompt)}>
            {forecast.chip.label}
          </button>
        </div>
      )}
    </CardShell>
  )
}
