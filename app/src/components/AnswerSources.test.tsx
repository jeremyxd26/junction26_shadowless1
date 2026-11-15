// The sources of a knowledge answer as chips (#922).
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { shownSources } from '../lib/answerSources.ts'
import { strings } from '../lib/i18n.ts'
import { SettingsContext } from '../lib/settings.ts'
import { AnswerSources } from './AnswerSources.tsx'

const MARTAT = { publisher: 'Marttaliitto', title: 'Säästäminen', url: 'https://www.martat.fi/omat-rahat/saastaminen/', lang: 'fi' }
const INFO = { publisher: 'InfoFinland.fi', title: 'Cost of living in Finland', url: 'https://infofinland.fi/en/cost-of-living', lang: 'en' }

function render(sources: unknown, lang: 'en' | 'fi' = 'en') {
  return renderToStaticMarkup(
    createElement(SettingsContext, { value: { lang, customerId: 'CUST00860', t: strings(lang) } }, createElement(AnswerSources, { sources })),
  )
}

describe('answer sources (#922)', () => {
  it('keeps well-formed https sources, deduplicated, at most three, in order', () => {
    const list = shownSources([
      MARTAT,
      { ...MARTAT },
      { publisher: 'Bad', title: 'x', url: 'http://insecure.example' },
      { title: 'no publisher', url: 'https://a.example' },
      INFO,
      { publisher: 'Three', title: 't', url: 'https://three.example' },
      { publisher: 'Four', title: 't', url: 'https://four.example' },
    ])
    expect(list.map((s) => s.publisher)).toEqual(['Marttaliitto', 'InfoFinland.fi', 'Three'])
    expect(shownSources(undefined)).toEqual([])
    expect(shownSources('https://x.example')).toEqual([])
  })

  it('renders a labelled list of mint pill links that open in a new tab, named "Source: publisher — title"', () => {
    const html = render([MARTAT, INFO])
    expect(html).toContain('aria-label="Sources"')
    expect(html).toContain('>Sources</p>')
    expect(html.match(/<a /g)).toHaveLength(2)
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('aria-label="Source: Marttaliitto — Säästäminen"')
    expect(html).toContain(`href="${MARTAT.url}"`)
    expect(html.match(/min-h-11[^"]*rounded-pill[^"]*bg-mint-tint/g)).toHaveLength(2)
    expect(html).toContain('truncate') // a long title is cut, the publisher stays whole
    expect(html).toContain('flex-wrap')
  })

  it('shows nothing without sources, and Finnish words in Finnish', () => {
    expect(render([])).toBe('')
    expect(render(undefined)).toBe('')
    const fi = render([MARTAT], 'fi')
    expect(fi).toContain('>Lähteet</p>')
    expect(fi).toContain('aria-label="Lähde: Marttaliitto — Säästäminen"')
  })
})
