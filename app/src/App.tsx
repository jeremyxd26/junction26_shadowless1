import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api/client.ts'
import type { Language } from './api/types.ts'
import { EvidenceSheet } from './components/EvidenceSheet.tsx'
import { OpeningProvider, OpeningTurn } from './components/OpeningTurn.tsx'
import { WhatIfSheet } from './components/WhatIfSheet.tsx'
import { Header } from './components/Header.tsx'
import { PersonaSheet } from './components/PersonaSheet.tsx'
import { LoadingBlock } from './components/States.tsx'
import { parseLanguage, strings } from './lib/i18n.ts'
import { chatStrings } from './lib/chatStrings.ts'
import { SettingsContext, type Settings } from './lib/settings.ts'
import { useChat } from './lib/useChat.ts'
import { useLoad } from './lib/useLoad.ts'
import { redirectChatToThread, setParams, useUrl, whatIfFromParams } from './lib/url.ts'
import { Chat } from './screens/Chat.tsx'

/** `/cards`: the contract's card examples, mock mode only; a live build drops the page. */
const CardGallery = import.meta.env.VITE_API_MODE === 'live' ? null : lazy(() => import('./screens/CardGallery.tsx'))

export default function App() {
  const { path, params } = useUrl()
  const lang = parseLanguage(params.get('lang'))
  const personaParam = params.get('persona')
  const evidenceRef = params.get('evidence')
  const whatIf = whatIfFromParams(params)
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

  // The first screen is the thread on `/`; an old `/chat` link lands there without a Back entry.
  useEffect(() => {
    if (path === '/chat') redirectChatToThread()
  }, [path])

  const settings: Settings = useMemo(() => ({ lang, customerId, t: strings(lang) }), [lang, customerId])
  const { t } = settings
  const closePersonas = useCallback(() => setPersonaSheet(false), [])
  // The conversation lives here, next to the opening; a persona switch starts it empty.
  const chat = useChat(customerId, lang)
  const ready = overview.status === 'ready' ? overview.data : null
  const overviewFailed = overview.status === 'error' || personas.status === 'error'

  return (
    <SettingsContext.Provider value={settings}>
      <div className="mx-auto flex min-h-dvh max-w-[480px] flex-col bg-page">
        <Header onLongPress={() => setPersonaSheet(true)} disclosure={ready?.ai_disclosure || t.disclosure} />
        {/* The composer is pinned to the bottom, so the thread always keeps room for it. */}
        <main className="flex-1 px-4 pt-2 pb-[calc(env(safe-area-inset-bottom)+88px)]">
          {path === '/cards' && CardGallery ? (
            <Suspense fallback={<LoadingBlock lines={6} />}>
              <CardGallery />
            </Suspense>
          ) : (
            <OpeningProvider overview={overview}>
              <Chat
                chat={chat}
                question={params.get('q')}
                disclosure={ready?.ai_disclosure || t.disclosure}
                suggestions={ready?.suggested_questions.length ? ready.suggested_questions : chatStrings(lang).starters}
                opening={
                  <OpeningTurn
                    key={customerId ?? 'no-persona'}
                    overview={overview}
                    personas={personas}
                    onSwitchPersona={() => setPersonaSheet(true)}
                  />
                }
                starters={overviewFailed ? chatStrings(lang).starters : undefined}
              />
            </OpeningProvider>
          )}
          {api.mode === 'mock' && (
            <p className="mt-2 text-center text-xs text-muted">
              {t.mockBadge} · {customerId ?? '…'}
            </p>
          )}
        </main>
      </div>

      {/* Before the evidence sheet, so evidence opened from a what-if number stacks on top. */}
      {whatIf && customerId && (
        <WhatIfSheet key={`${whatIf.selection.kind}:${whatIf.selection.value}`} scenario={whatIf} />
      )}
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
