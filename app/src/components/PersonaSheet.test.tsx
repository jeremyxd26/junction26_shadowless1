import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Persona } from '../api/types.ts'
import { strings } from '../lib/i18n.ts'
import { SettingsContext } from '../lib/settings.ts'
import { PersonaSheet } from './PersonaSheet.tsx'

const SANNA: Persona = {
  customer_id: 'CUST00860',
  display_name: 'Sanna',
  age: 35,
  age_band: '35-44',
  postal_area: { code: '00590', label: 'Helsinki 00590' },
  profile: { key: 'big_ticket', label: 'Big ticket' },
  tagline: 'A large home and tech purchase in late September, on top of regular bills.',
  default_language: 'en',
}

function sheet(lang: 'en' | 'fi') {
  return renderToStaticMarkup(
    <SettingsContext.Provider value={{ lang, customerId: 'CUST00860', t: strings(lang) }}>
      <PersonaSheet personas={[SANNA]} onPick={() => {}} onLanguage={() => {}} onClose={() => {}} />
    </SettingsContext.Provider>,
  )
}

describe('the demo persona picker says who is who (#872)', () => {
  it('shows the age and the age band under the name, in English and Finnish', () => {
    expect(sheet('en')).toContain('35 years · age group 35–44')
    expect(sheet('fi')).toContain('35 vuotta · ikäryhmä 35–44')
  })

  it('never shows the postal code or the customer id', () => {
    const html = sheet('en')
    expect(html).not.toContain('00590')
    expect(html).not.toContain('CUST00860')
  })
})
