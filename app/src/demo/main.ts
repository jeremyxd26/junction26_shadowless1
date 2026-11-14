// The demo frame (#325, #326): the module inside a neutral host app, for the stage demo and the
// video. A separate Vite entry (demo.html), so none of this is in the module's bundle. Same origin as
// the module, so the app's CSP (`frame-ancestors 'self'`, scripts and styles from 'self') allows it:
// no inline script or style; sizes are set through the CSSOM.
import './demo.css'

type Lang = 'en' | 'fi'

interface Strings {
  host: string
  row: string
  persona: string
  defaultPersona: string
  language: string
  note: string
  messages: string
  noMessages: string
  close: string
  draftTitle: string
  payee: string
  payeeMissing: string
  amount: string
  dueDate: string
  reference: string
  iban: string
  confirm: string
  nothingPaid: string
  opensIn: (target: string) => string
  invalidJson: string
}

const TEXT: Record<Lang, Strings> = {
  en: {
    host: 'Bank app (demo)',
    row: 'Money coach · Sentti',
    persona: 'Persona',
    defaultPersona: 'Default',
    language: 'Language',
    note: 'A neutral host app around the Sentti module, for the demo. Not a bank screen.',
    messages: 'Messages',
    noMessages: 'No messages yet.',
    close: 'Close',
    draftTitle: 'Payment draft',
    payee: 'Payee',
    payeeMissing: 'Payee missing',
    amount: 'Amount',
    dueDate: 'Due date',
    reference: 'Reference',
    iban: 'Account (IBAN)',
    confirm: 'Confirm in the bank app',
    nothingPaid: 'Demo: nothing is paid',
    opensIn: (target) => `Opens in the bank app: ${target}`,
    invalidJson: '(not JSON)',
  },
  fi: {
    host: 'Pankkisovellus (demo)',
    row: 'Rahavalmentaja · Sentti',
    persona: 'Henkilö',
    defaultPersona: 'Oletus',
    language: 'Kieli',
    note: 'Neutraali isäntäsovellus Sentti-moduulin ympärillä esittelyä varten. Ei pankin näkymä.',
    messages: 'Viestit',
    noMessages: 'Ei vielä viestejä.',
    close: 'Sulje',
    draftTitle: 'Maksuluonnos',
    payee: 'Saaja',
    payeeMissing: 'Saaja puuttuu',
    amount: 'Summa',
    dueDate: 'Eräpäivä',
    reference: 'Viite',
    iban: 'Tilinumero (IBAN)',
    confirm: 'Vahvista pankin sovelluksessa',
    nothingPaid: 'Demo: mitään ei makseta',
    opensIn: (target) => `Avautuu pankin sovelluksessa: ${target}`,
    invalidJson: '(ei JSONia)',
  },
}

const PHONE_W = 375
const PHONE_H = 812
const MODULE_H = 768 // 812 minus the 44 px host header
const LOG_LIMIT = 30

interface ModuleWindow extends Window {
  sentti?: { postMessage(json: string): void }
}

interface Envelope {
  type?: unknown
  v?: unknown
  payload?: unknown
}

/** `?path=` sets the module's path in the iframe (for example `/cards` under `npm run dev`). Same origin only. */
function safePath(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return '/'
  return value
}

