import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { speak, speakingNow, stopSpeaking, voiceFor } from './speech.ts'

const voice = (lang: string, name = lang, localService = true) => ({ lang, name, localService }) as unknown as SpeechSynthesisVoice

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

  it('skips a remote en-GB voice for a local en-US one', () => {
    const voices = [voice('en-GB', 'Google UK English Female', false), voice('en-US', 'Microsoft David')]
    expect(voiceFor(voices, 'en')?.name).toBe('Microsoft David')
  })

  it('returns null when the only Finnish voice is remote', () => {
    expect(voiceFor([voice('fi-FI', 'Microsoft Noora Online (Natural)', false), voice('en-US')], 'fi')).toBeNull()
  })
})

/** A speechSynthesis that only records: `end` and `error` fire when the test says so. */
class FakeUtterance {
  voice: SpeechSynthesisVoice | null = null
  lang = ''
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(readonly text: string) {}
}

describe('speak and stopSpeaking', () => {
  const spoken: FakeUtterance[] = []
  const en = voice('en-GB', 'Daniel')

  beforeEach(() => {
    spoken.length = 0
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
    vi.stubGlobal('window', { speechSynthesis: { cancel: () => {}, speak: (u: FakeUtterance) => spoken.push(u) } })
  })
  afterEach(() => {
    stopSpeaking()
    vi.unstubAllGlobals()
  })

  it('keeps the state when a stopped utterance ends late after a quick second tap', () => {
    speak('3', 'Safe to spend is €138.79.', en)
    stopSpeaking('3')
    speak('3', 'Safe to spend is €138.79.', en)
    expect(speakingNow()).toBe('3')
    spoken[0].onerror?.() // the cancelled first utterance reports "interrupted" only now
    expect(speakingNow()).toBe('3')
    spoken[1].onend?.()
    expect(speakingNow()).toBeNull()
  })

  it('keeps the newer answer speaking when the older one ends late', () => {
    speak('1', 'First answer.', en)
    speak('2', 'Second answer.', en)
    spoken[0].onend?.()
    expect(speakingNow()).toBe('2')
  })

  it('stops any answer when called without an id, as the chat does for a new question', () => {
    speak('1', 'An older answer.', en)
    stopSpeaking()
    expect(speakingNow()).toBeNull()
    spoken[0].onend?.()
    expect(speakingNow()).toBeNull()
  })
})
