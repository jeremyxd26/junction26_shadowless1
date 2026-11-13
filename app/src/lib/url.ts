// A tiny router on the History API. Screens are paths (`/`, `/chat`); overlays and demo
// settings are query parameters (`?evidence=`, `?persona=`, `?lang=`), so the WebView back
// button closes a sheet the same way it leaves a screen.
import { useSyncExternalStore } from 'react'
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

/** Back from a screen; on the first screen, hand control back to the host app if it listens. */
export function goBack() {
  const state = window.history.state as { screen?: boolean; sheet?: boolean } | null
  if (state?.screen || state?.sheet) {
    window.history.back()
    return
  }
  const host = (window as unknown as {
    webkit?: { messageHandlers?: { sentti?: { postMessage(message: unknown): void } } }
  }).webkit?.messageHandlers?.sentti
  if (host) host.postMessage({ type: 'close' })
  else if (window.location.pathname !== '/') navigate('/')
  else window.history.back()
}