const page = new URLSearchParams(location.search)
const state = {
  lang: (page.get('lang') === 'fi' ? 'fi' : 'en') as Lang,
  persona: page.get('persona') ?? '',
  path: safePath(page.get('path')),
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

// Layout: controls outside the phone, then the phone (host header + host home or the module) and
// the message log beside it (below it on a narrow screen).
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

const workspace = el('div', 'workspace')
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

const log = el('section', 'log')
const logTitle = el('h2', 'log-title')
log.setAttribute('aria-labelledby', 'log-title')
logTitle.id = 'log-title'
const logList = el('ol', 'log-list')
logList.setAttribute('aria-live', 'polite')
const logEmpty = el('p', 'log-empty')
log.append(logTitle, logEmpty, logList)

workspace.append(slot, log)
stage.append(controls, workspace)
root.append(stage)

let frame: HTMLIFrameElement | null = null
let sheet: HTMLElement | null = null

function moduleUrl(): string {
  const params = new URLSearchParams({ lang: state.lang })
  if (state.persona) params.set('persona', state.persona)
  return `${state.path}?${params.toString()}`
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

/** Every message goes to the log, unknown names too; the known ones get the host's mock answer. */
function parseEnvelope(json: string): Envelope | null {
  try {
    const value: unknown = JSON.parse(json)
    return typeof value === 'object' && value !== null ? (value as Envelope) : null
  } catch {
    return null
  }
}

function onModuleMessage(json: string) {
  const message = parseEnvelope(json)
  addLog(message, json)
  if (!message || typeof message.type !== 'string') return
  const payload = (typeof message.payload === 'object' && message.payload !== null ? message.payload : {}) as Record<string, unknown>
  if (message.type === 'sentti.close') closeModule()
  else if (message.type === 'sentti.paymentDraft') showDraft(payload)
  else if (message.type === 'sentti.openHostScreen') showHostScreen(payload)
}

function addLog(message: Envelope | null, raw: string) {
  const t = TEXT[state.lang]
  const item = el('li', 'log-item')
  const time = el('span', 'log-time', new Date().toLocaleTimeString(state.lang === 'fi' ? 'fi-FI' : 'en-GB'))
  const name = el('span', 'log-name', message && typeof message.type === 'string' ? message.type : t.invalidJson)
  const body = el('code', 'log-body', message ? JSON.stringify(message.payload ?? {}) : raw.slice(0, 160))
  item.append(time, name, body)
  logList.prepend(item)
  while (logList.children.length > LOG_LIMIT) logList.lastElementChild?.remove()
  logEmpty.hidden = true
}

function formatDate(iso: unknown): string {
  if (typeof iso !== 'string') return '–'
  const date = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat(state.lang === 'fi' ? 'fi-FI' : 'en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(date)
}

function text(value: unknown): string {
  return typeof value === 'string' && value !== '' ? value : '–'
}

/** A mock host sheet over the module, inside the phone. Close, the scrim and Escape dismiss it. */
function openSheet(title: string, build: (panel: HTMLElement) => void) {
  closeSheet()
  const t = TEXT[state.lang]
  sheet = el('div', 'sheet')
  const scrim = el('button', 'sheet-scrim')
  scrim.type = 'button'
  scrim.tabIndex = -1
  scrim.setAttribute('aria-label', t.close)
  scrim.addEventListener('click', closeSheet)
  const panel = el('div', 'sheet-panel')
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-modal', 'true')
  panel.setAttribute('aria-labelledby', 'sheet-title')
  const head = el('div', 'sheet-head')
  const heading = el('h2', 'sheet-title', title)
  heading.id = 'sheet-title'
  const close = el('button', 'sheet-close', '×')
  close.type = 'button'
  close.setAttribute('aria-label', t.close)
  close.addEventListener('click', closeSheet)
  head.append(heading, close)
  panel.append(head)
  build(panel)
  sheet.append(scrim, panel)
  hostBody.append(sheet)
  const primary = panel.querySelector<HTMLElement>('.sheet-primary')
  ;(primary ?? close).focus()
}

function closeSheet() {
  sheet?.remove()
  sheet = null
}

function showDraft(payload: Record<string, unknown>) {
  const t = TEXT[state.lang]
  const amount = payload.amount as { display?: unknown } | null | undefined
  openSheet(t.draftTitle, (panel) => {
    const list = el('dl', 'draft')
    const rows: [string, string, boolean][] = [
      [t.payee, typeof payload.payee === 'string' && payload.payee ? payload.payee : t.payeeMissing, !(typeof payload.payee === 'string' && payload.payee)],
      [t.amount, text(amount?.display), false],
      [t.dueDate, formatDate(payload.due_date), false],
      [t.reference, text(payload.reference), false],
      [t.iban, text(payload.iban), false],
    ]
    for (const [label, value, missing] of rows) {
      const wrap = el('div', 'draft-row')
      wrap.append(el('dt', 'draft-label', label), el('dd', missing ? 'draft-value draft-missing' : 'draft-value', value))
      list.append(wrap)
    }
    const confirm = el('button', 'sheet-primary', t.confirm)
    confirm.type = 'button'
    confirm.addEventListener('click', closeSheet)
    panel.append(list, confirm, el('p', 'sheet-note', t.nothingPaid))
  })
}

function showHostScreen(payload: Record<string, unknown>) {
  const t = TEXT[state.lang]
  const target = text(payload.target)
  openSheet(t.opensIn(target), (panel) => {
    const done = el('button', 'sheet-primary', t.close)
    done.type = 'button'
    done.addEventListener('click', closeSheet)
    panel.append(el('p', 'sheet-note', t.nothingPaid), done)
  })
}

function openModule() {
  state.open = true
  closeSheet()
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
  closeSheet()
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
  if (state.path !== '/') params.set('path', state.path)
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
  logTitle.textContent = t.messages
  logEmpty.textContent = t.noMessages
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

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && sheet) closeSheet()
})

/** 1:1 on a phone; on a laptop the phone is scaled down to fit under the controls. */
function fit() {
  const narrow = window.innerWidth <= 480
  const room = window.innerHeight - controls.offsetHeight - 48
  const scale = narrow ? 1 : Math.min(1, room / PHONE_H, (window.innerWidth - 32) / PHONE_W)
  phone.style.setProperty('--scale', String(Math.max(0.4, scale)))
  slot.style.height = `${Math.round(PHONE_H * Math.max(0.4, scale))}px`
  slot.style.width = `${Math.round(PHONE_W * Math.max(0.4, scale))}px`
}
window.addEventListener('resize', fit)

render()
void loadPersonas()
fit()
syncPageUrl()
