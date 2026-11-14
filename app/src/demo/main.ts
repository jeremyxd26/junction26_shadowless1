// The demo frame (#325): the module inside a neutral host app, for the stage demo and the video.
// A separate Vite entry (demo.html), so none of this is in the module's bundle. Same origin as the
// module, so the app's CSP (`frame-ancestors 'self'`, scripts and styles from 'self') allows it:
// no inline script or style; sizes are set through the CSSOM.
import './demo.css'

type Lang = 'en' | 'fi'

const TEXT: Record<Lang, { host: string; row: string; persona: string; defaultPersona: string; language: string; note: string }> = {
  en: {
    host: 'Bank app (demo)',
    row: 'Money coach · Sentti',
    persona: 'Persona',
    defaultPersona: 'Default',
    language: 'Language',
    note: 'A neutral host app around the Sentti module, for the demo. Not a bank screen.',
  },
  fi: {
    host: 'Pankkisovellus (demo)',
    row: 'Rahavalmentaja · Sentti',
    persona: 'Henkilö',
    defaultPersona: 'Oletus',
    language: 'Kieli',
    note: 'Neutraali isäntäsovellus Sentti-moduulin ympärillä esittelyä varten. Ei pankin näkymä.',
  },
}

const PHONE_W = 375
const PHONE_H = 812
const MODULE_H = 768 // 812 minus the 44 px host header

interface ModuleWindow extends Window {
  sentti?: { postMessage(json: string): void }
}

