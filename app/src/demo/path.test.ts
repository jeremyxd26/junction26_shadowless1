import { describe, expect, it } from 'vitest'
import { moduleHref, safePath } from './path.ts'

const ORIGIN = 'https://sentti.example'

describe('safePath', () => {
  it('keeps a same-origin path', () => {
    expect(safePath('/cards', ORIGIN)).toBe('/cards')
    expect(safePath('/chat?q=hi', ORIGIN)).toBe('/chat?q=hi')
  })

  it('falls back to / when there is no value', () => {
    expect(safePath(null, ORIGIN)).toBe('/')
    expect(safePath('', ORIGIN)).toBe('/')
  })

  it('refuses a protocol-relative URL to another host', () => {
    expect(safePath('//evil.example/x', ORIGIN)).toBe('/')
  })

  it('refuses a tab or newline that the URL parser drops', () => {
    expect(safePath('/\t/evil.example', ORIGIN)).toBe('/')
    expect(safePath('/\n/evil.example', ORIGIN)).toBe('/')
    expect(safePath('/\\evil.example', ORIGIN)).toBe('/')
  })

  it('keeps an encoded tab as a plain same-origin path', () => {
    expect(safePath('/%09/evil', ORIGIN)).toBe('/%09/evil')
  })

  it('refuses other schemes and absolute URLs', () => {
    expect(safePath('javascript:alert(1)', ORIGIN)).toBe('/')
    expect(safePath('data:text/html,hi', ORIGIN)).toBe('/')
    expect(safePath('https://evil.example/', ORIGIN)).toBe('/')
  })
})

describe('moduleHref', () => {
  it('adds the language and the persona to the path', () => {
    expect(moduleHref('/', ORIGIN, 'en', 'CUST00860')).toBe('/?lang=en&persona=CUST00860')
    expect(moduleHref('/cards', ORIGIN, 'fi', '')).toBe('/cards?lang=fi')
  })

  it('merges with a query already on the path', () => {
    expect(moduleHref('/chat?q=hi', ORIGIN, 'en', '')).toBe('/chat?q=hi&lang=en')
  })

  it('uses / for a path that leaves the origin', () => {
    expect(moduleHref('//evil.example', ORIGIN, 'en', '')).toBe('/?lang=en')
  })
})
