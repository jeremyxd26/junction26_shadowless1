// A tiny router on the History API. The first screen is one thread on `/` (`/chat` redirects to
// it); overlays and demo settings are query parameters (`?evidence=`, `?whatif=`, `?overview=1`,
// `?persona=`, `?lang=`), so the WebView back button closes a sheet the same way it leaves a screen.
import { useSyncExternalStore } from 'react'
import { hostPlatform, sendToHost } from './hostBridge.ts'
import type { WhatIfScenarioRequest, WhatIfSelection } from '../api/types.ts'

const CHANGE = 'sentti:navigate'

function subscribe(onChange: () => void) {
  window.addEventListener('popstate', onChange)
  window.addEventListener(CHANGE, onChange)
  return () => {
    window.removeEventListener('popstate', onChange)
    window.removeEventListener(CHANGE, onChange)
  }
}

function snapshot() {
  return window.location.pathname + window.location.search
}

export interface UrlState {
  path: string
  params: URLSearchParams
}

export function useUrl(): UrlState {
  const href = useSyncExternalStore(subscribe, snapshot)
  const url = new URL(href, window.location.origin)
  return { path: url.pathname, params: url.searchParams }
}

type Mode = 'push' | 'replace'

function go(url: URL, mode: Mode, state: Record<string, unknown> | null = null) {
  const target = url.pathname + url.search
  if (mode === 'push') window.history.pushState(state, '', target)
  else window.history.replaceState(state ?? window.history.state, '', target)
  window.dispatchEvent(new Event(CHANGE))
}

/** Sets or clears query parameters on the current path. */
export function setParams(changes: Record<string, string | null>, mode: Mode = 'replace') {
  const url = new URL(window.location.href)
  for (const [name, value] of Object.entries(changes)) {
    if (value === null) url.searchParams.delete(name)
    else url.searchParams.set(name, value)
  }
  go(url, mode)
}

/** Goes to another screen and keeps the demo settings (persona, lang). */
export function navigate(path: string, params: Record<string, string> = {}) {
  const current = new URL(window.location.href)
  const url = new URL(path, window.location.origin)
  for (const keep of ['persona', 'lang']) {
    const value = current.searchParams.get(keep)
    if (value) url.searchParams.set(keep, value)
  }
  for (const [name, value] of Object.entries(params)) url.searchParams.set(name, value)
  go(url, 'push', { screen: true })
}

/**
 * Asks a question in the thread on `/`: it becomes `?q=`, which the thread sends and then drops.
 * The URL is replaced, not pushed, so asking adds no history entry and Back never re-asks.
 */
export function askInThread(question: string) {
  const url = new URL(window.location.href)
  url.pathname = '/'
  url.searchParams.set('q', question)
  go(url, 'replace')
}

/** `/chat` (an old link) shows the thread on `/`, replacing the entry so Back never returns to it. */
export function redirectChatToThread() {
  const url = new URL(window.location.href)
  url.pathname = '/'
  go(url, 'replace')
}

/** Opens the evidence sheet as a history entry, so Back closes it. */
export function openEvidence(ref: string) {
  const url = new URL(window.location.href)
  url.searchParams.set('evidence', ref)
  go(url, 'push', { sheet: true })
}

/**
 * Closes the evidence sheet. If the app opened it, step back in history; if it was
 * deep-linked (`?evidence=` in the first URL), there is nothing to go back to, so replace.
 */
export function closeEvidence() {
  const state = window.history.state as { sheet?: boolean } | null
  if (state?.sheet) window.history.back()
  else setParams({ evidence: null })
}

const WHATIF_KINDS: WhatIfSelection['kind'][] = ['category', 'basket', 'mcc', 'merchant']
const DEFAULT_CUT = 20

/**
 * Opens the what-if sheet as a history entry (`?whatif=<kind>:<value>&cut=<pct>`), so Back
 * closes it. Accepts the `scenario` of an `open_whatif` action, which the contract passes on
 * unchanged; anything that is not a valid scenario is ignored.
 */
export function openWhatIf(scenario: unknown) {
  const parsed = parseScenario(scenario)
  if (!parsed) return
  const url = new URL(window.location.href)
  url.searchParams.set('whatif', `${parsed.selection.kind}:${parsed.selection.value}`)
  url.searchParams.set('cut', String(parsed.cut_pct))
  go(url, 'push', { sheet: true })
}

