import { useEffect } from 'react'
import type { Language } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'
import { speak, stopSpeaking, useSpeakingId, useVoice } from '../lib/speech.ts'
import { speechStrings } from '../lib/speechStrings.ts'

interface Props {
  /** The turn's id: one answer speaks at a time. */
  id: string
  /** `done.text_rendered`, spoken unchanged (no number tokens). */
  text: string
  /** The answer's language (`meta.language`); it picks the voice. */
  language: Language
}

/**
 * A speaker next to Sentti's answer (#252). A tap reads the answer aloud with the device's voice
 * for its language, a second tap stops; another answer, a new question (the chat stops speech for
 * every question, #438), leaving the screen or a persona switch (the turn unmounts) stops it too.
 * Nothing plays without a tap. Without speech support or without a local voice for the language,
 * nothing is rendered.
 */
export function SpeakButton({ id, text, language }: Props) {
  const { lang } = useSettings()
  const s = speechStrings(lang)
  const voice = useVoice(language)
  const speakingId = useSpeakingId()
  const speaking = speakingId === id

  useEffect(() => () => stopSpeaking(id), [id])

  if (!voice || !text) return null

  return (
    <button
      type="button"
      aria-pressed={speaking}
      aria-label={speaking ? s.stop : s.read}
      onClick={() => (speaking ? stopSpeaking(id) : speak(id, text, voice))}
      className={`inline-flex size-11 shrink-0 items-center justify-center rounded-pill border transition-colors duration-(--duration-fast) ${
        speaking ? 'border-brand bg-mint-tint text-brand' : 'border-transparent text-brand hover:bg-sunken'
      }`}
    >
      {speaking ? (
        // Stop square while speaking, so the state is visible, not only announced.
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="currentColor">
          <rect x="7" y="7" width="10" height="10" rx="1.5" />
        </svg>
      ) : (
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 10v4h4l5 4V6L8 10H4z" strokeLinejoin="round" />
          <path d="M16.5 8.5a5 5 0 010 7M19 6a8.5 8.5 0 010 12" strokeLinecap="round" />
        </svg>
      )}
    </button>
  )
}
