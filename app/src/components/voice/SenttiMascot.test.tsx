// Sentti's mascot (#798): the markup of each state, the text that stands in for motion, and the
// rule that every movement lives inside `prefers-reduced-motion: no-preference`.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { SenttiMascot } from './SenttiMascot.tsx'
import { MASCOT_STATES, mascotStateLabel, type MascotState } from './mascotStrings.ts'

// Vitest serves every .css import as an empty string, so the stylesheet is read from disk (Node 20.16+).
const fs = (globalThis as unknown as { process: { getBuiltinModule: (id: 'node:fs') => { readFileSync: (path: URL, encoding: 'utf8') => string } } }).process.getBuiltinModule('node:fs')
const css = fs.readFileSync(new URL('../../index.css', import.meta.url), 'utf8')

function render(state: MascotState, lang: 'en' | 'fi' = 'en', size?: number) {
  return renderToStaticMarkup(createElement(SenttiMascot, { state, lang, level: 0.8, size }))
}

/** The `{ ... }` body that starts at the first `{` after `from`. */
function block(source: string, from: number): { start: number; end: number } {
  const open = source.indexOf('{', from)
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++
    if (source[i] === '}' && --depth === 0) return { start: from, end: i + 1 }
  }
  throw new Error('unbalanced CSS')
}

describe('SenttiMascot (#798)', () => {
  it.each(MASCOT_STATES)('%s: one inline 160 px drawing, hidden from screen readers, with no style or id', (state) => {
    const html = render(state)
    expect(html).toMatch(/^<div class="sentti-mascot /)
    expect(html.match(/<svg/g)).toHaveLength(1)
    expect(html).toContain('viewBox="0 0 160 160"')
    expect(html).toContain('width="160" height="160"')
    expect(html).toContain('aria-hidden="true" focusable="false"')
    expect(html).toContain(`data-state="${state}"`)
    // The CSP allows no style attribute; ids would clash between several mascots on a page.
    expect(html).not.toContain('style=')
    expect(html).not.toMatch(/\sid=/)
    // The mouth starts shut; only the speaking loop opens it, in the browser.
    expect(html).toContain('<ellipse class="mascot-mouth" cx="80" cy="82.5" rx="3.6" ry="0"')
    // The groups the CSS poses: ring, ears, eyes, pupils, dots, and the rest and cheer poses.
    for (const part of ['mascot-ring', 'mascot-cat', 'mascot-ear-l', 'mascot-ear-r', 'mascot-eyes', 'mascot-pupils', 'mascot-dots', 'mascot-rest', 'mascot-cheer']) {
      expect(html).toContain(`class="${part}"`)
    }
  })

  it('every state draws the same cat; only data-state and the text differ, so reduced motion shows the neutral pose', () => {
    const drawing = (state: MascotState) =>
      render(state)
        .replace(/ data-state="[a-z]+"/, '')
        .replace(/<p [^>]*>[^<]*<\/p>/, '')
    const idle = drawing('idle')
    for (const state of MASCOT_STATES) expect(drawing(state)).toBe(idle)
  })

  it('a size sets the drawing only, as width and height attributes', () => {
    expect(render('idle', 'en', 96)).toContain('width="96" height="96"')
  })

  it('getLevel (#893) changes nothing in the markup: the mouth starts shut and only the browser loop polls it', () => {
    let calls = 0
    const getLevel = () => {
      calls++
      return 1
    }
    const html = renderToStaticMarkup(createElement(SenttiMascot, { state: 'speaking', lang: 'en', getLevel }))
    expect(html).toBe(renderToStaticMarkup(createElement(SenttiMascot, { state: 'speaking', lang: 'en' })))
    expect(calls).toBe(0)
  })

  it('stateText={false} (#893) leaves out the reduced-motion text, for a parent whose caption says it', () => {
    for (const state of MASCOT_STATES) {
      const html = renderToStaticMarkup(createElement(SenttiMascot, { state, lang: 'fi', stateText: false }))
      expect(html).not.toMatch(/<p[\s>]/)
      expect(html).toContain(`data-state="${state}"`)
    }
  })

  it('under reduced motion the state shows as text, in EN and FI; idle and celebrate have none', () => {
    const text = (state: MascotState, lang: 'en' | 'fi') => /<p ([^>]*)>([^<]*)<\/p>/.exec(render(state, lang))
    expect(text('listening', 'en')?.[2]).toBe('Listening…')
    expect(text('thinking', 'en')?.[2]).toBe('Thinking…')
    expect(text('speaking', 'en')?.[2]).toBe('Speaking…')
    expect(text('listening', 'fi')?.[2]).toBe('Kuuntelen…')
    expect(text('thinking', 'fi')?.[2]).toBe('Mietin…')
    expect(text('speaking', 'fi')?.[2]).toBe('Puhun…')
    // Shown only under reduced motion, and not read twice: the voice mode's caption is the status.
    const attributes = text('listening', 'en')?.[1] ?? ''
    expect(attributes).toContain('aria-hidden="true"')
    expect(attributes).toMatch(/class="hidden .*motion-reduce:block/)
    expect(attributes).toContain('text-base')
    expect(attributes).not.toContain('role=')
    expect(attributes).not.toContain('aria-live')
    for (const lang of ['en', 'fi'] as const) {
      expect(text('idle', lang)).toBeNull()
      expect(text('celebrate', lang)).toBeNull()
    }
  })
})

describe('mascotStateLabel', () => {
  it('names the three talking states in EN and FI, and nothing for idle and celebrate', () => {
    expect(MASCOT_STATES.map((state) => mascotStateLabel(state, 'en'))).toEqual(['', 'Listening…', 'Thinking…', 'Speaking…', ''])
    expect(MASCOT_STATES.map((state) => mascotStateLabel(state, 'fi'))).toEqual(['', 'Kuuntelen…', 'Mietin…', 'Puhun…', ''])
  })
})

describe('the mascot CSS', () => {
  const start = css.indexOf("/* Sentti's mascot (#798")
  const end = css.indexOf('@keyframes mascot-', start)
  const rules = css.slice(start, end)
  const media = rules.indexOf('@media (prefers-reduced-motion: no-preference)')
  const motion = block(rules, media)
  const outside = rules.slice(0, motion.start) + rules.slice(motion.end)

  it('moves nothing outside prefers-reduced-motion: no-preference', () => {
    expect(start).toBeGreaterThan(-1)
    expect(media).toBeGreaterThan(-1)
    expect(outside).not.toMatch(/animation|transition|transform/)
    expect(rules.slice(motion.start, motion.end)).toMatch(/animation: mascot-blink/)
  })

  it('hides the ring, the dots and the celebrate pose by default, so reduced motion is the still neutral cat', () => {
    expect(outside).toMatch(/\.mascot-ring,\s*\.sentti-mascot \.mascot-cheer,\s*\.sentti-mascot \.mascot-dots \{\s*display: none;/)
  })

  it('every mascot keyframe is used only inside the no-preference block', () => {
    const names = [...css.matchAll(/@keyframes (mascot-[a-z]+)/g)].map((match) => match[1])
    expect(names.sort()).toEqual(['mascot-blink', 'mascot-cheer', 'mascot-pop', 'mascot-pulse', 'mascot-rest'])
    const elsewhere = css.slice(0, start + motion.start) + css.slice(start + motion.end)
    for (const name of names) expect(elsewhere).not.toMatch(new RegExp(`animation:[^;]*\\b${name}\\b`))
  })
})
