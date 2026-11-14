import { describe, expect, it } from 'vitest'
import { voiceFor } from './speech.ts'

const voice = (lang: string, name = lang) => ({ lang, name }) as unknown as SpeechSynthesisVoice

describe('voiceFor', () => {
  it('prefers fi-FI for Finnish', () => {
    expect(voiceFor([voice('en-GB'), voice('fi-FI', 'Satu')], 'fi')?.name).toBe('Satu')
  })

  it('prefers en-GB, then en-US, for English', () => {
    expect(voiceFor([voice('en-US', 'Samantha'), voice('en-GB', 'Daniel')], 'en')?.name).toBe('Daniel')
    expect(voiceFor([voice('fi-FI'), voice('en-US', 'Samantha')], 'en')?.name).toBe('Samantha')
  })

  it('takes another regional voice of the language', () => {
    expect(voiceFor([voice('en-AU', 'Karen')], 'en')?.name).toBe('Karen')
    expect(voiceFor([voice('fi_FI', 'Android FI')], 'fi')?.name).toBe('Android FI')
  })

  it('returns null without a voice for the language, so no button is shown', () => {
    expect(voiceFor([voice('en-GB'), voice('sv-SE')], 'fi')).toBeNull()
    expect(voiceFor([], 'en')).toBeNull()
  })
})
