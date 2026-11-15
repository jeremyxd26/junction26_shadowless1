// The header in one row (Renat's light redesign, step 3): the profile icon opens the menu, Chat | Learn in the
// middle, the new-chat pencil on the right; the overview and How Sentti works live in the menu.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { strings } from '../lib/i18n.ts'
import { SettingsContext } from '../lib/settings.ts'

// Server rendering needs a server snapshot for the URL store; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

vi.stubGlobal('window', {
  location: { search: '', pathname: '/', href: 'http://localhost/', origin: 'http://localhost' },
  history: { length: 1, state: null },
  addEventListener: () => {},
  removeEventListener: () => {},
  matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
})

async function render(lang: 'en' | 'fi') {
  const { Header } = await import('./Header.tsx')
  return renderToStaticMarkup(
    createElement(
      SettingsContext,
      { value: { lang, customerId: 'CUST00860', t: strings(lang) } },
      createElement(Header, { onLongPress: () => {}, disclosure: 'AI', overviewReady: true, onNewChat: () => {}, tab: 'chat', onTab: () => {} }),
    ),
  )
}

describe('the header in one row (#853)', () => {
  it('has the menu, the tabs and the pencil in one grid row, a hidden title and no overview button of its own', async () => {
    const html = await render('en')
    const row = html.slice(html.indexOf('<div class="grid'), html.indexOf('</header>'))
    expect(row).toContain('aria-label="Menu"')
    expect(row).toContain('role="tablist"')
    expect(row).toContain('aria-label="New chat"')
    expect(html.indexOf('aria-label="Menu"')).toBeLessThan(html.indexOf('role="tablist"'))
    expect(html.indexOf('role="tablist"')).toBeLessThan(html.indexOf('aria-label="New chat"'))
    expect(html).toContain('<h1 class="sr-only">Sentti</h1>')
    expect(html).not.toContain('aria-label="Overview"')
    expect(html.match(/role="tablist"/g)).toHaveLength(1)
  })

  it('names the menu in Finnish', async () => {
    expect(await render('fi')).toContain('aria-label="Valikko"')
  })
})