export function closeWhatIf() {
  const state = window.history.state as { sheet?: boolean } | null
  if (state?.sheet) window.history.back()
  else setParams({ whatif: null, cut: null })
}

/**
 * Opens the overview sheet as a history entry (`?overview=1`), so Back closes it (#321). When it is
 * open already, nothing happens: no second entry, no URL change (#513).
 */
export function openOverview() {
  const url = new URL(window.location.href)
  if (overviewFromParams(url.searchParams)) return
  url.searchParams.set('overview', '1')
  go(url, 'push', { sheet: true })
}

/** Closes the overview sheet: a step back if the app opened it, else (deep-linked) a replace. */
export function closeOverview() {
  const state = window.history.state as { sheet?: boolean } | null
  if (state?.sheet) window.history.back()
  else setParams({ overview: null })
}

/** `?overview=1`: the overview sheet is open. */
export function overviewFromParams(params: URLSearchParams): boolean {
  return params.get('overview') === '1'
}

/** The scenario in the URL, or null when it is missing or not valid. */
export function whatIfFromParams(params: URLSearchParams): WhatIfScenarioRequest | null {
  const raw = params.get('whatif')
  if (!raw) return null
  const split = raw.indexOf(':')
  if (split < 1) return null
  return parseScenario({
    selection: { kind: raw.slice(0, split), value: raw.slice(split + 1) },
    cut_pct: Number(params.get('cut') ?? DEFAULT_CUT),
  })
}

function parseScenario(scenario: unknown): WhatIfScenarioRequest | null {
  if (typeof scenario !== 'object' || scenario === null) return null
  const { selection, cut_pct: cut } = scenario as { selection?: { kind?: unknown; value?: unknown }; cut_pct?: unknown }
  const kind = selection?.kind
  const value = selection?.value
  if (!WHATIF_KINDS.includes(kind as WhatIfSelection['kind']) || typeof value !== 'string' || value === '') return null
  const pct = typeof cut === 'number' && Number.isFinite(cut) ? Math.min(100, Math.max(1, Math.round(cut))) : DEFAULT_CUT
  return { selection: { kind: kind as WhatIfSelection['kind'], value }, cut_pct: pct }
}

type BackState = { screen?: boolean; sheet?: boolean } | null

/**
 * A sheet is open: opened by the app (history state) or deep-linked (`?evidence=`, `?whatif=`,
 * `?overview=1`).
 */
function sheetOpen(state: BackState): boolean {
  const params = new URLSearchParams(window.location.search)
  return Boolean(state?.sheet) || params.has('evidence') || params.has('whatif') || overviewFromParams(params)
}

/** Closes the top sheet. They stack evidence over what-if over overview, so they close in that order. */
function closeTopSheet() {
  const params = new URLSearchParams(window.location.search)
  if (params.has('evidence')) closeEvidence()
  else if (params.has('whatif')) closeWhatIf()
  else if (overviewFromParams(params)) closeOverview()
  else closeWhatIf()
}

/**
 * The first screen is the thread on `/` (opened by Sentti's opening turn) with no sheet open,
 * however the customer got there: the history state says nothing about it.
 */
function onFirstScreen(state: BackState): boolean {
  return window.location.pathname === '/' && !sheetOpen(state)
}

/**
 * Whether the back button has somewhere to go: a sheet to close, an inner screen to leave, or,
 * on the first screen, a host app to hand control to. In a plain browser the first screen has
 * none, so the button is not shown there.
 */
export function canGoBack(): boolean {
  const state = window.history.state as BackState
  if (!onFirstScreen(state)) return true
  return hostPlatform() !== null
}

/**
 * Back: close the open sheet, or leave an inner screen; on the first screen, hand control back
 * to the host app with `sentti.close` (iOS or Android, docs/integration.md). If no host takes the
 * message there (a plain browser, or the host's handler throws), nothing happens. With a sheet
 * open on the first screen (the overview, too), Back closes the sheet and never sends `sentti.close`.
 */
export function goBack() {
  const state = window.history.state as BackState
  if (sheetOpen(state)) {
    closeTopSheet()
    return
  }
  if (onFirstScreen(state)) {
    sendToHost('close')
    return
  }
  if (state?.screen) window.history.back()
  else navigate('/')
}