const page = new URLSearchParams(location.search)
const state = {
  lang: (page.get('lang') === 'fi' ? 'fi' : 'en') as Lang,
  persona: page.get('persona') ?? '',
  open: false,
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

function chevron(): SVGSVGElement {
  const ns = 'http://www.w3.org/2000/svg'
  const svg = document.createElementNS(ns, 'svg')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('aria-hidden', 'true')
  svg.setAttribute('class', 'chevron')
  const path = document.createElementNS(ns, 'path')
  path.setAttribute('d', 'M9 5l7 7-7 7')
  svg.append(path)
  return svg
}

// Layout: controls outside the phone, then the phone (host header + host home or the module).
const root = document.getElementById('demo')!
const stage = el('main', 'stage')
const controls = el('div', 'controls')
const personaLabel = el('label', 'control')
const personaText = el('span', 'control-label')
const personaSelect = el('select', 'select')
personaLabel.append(personaText, personaSelect)
const langGroup = el('div', 'control')
langGroup.setAttribute('role', 'group')
const langText = el('span', 'control-label')
const langButtons = (['en', 'fi'] as const).map((lang) => {
  const button = el('button', 'toggle', lang.toUpperCase())
  button.type = 'button'
  button.addEventListener('click', () => setLang(lang))
  return button
})
langGroup.append(langText, ...langButtons)
const note = el('p', 'note')
controls.append(personaLabel, langGroup, note)

const slot = el('div', 'phone-slot')
const phone = el('div', 'phone')
const hostHeader = el('header', 'host-header')
const hostBody = el('div', 'host-body')
const home = el('div', 'host-home')
const row = el('button', 'row-card')
row.type = 'button'
const rowText = el('span', 'row-text')
row.append(rowText, chevron())
row.addEventListener('click', () => openModule())
home.append(row)
hostBody.append(home)
phone.append(hostHeader, hostBody)
slot.append(phone)
stage.append(controls, slot)
root.append(stage)

let frame: HTMLIFrameElement | null = null

function moduleUrl(): string {
  const params = new URLSearchParams({ lang: state.lang })
  if (state.persona) params.set('persona', state.persona)
  return `/?${params.toString()}`
}

/**
 * Makes the module believe it runs in an Android host: `window.sentti` takes JSON strings, like
 * the object `addWebMessageListener` injects. The module reads it on every call, but it renders
 * the header before this runs; so the frame changes the URL (adds `host=demo`) and fires
 * `popstate`, which re-renders the header with the back chevron (#175) and without the visible
 * persona button (#323).
 */
function installHost(target: HTMLIFrameElement) {
  const win = target.contentWindow as ModuleWindow | null
  if (!win) return
  win.sentti = { postMessage: (json: string) => onModuleMessage(json) }
  const { pathname, search } = win.location
  if (!new URLSearchParams(search).has('host')) {
    win.history.replaceState(win.history.state, '', `${pathname}${search}${search ? '&' : '?'}host=demo`)
  }
  win.dispatchEvent(new PopStateEvent('popstate', { state: win.history.state }))
}

function onModuleMessage(json: string) {
  let message: { type?: unknown; payload?: unknown }
  try {
    message = JSON.parse(json) as { type?: unknown; payload?: unknown }
  } catch {
    return
  }
  if (message.type === 'sentti.close') closeModule()
  // Other messages (paymentDraft, openHostScreen) get mock host sheets in the next issue (#326).
}

function openModule() {
  state.open = true
  frame?.remove()
  frame = el('iframe', 'module')
  frame.title = 'Sentti'
  frame.width = String(PHONE_W)
  frame.height = String(MODULE_H)
  frame.addEventListener('load', () => installHost(frame!))
  frame.src = moduleUrl()
  home.hidden = true
  hostBody.append(frame)
  frame.focus()
  syncPageUrl()
}

function closeModule() {
  state.open = false
  frame?.remove()
  frame = null
  home.hidden = false
  row.focus()
  syncPageUrl()
}

function setLang(lang: Lang) {
  if (lang === state.lang) return
  state.lang = lang
  render()
  if (state.open) openModule()
  else syncPageUrl()
}

function setPersona(id: string) {
  state.persona = id
  if (state.open) openModule()
  else syncPageUrl()
}

/** The demo page's own URL keeps the choice, so a reload or a shared link shows the same thing. */
function syncPageUrl() {
  const params = new URLSearchParams({ lang: state.lang })
  if (state.persona) params.set('persona', state.persona)
  history.replaceState(null, '', `${location.pathname}?${params.toString()}`)
}

function render() {
  const t = TEXT[state.lang]
  document.documentElement.lang = state.lang
  hostHeader.textContent = t.host
  rowText.textContent = t.row
  personaText.textContent = t.persona
  langText.textContent = t.language
  langGroup.setAttribute('aria-label', t.language)
  note.textContent = t.note
  for (const button of langButtons) {
    button.setAttribute('aria-pressed', String(button.textContent?.toLowerCase() === state.lang))
  }
  const first = personaSelect.options[0]
  if (first) first.textContent = t.defaultPersona
}

/** The personas the API serves; in a mock build there is no API, so only "Default" is offered. */
async function loadPersonas() {
  const fallback = el('option', undefined, TEXT[state.lang].defaultPersona)
  fallback.value = ''
  personaSelect.append(fallback)
  try {
    const response = await fetch(`/api/personas?lang=${state.lang}`, { headers: { Accept: 'application/json' } })
    const body: unknown = response.ok ? await response.json() : null
    const list = (body as { personas?: { customer_id: string; display_name: string }[] } | null)?.personas
    for (const persona of Array.isArray(list) ? list : []) {
      const option = el('option', undefined, `${persona.display_name} (${persona.customer_id})`)
      option.value = persona.customer_id
      personaSelect.append(option)
    }
  } catch {
    // No API (mock build or offline): the module picks its own default persona.
  }
  if (state.persona && ![...personaSelect.options].some((option) => option.value === state.persona)) {
    const option = el('option', undefined, state.persona)
    option.value = state.persona
    personaSelect.append(option)
  }
  personaSelect.value = state.persona
}
personaSelect.addEventListener('change', () => setPersona(personaSelect.value))

/** 1:1 on a phone; on a laptop the phone is scaled down to fit under the controls. */
function fit() {
  const narrow = window.innerWidth <= 480
  const room = window.innerHeight - controls.offsetHeight - 48
  const scale = narrow ? 1 : Math.min(1, room / PHONE_H, (window.innerWidth - 32) / PHONE_W)
  phone.style.setProperty('--scale', String(Math.max(0.4, scale)))
  slot.style.height = `${Math.round(PHONE_H * Math.max(0.4, scale))}px`
}
window.addEventListener('resize', fit)

render()
void loadPersonas()
fit()
syncPageUrl()
