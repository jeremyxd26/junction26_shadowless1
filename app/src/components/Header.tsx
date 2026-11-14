import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { canGoBack, goBack, openOverview, useUrl } from '../lib/url.ts'
import { showPersonaButton } from '../lib/hostBridge.ts'
import { hostStrings } from '../lib/hostStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { BottomSheet } from './BottomSheet.tsx'
import { learnStrings } from './learn/learnStrings.ts'

const FALLBACK_LONG_PRESS_MS = 600
const MOVE_TOLERANCE_PX = 10

/** `--duration-long-press` from the design tokens, in milliseconds. */
function longPressMs(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--duration-long-press').trim()
  const value = Number.parseFloat(raw)
  if (!Number.isFinite(value) || value <= 0) return FALLBACK_LONG_PRESS_MS
  return raw.endsWith('ms') ? value : raw.endsWith('s') ? value * 1000 : value
}

/**
 * Minimal header inside the host app: back and "Sentti" with a small AI tag and an ⓘ; tapping the
 * title opens the AI disclosure (`ai_disclosure`) in a small sheet. No logo and no own navigation.
 * A long press on the header (not on a button) opens the demo persona switch. In a plain browser,
 * where nobody would guess the long press, a visible button in the left cell opens it too, unless
 * the back chevron takes that cell.
 */
