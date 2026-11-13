import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api/client.ts'
import { ApiError } from './api/errors.ts'
import type { Language } from './api/types.ts'
import { EvidenceSheet } from './components/EvidenceSheet.tsx'
import { Header } from './components/Header.tsx'
import { PersonaSheet } from './components/PersonaSheet.tsx'
import { ErrorBlock, LoadingBlock } from './components/States.tsx'
import { parseLanguage, strings } from './lib/i18n.ts'
import { chatStrings } from './lib/chatStrings.ts'
import { SettingsContext, type Settings } from './lib/settings.ts'
import { useChat } from './lib/useChat.ts'
import { useLoad, type Loaded } from './lib/useLoad.ts'
import { setParams, useUrl } from './lib/url.ts'
import { Chat } from './screens/Chat.tsx'
import { Overview } from './screens/Overview.tsx'

/** `/cards`: the contract's card examples, mock mode only; a live build drops the page. */
const CardGallery = import.meta.env.VITE_API_MODE === 'live' ? null : lazy(() => import('./screens/CardGallery.tsx'))

export default function App() {
  const { path, params } = useUrl()
  const lang = parseLanguage(params.get('lang'))
  const personaParam = params.get('persona')
  const evidenceRef = params.get('evidence')
  const [personaSheet, setPersonaSheet] = useState(false)

  const loadPersonas = useCallback(() => api.personas(lang), [lang])
  const personas = useLoad(`personas|${lang}`, loadPersonas)
  const firstPersona = personas.status === 'ready' ? (personas.data.personas[0]?.customer_id ?? null) : null
  const customerId = personaParam ?? firstPersona

  const loadOverview = useCallback(() => api.overview(customerId ?? '', lang), [customerId, lang])
  const overview = useLoad(customerId ? `overview|${customerId}|${lang}` : null, loadOverview)

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const settings: Settings = useMemo(() => ({ lang, customerId, t: strings(lang) }), [lang, customerId])
  const { t } = settings
  const closePersonas = useCallback(() => setPersonaSheet(false), [])
  // The chat lives here, so its conversation survives a trip to the overview and back.
  const chat = useChat(customerId, lang)
  const ready = overview.status === 'ready' ? overview.data : null
  const isChat = path === '/chat'

  return (
    <SettingsContext.Provider value={settings}>
      <div className="mx-auto flex min-h-dvh max-w-[480px] flex-col bg-page">
        <Header onLongPress={() => setPersonaSheet(true)} />
        <main
          className={`flex-1 px-4 pt-2 ${isChat ? 'pb-[calc(env(safe-area-inset-bottom)+88px)]' : 'pb-[calc(env(safe-area-inset-bottom)+16px)]'}`}
        >
          {path === '/cards' && CardGallery ? (
            <Suspense fallback={<LoadingBlock lines={6} />}>
              <CardGallery />
            </Suspense>
          ) : isChat ? (
            <Chat
              chat={chat}
              question={params.get('q')}
              suggestions={ready?.suggested_questions.length ? ready.suggested_questions : chatStrings(lang).starters}
            />
          ) : overview.status === 'ready' ? (
            <Overview overview={overview.data} />
          ) : overview.status === 'error' || personas.status === 'error' ? (
            <ErrorBlock
              message={errorMessage(overview.status === 'error' ? overview.error : personas.status === 'error' ? personas.error : null)}
              onRetry={retryFor(overview) ?? retryFor(personas)}
            >
              <button
                type="button"
                onClick={() => setPersonaSheet(true)}
                className="min-h-11 rounded-pill border border-mint-line bg-surface px-5 font-semibold text-brand"
              >
                {t.switchPersona}
              </button>
            </ErrorBlock>
          ) : (
            <LoadingBlock lines={6} />
          )}
          {api.mode === 'mock' && (
            <p className="mt-6 text-center text-xs text-muted">
              {t.mockBadge} · {customerId ?? '…'}
            </p>
          )}
        </main>
      </div>

      {evidenceRef && customerId && <EvidenceSheet evidenceRef={evidenceRef} />}
      {personaSheet && personas.status === 'ready' && (
        <PersonaSheet
          personas={personas.data.personas}
          onPick={(id) => {
            setParams({ persona: id, evidence: null })
            setPersonaSheet(false)
          }}
          onLanguage={(next: Language) => setParams({ lang: next })}
          onClose={closePersonas}
        />
      )}
    </SettingsContext.Provider>
  )
}

function errorMessage(error: unknown): string | undefined {
  return error instanceof ApiError ? error.message : undefined
}

/** Offer a retry only when the API says it may help (contract section 4). */
function retryFor(result: Loaded<unknown>): (() => void) | undefined {
  if (result.status !== 'error') return undefined
  if (result.error instanceof ApiError && !result.error.retryable) return undefined
  return result.retry
}
