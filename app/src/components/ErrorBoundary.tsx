import { Component, type ErrorInfo, type ReactNode } from 'react'
import { parseLanguage, strings } from '../lib/i18n.ts'

interface State {
  failed: boolean
}

/**
 * Last line of defence: if a screen throws while rendering (for example on a response
 * shape the app does not expect), show a message and a reload button instead of a blank
 * WebView. It sits outside the settings context, so it reads the language from the URL.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('Sentti screen failed', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    const t = strings(parseLanguage(new URLSearchParams(window.location.search).get('lang')))
    return (
      <div className="mx-auto flex min-h-dvh max-w-[480px] flex-col justify-center bg-page px-4 pt-[env(safe-area-inset-top)]">
        <div role="alert" className="flex flex-col items-start gap-3 rounded-lg bg-danger-tint p-4">
          <p className="text-base text-ink">{t.crash}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="min-h-11 rounded-pill bg-mint px-5 font-semibold text-ink hover:bg-mint-hover"
          >
            {t.reload}
          </button>
        </div>
      </div>
    )
  }
}
