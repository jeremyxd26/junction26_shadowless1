// A tiny router on the History API. Screens are paths (`/`, `/chat`); overlays and demo
// settings are query parameters (`?evidence=`, `?persona=`, `?lang=`), so the WebView back
// button closes a sheet the same way it leaves a screen.
import { useSyncExternalStore } from 'react'
import { hostPlatform, sendToHost } from './hostBridge.ts'

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

type BackState = { screen?: boolean; sheet?: boolean } | null

/** A sheet is open: opened by the app (history state) or deep-linked (`?evidence=`). */
function sheetOpen(state: BackState): boolean {
  return Boolean(state?.sheet) || new URLSearchParams(window.location.search).has('evidence')
}

/**
 * The first screen is the overview (`/`) with no sheet open, however the customer got there:
 * the history state says nothing about it (Chat → overview pushes a `screen` entry too).
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
 * message there (a plain browser, or the host's handler throws), nothing happens.
 */
export function goBack() {
  const state = window.history.state as BackState
  if (sheetOpen(state)) {
    closeEvidence()
    return
  }
  if (onFirstScreen(state)) {
    sendToHost('close')
    return
  }
  if (state?.screen) window.history.back()
  else navigate('/')
}