export function Header({
  onLongPress,
  disclosure,
  overviewReady,
  onNewChat,
  threadEmpty = true,
  tab = 'chat',
  onTab,
  learnDot = false,
}: {
  onLongPress: () => void
  disclosure: string
  /** The overview has loaded; while it loads or after it failed, the overview button is disabled. */
  overviewReady: boolean
  /** "New chat": empties the thread; asked first when the thread has something in it. */
  onNewChat?: () => void
  threadEmpty?: boolean
  /** The thread's two tabs (Chat, Learn), on the first screen only. */
  tab?: 'chat' | 'learn'
  onTab?: (tab: 'chat' | 'learn') => void
  /** A small dot on the Learn tab while a lesson is under way. */
  learnDot?: boolean
}) {
  const { t, lang } = useSettings()
  const [about, setAbout] = useState(false)
  const [confirmNew, setConfirmNew] = useState(false)
  // Re-render on every navigation, so the back button follows the current screen.
  useUrl()
  const showBack = canGoBack()
  const showPersonas = showPersonaButton(undefined, showBack)
  const timer = useRef<number | null>(null)
  const start = useRef<{ x: number; y: number } | null>(null)

  const cancel = () => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    start.current = null
  }

  return (
    <header
      className="@container sticky top-0 z-40 bg-page/95 pt-[env(safe-area-inset-top)] backdrop-blur select-none [-webkit-touch-callout:none]"
      onPointerDown={(event) => {
        cancel()
        if (event.target instanceof Element && event.target.closest('button')) return
        start.current = { x: event.clientX, y: event.clientY }
        timer.current = window.setTimeout(() => {
          cancel()
          navigator.vibrate?.(10)
          onLongPress()
        }, longPressMs())
      }}
      onPointerMove={(event) => {
        if (!start.current) return
        const dx = Math.abs(event.clientX - start.current.x)
        const dy = Math.abs(event.clientY - start.current.y)
        if (dx > MOVE_TOLERANCE_PX || dy > MOVE_TOLERANCE_PX) cancel()
      }}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerLeave={cancel}
      onContextMenu={(event) => event.preventDefault()}
    >
      {/* The side columns are as wide as their 2.75rem buttons in rem, not px, so with large text the
          buttons and their columns grow together and the header never runs past the screen (#590).
          At normal size 2.75rem is 44px, as before. Each side column holds up to two buttons (5.5rem,
          kept equal so the title stays centred), so one row needs about 18.3rem; below 19rem (200 %
          text on a phone) the title moves to a second row under the buttons instead of overlapping
          them. At normal size the header is 20rem or wider (320 px), so it stays one row. */}
      <div className="grid min-h-13 grid-cols-[5.5rem_minmax(0,1fr)_5.5rem] items-center px-2">
        {showBack ? (
          <button
            type="button"
            onClick={goBack}
            aria-label={t.back}
            className="inline-flex size-11 items-center justify-center rounded-pill text-brand hover:bg-sunken"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.25">
              <path d="M15 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ) : showPersonas ? (
          // First screen in a plain browser: nowhere to go back to, so the cell opens the demo personas.
          <button
            type="button"
            onClick={onLongPress}
            aria-label={hostStrings(lang).personas}
            className="inline-flex size-11 items-center justify-center rounded-pill text-brand hover:bg-sunken"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="8" r="3.5" />
              <path d="M5 19.5c1.2-3.4 3.9-5 7-5s5.8 1.6 7 5" strokeLinecap="round" />
            </svg>
          </button>
        ) : (
          // Inside a host with nowhere to go back to (not reached today); the cell keeps the title centred.
          <span aria-hidden="true" />
        )}
        {/* The title with its AI tag and an ⓘ opens the AI disclosure, the only place it is shown
            (answers carry no AI line, #685); the right cell is kept for the overview button (#322).
            The ⓘ sits inside the one button, so the grid keeps its three cells at 200 % text (#590). */}
        <h1 className="flex justify-center @max-[19rem]:col-span-3 @max-[19rem]:row-start-2">
          <AboutButton onOpen={() => setAbout(true)} />
        </h1>
        <div className="flex justify-end @max-[19rem]:col-start-3 @max-[19rem]:row-start-1">
        {onNewChat && (
          <button
            type="button"
            onClick={() => (threadEmpty ? onNewChat() : setConfirmNew(true))}
            aria-label={t.newChat}
            className="inline-flex size-11 items-center justify-center rounded-pill text-brand hover:bg-sunken"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M17.5 3.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        {/* The overview sheet from anywhere in the thread (#322). */}
        <button
          type="button"
          onClick={openOverview}
          disabled={!overviewReady}
          aria-label={t.overview}
          className="inline-flex size-11 items-center justify-center rounded-pill text-brand hover:bg-sunken disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
            <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
            <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
            <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
          </svg>
        </button>
        </div>
      </div>
      {onTab && (
        // Chat and Learn as two tabs under the title; each tab keeps a 44 px target (36 px pill + its ::after).
        <div role="tablist" aria-label={learnStrings(lang).tabs} className="mx-4 mb-2 flex gap-1 rounded-pill bg-sunken p-1">
          {(['chat', 'learn'] as const).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => onTab(key)}
              className={`relative min-h-9 flex-1 rounded-pill text-[15px] font-semibold after:absolute after:inset-x-0 after:-inset-y-1 after:content-[''] ${
                tab === key ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink'
              }`}
            >
              {key === 'chat' ? learnStrings(lang).tabChat : learnStrings(lang).tabLearn}
              {key === 'learn' && learnDot && (
                <>
                  <span aria-hidden="true" className="ml-1.5 inline-block size-2 rounded-pill bg-brand align-middle" />
                  <span className="sr-only">, {learnStrings(lang).unfinishedDot}</span>
                </>
              )}
            </button>
          ))}
        </div>
      )}
      {/* In a portal: the header's backdrop blur would pin a fixed sheet to the header. */}
      {about && createPortal(<AboutSheet disclosure={disclosure} onClose={() => setAbout(false)} />, document.body)}
      {confirmNew &&
        onNewChat &&
        createPortal(
          <BottomSheet title={t.newChat} onClose={() => setConfirmNew(false)}>
            <p className="text-base text-ink-2">{t.newChatConfirm}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setConfirmNew(false)
                  onNewChat()
                }}
                className="inline-flex min-h-11 items-center justify-center rounded-pill bg-deep px-5 font-semibold text-on-deep"
              >
                {t.newChat}
              </button>
              <button
                type="button"
                onClick={() => setConfirmNew(false)}
                className="inline-flex min-h-11 items-center justify-center rounded-pill border border-line-strong bg-surface px-5 font-semibold text-ink"
              >
                {t.cancel}
              </button>
            </div>
          </BottomSheet>,
          document.body,
        )}
    </header>
  )
}

/**
 * "Sentti", the visible AI tag and an ⓘ, as one 44 px button. Its accessible name says what it
 * opens: "Sentti, AI. About Sentti" / "Sentti, tekoäly. Tietoa Senttistä".
 */
export function AboutButton({ onOpen }: { onOpen: () => void }) {
  const { t } = useSettings()
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-haspopup="dialog"
      aria-label={`${t.titleLabel}. ${t.aboutSentti}`}
      className="inline-flex min-h-11 items-center gap-1.5 rounded-pill px-2 text-lg font-semibold text-ink hover:bg-sunken"
    >
      Sentti
      <span className="rounded-sm border border-brand px-1 text-xs font-bold leading-4 text-brand">AI</span>
      <svg data-icon="info" aria-hidden="true" viewBox="0 0 24 24" className="size-4 shrink-0 text-brand" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
      </svg>
    </button>
  )
}

/** The AI disclosure as received (`ai_disclosure` of the ready overview, or the app's fallback), in a small sheet. */
export function AboutSheet({ disclosure, onClose }: { disclosure: string; onClose: () => void }) {
  const { t } = useSettings()
  return (
    <BottomSheet title={t.aboutSentti} onClose={onClose}>
      <p className="text-base text-ink-2">{disclosure}</p>
    </BottomSheet>
  )
}
