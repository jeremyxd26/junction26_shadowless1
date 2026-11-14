// Pure helpers of the demo-path check (scripts/demo-check.mjs, #491), kept apart so vitest can test them.
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

/** The UI texts each step looks for, per `--lang`. */
export const TEXT = {
  en: {
    asks: 'Sentti asks',
    needed: /Needed/,
    undo: /^(Undo)$/,
    firstQuestion: 'Where did my money go?',
    saveQuestion: 'How could I save more?',
    saveAction: /monthly saving/i,
    hostScreen: /Monthly saving/,
    startOver: 'Start over',
    mockBadge: 'Mock data',
  },
  fi: {
    asks: 'Sentti kysyy',
    needed: /Välttämätön|Needed/,
    undo: /^(Peru|Kumoa)$/,
    firstQuestion: 'Mihin rahani menivät?',
    saveQuestion: 'Miten voisin säästää enemmän?',
    // The core's label is "Katso kuukausisäästäminen S-mobiilissa"; the stem also covers "kuukausisäästö".
    saveAction: /kuukausisääst|monthly saving/i,
    hostScreen: /Kuukausisäästö/,
    startOver: 'Aloita alusta',
    mockBadge: 'Testidata',
  },
}

export const USAGE = 'Usage: npm run demo:check -- <base-url> [--lang en|fi] [--persona CUST00860]'

/** `<base-url> [--lang en|fi] [--persona ID]` → { base, lang, persona } or { error }. */
export function parseArgs(argv) {
  const out = { base: null, lang: 'en', persona: 'CUST00860' }
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--lang' || arg === '--persona') {
      const value = argv[++i]
      if (!value) return { error: `${arg} needs a value` }
      out[arg.slice(2)] = value
    } else if (arg.startsWith('--')) {
      return { error: `unknown option ${arg}` }
    } else if (!out.base) {
      out.base = arg
    } else {
      return { error: `unexpected argument ${arg}` }
    }
  }
  if (!out.base) return { error: 'the base URL is missing' }
  let url
  try {
    url = new URL(out.base)
  } catch {
    return { error: `not a URL: ${out.base}` }
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return { error: `not an http(s) URL: ${out.base}` }
  if (out.lang !== 'en' && out.lang !== 'fi') return { error: `--lang is en or fi, not ${out.lang}` }
  if (!/^CUST\d{5}$/.test(out.persona)) return { error: `--persona looks like CUST00860, not ${out.persona}` }
  out.base = url.origin + url.pathname.replace(/\/+$/, '')
  return out
}

/**
 * A Chromium to drive, without downloading one: `DEMO_CHECK_BROWSER`, then playwright's own
 * browser cache (chrome-headless-shell first, the newest build first), then an installed
 * Chrome or Chromium. Returns null when there is none.
 */
export function findBrowser({
  env = process.env,
  home = homedir(),
  platform = process.platform,
  exists = existsSync,
  list = (dir) => readdirSync(dir),
} = {}) {
  if (env.DEMO_CHECK_BROWSER) return exists(env.DEMO_CHECK_BROWSER) ? env.DEMO_CHECK_BROWSER : null
  const caches = [
    env.PLAYWRIGHT_BROWSERS_PATH,
    platform === 'darwin' ? join(home, 'Library', 'Caches', 'ms-playwright') : null,
    platform === 'linux' ? join(home, '.cache', 'ms-playwright') : null,
    platform === 'win32' && env.LOCALAPPDATA ? join(env.LOCALAPPDATA, 'ms-playwright') : null,
  ].filter(Boolean)
  const build = (name) => Number(name.split('-').pop()) || 0
  const inCache = []
  for (const cache of caches) {
    let names = []
    try {
      names = list(cache)
    } catch {
      continue
    }
    const shells = names.filter((n) => n.startsWith('chromium_headless_shell-')).sort((a, b) => build(b) - build(a))
    const fulls = names.filter((n) => /^chromium-\d+$/.test(n)).sort((a, b) => build(b) - build(a))
    for (const dir of shells) {
      for (const sub of ['chrome-headless-shell-mac-arm64', 'chrome-headless-shell-mac-x64', 'chrome-headless-shell-linux64', 'chrome-headless-shell-win64']) {
        inCache.push(join(cache, dir, sub, platform === 'win32' ? 'chrome-headless-shell.exe' : 'chrome-headless-shell'))
      }
      inCache.push(join(cache, dir, 'chrome-linux', 'headless_shell'))
    }
    for (const dir of fulls) {
      inCache.push(
        join(cache, dir, 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing'),
        join(cache, dir, 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
        join(cache, dir, 'chrome-linux64', 'chrome'),
        join(cache, dir, 'chrome-linux', 'chrome'),
        join(cache, dir, 'chrome-win64', 'chrome.exe'),
        join(cache, dir, 'chrome-win', 'chrome.exe'),
      )
    }
  }
  const installed = {
    darwin: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium'],
    linux: ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser'],
    win32: [
      join(env.PROGRAMFILES ?? 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
      join(env['PROGRAMFILES(X86)'] ?? 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ],
  }[platform] ?? []
  return [...inCache, ...installed].find((path) => exists(path)) ?? null
}

/** An amount as the app shows it: `€1,080.42` / `-€5.00` (en) or `1 080,42 €` (fi, any space). */
export function parseAmount(text, lang) {
  const t = String(text ?? '').trim().replace(/[\s\u00a0\u202f]/g, '').replace('−', '-')
  const match = lang === 'fi' ? /^(-?)([\d]+(?:,\d{1,2})?)€$/.exec(t) : /^(-?)€([\d,]+(?:\.\d{1,2})?)$/.exec(t)
  if (!match) return null
  const digits = lang === 'fi' ? match[2].replace(',', '.') : match[2].replace(/,/g, '')
  const value = Number(digits)
  return Number.isFinite(value) ? (match[1] ? -value : value) : null
}

/** The amounts a count showed, in order: it must only go down and end lower than it began. */
export function downOnly(values) {
  const steps = values.filter((v, i) => i === 0 || v !== values[i - 1])
  const upAt = steps.findIndex((v, i) => i > 0 && v > steps[i - 1])
  const from = steps[0]
  const to = steps[steps.length - 1]
  return { ok: steps.length > 1 && upAt === -1 && to < from, from, to, steps: steps.length - 1, upAt }
}

/** One output line: `3 PASS  Needed: …`. */
export function line(n, status, text) {
  return `${n} ${status.padEnd(4)}  ${text}`
}

/**
 * The opening's chips since #784: one horizontally scrollable row. It holds the question chips (the
 * app's own questions, "Where did my money go?" first) and the client-turn chips ("Show Sentti a
 * bill"), and the whole row carries `data-opening-part`.
 */
export const CHIP_ROW = '[data-turn="opening"] [data-opening-part="client-chips"]'

/** The row's question chips: the chips whose text is a question, in row order. */
export function rowQuestions(texts) {
  return texts.map((text) => String(text ?? '').trim()).filter((text) => /\?$/.test(text))
}

/** Step 2's findings on the row's question chips (an empty list is a pass). */
export function rowProblems(questions, firstQuestion) {
  const problems = []
  if (questions.length < 2) problems.push(`${questions.length} question chips in the row, not 2 or more`)
  if (!questions.includes(firstQuestion)) problems.push(`no "${firstQuestion}" chip in the row`)
  return problems
}
