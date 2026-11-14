import { Component, type ErrorInfo, type ReactNode } from 'react'
import type { Language } from '../api/types.ts'

const STRINGS = {
  en: { failed: 'This part of the chat didn’t load.' },
  fi: { failed: 'Tämä osa keskustelusta ei latautunut.' },
}

interface Props {
  lang: Language
  /** The same content as a screen of its own (for example `/bill`), and the link's text. */
  screen?: { path: string; label: string }
  /** Called once the turn shows the failure (the turn is no longer busy). */
  onFailed?: () => void
  children: ReactNode
}

/**
 * A client turn's own error boundary (#332). When its component fails, for example when its code
 * chunk no longer exists after a redeploy changed the hashes, only this turn shows a short message
 * and a link to the same content as a screen of its own; the thread and the composer stay. The
 * link loads the page anew, so it also picks up the new chunks.
 */
export class ClientTurnBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('Sentti client turn failed', error, info.componentStack)
    this.props.onFailed?.()
  }

  render() {
    if (!this.state.failed) return this.props.children
    const { lang, screen } = this.props
    return (
      <div role="alert" className="flex flex-col items-start gap-2 rounded-lg bg-danger-tint p-4">
        <p className="text-base text-ink">{STRINGS[lang].failed}</p>
        {screen && (
          <a href={screenHref(screen.path)} className="inline-flex min-h-11 items-center font-semibold text-brand underline underline-offset-4">
            {screen.label}
          </a>
        )}
      </div>
    )
  }
}

/** The screen's path with the page's own query (persona, language, host), without a pending question. */
function screenHref(path: string, search = window.location.search): string {
  const params = new URLSearchParams(search)
  params.delete('q')
  const query = params.toString()
  return query ? `${path}?${query}` : path
}
