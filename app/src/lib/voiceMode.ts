// Voice mode (#811): a spoken conversation on top of POST /api/stt and POST /api/tts. What is sent, and when:
// - Only after a tap on the wave button: the app listens through the microphone. A round ends about 1.2 s
//   after the user stops talking, or at 15 s. A round in which no speech was heard sends nothing.
// - The clip goes to the core (POST /api/stt) exactly as the composer mic sends it (stt.ts); the words are then
//   sent as a normal question (POST /api/ask) without a tap on send, and appear in the thread as typed ones do.
// - The answer is read aloud as the speaker button reads it (speech.ts): the Gemini voice by the answer's id,
//   the device voice when the voice budget is low or the request fails. Nothing is recorded while it speaks.
// - No audio is stored: each clip stays in memory for its one request. The wave reads only the level.
// Pure helpers here, so the tests share them; the overlay is components/VoiceMode.tsx.
import type { Language } from '../api/types.ts'
import { MAX_RECORD_MS, STT_LIVE, canRecord } from './stt.ts'
import type { Turn } from './thread.ts'

/** A round ends this long after the speech stopped. */
export const SILENCE_MS = 1200
/** A round ends by itself after this long, heard or not (the core takes 15 s clips at most). */
export const LISTEN_MS = MAX_RECORD_MS
/** Speech counts once the level has been above SPEECH_LEVEL this long in all, so a one-word answer ("Yes",
 * "Ei") counts, dips inside the word included; a click does not. */
export const ONSET_MS = 150
/** Before speech counts, this long below QUIET_LEVEL forgets the loud bits heard so far (stray noises). */
export const ONSET_RESET_MS = 600
/** One reading never counts for more than this, so a late timer does not turn one loud reading into speech. */
const MAX_STEP_MS = 100
/** Levels on the scale of stt.ts levelOf (0 to 1): speech starts above SPEECH_LEVEL, silence is below QUIET_LEVEL. */
export const SPEECH_LEVEL = 0.14
export const QUIET_LEVEL = 0.07
/** Transcriptions with no words in a row before the mode closes (each one spent a model request). A round in which
 * the meter heard no speech sends nothing and costs nothing, so it never counts here. */
export const MAX_EMPTY_ROUNDS = 3
/** With no speech heard for this long the mode closes, so it never keeps listening in the background. */
export const SILENT_CLOSE_MS = 60_000
/** The room's own level raises both thresholds: speech must be this many times the noise floor, silence below that
 * many times it, so a round still ends 1.2 s after the words in a noisy room. */
const SPEECH_OVER_FLOOR = 2.5
const QUIET_OVER_FLOOR = 1.6

/** Barge-in: while Sentti speaks, the user's voice must be this loud (higher than normal speech, so Sentti's own
 * voice leaking into the microphone does not count), for this long, and not in the first moment of playback. */
export const BARGE_LEVEL = 0.32
export const BARGE_MS = 300
export const BARGE_GRACE_MS = 600

/** Whether this build and browser can offer voice mode: a live build with a microphone API and a persona. */
export function voiceModeAvailable(customerId: string | null): boolean {
  return STT_LIVE && Boolean(customerId) && canRecord()
}

/** Where a listening round is: `waiting` for speech, `speech` heard, `end` (send it), `nothing` (send nothing). */
export type RoundState = 'waiting' | 'speech' | 'end' | 'nothing'

export interface Endpointer {
  /** One level reading at time `now` (ms); returns where the round is. */
  push(level: number, now: number): RoundState
  /** Whether speech was heard in this round. */
  heard(): boolean
}

/**
 * Decides when a listening round ends: after ONSET_MS above the speech level in all the round has speech; after
 * that, SILENCE_MS below the quiet level ends it. At LISTEN_MS it ends anyway: `end` with speech, `nothing` without.
 * Both levels rise with the room's noise floor (measured before the speech), never below SPEECH_LEVEL and
 * QUIET_LEVEL. `heard`: the round starts with speech already going (a barge-in, #895).
 */
export function endpointer(start: number, options: { heard?: boolean } = {}): Endpointer {
  let last: number | null = null
  let loudMs = 0
  let calmSince: number | null = null
  let quietSince: number | null = null
  let heard = options.heard === true
  let floor: number | null = null
  let finished: RoundState | null = null
  return {
    heard: () => heard,
    push(level, now) {
      if (finished) return finished
      const step = last === null ? 0 : Math.min(MAX_STEP_MS, Math.max(0, now - last))
      last = now
      const speech = Math.max(SPEECH_LEVEL, (floor ?? 0) * SPEECH_OVER_FLOOR)
      const quiet = Math.max(QUIET_LEVEL, (floor ?? 0) * QUIET_OVER_FLOOR)
      if (!heard) {
        // The noise floor follows the room while nobody speaks (about the last second).
        if (level < speech) floor = floor === null ? level : floor * 0.95 + level * 0.05
        if (level >= speech) {
          loudMs += step
          calmSince = null
          if (loudMs >= ONSET_MS) heard = true
        } else if (level < quiet) {
          calmSince ??= now
          if (now - calmSince >= ONSET_RESET_MS) loudMs = 0
        }
      } else if (level < quiet) {
        quietSince ??= now
        if (now - quietSince >= SILENCE_MS) finished = 'end'
      } else {
        quietSince = null
      }
      if (!finished && now - start >= LISTEN_MS) finished = heard ? 'end' : 'nothing'
      return finished ?? (heard ? 'speech' : 'waiting')
    },
  }
}

/**
 * Barge-in while Sentti speaks (#895): true once the microphone has been above BARGE_LEVEL for BARGE_MS in all,
 * after the first BARGE_GRACE_MS of playback; quieter moments under half the level forget it.
 */
export function bargeDetector(start: number): { push(level: number, now: number): boolean } {
  let last: number | null = null
  let loudMs = 0
  return {
    push(level, now) {
      const step = last === null ? 0 : Math.min(MAX_STEP_MS, Math.max(0, now - last))
      last = now
      if (now - start < BARGE_GRACE_MS) return false
      if (level >= BARGE_LEVEL) loudMs += step
      else if (level < BARGE_LEVEL / 2) loudMs = 0
      return loudMs >= BARGE_MS
    },
  }
}

/** The reduced-motion ring's width step, 0 to 3, for a level from 0 to 1: it steps with the voice, no motion. */
export function ringStep(level: number): number {
  return level < 0.15 ? 0 : level < 0.4 ? 1 : level < 0.7 ? 2 : 3
}

/** The answer to a question voice mode sent: still coming, done (with what to read aloud), failed or stopped. */
export type Followed =
  | { state: 'waiting' }
  | { state: 'done'; id: number; text: string; answerId: string | null; language: Language | null }
  | { state: 'failed' }
  | { state: 'stopped' }

/** The first ask turn after the turn id `after` (the last id when the question was sent) and where its answer is. */
export function followAnswer(turns: Turn[], after: number): Followed {
  const turn = turns.find((candidate) => candidate.kind === 'ask' && candidate.id > after)
  if (!turn || turn.kind !== 'ask') return { state: 'waiting' }
  const { answer } = turn
  if (answer.status === 'error') return { state: 'failed' }
  if (answer.status === 'stopped') return { state: 'stopped' }
  if (answer.status !== 'done' || !answer.done) return { state: 'waiting' }
  return {
    state: 'done',
    id: turn.id,
    text: answer.done.text_rendered,
    answerId: answer.done.answer_id || null,
    language: answer.meta?.language ?? null,
  }
}

/** The wave's bar heights (0 to 1) from one frame of frequency data: speech bands in the middle, mirrored. */
export function waveBars(frequencies: ArrayLike<number>, count: number): number[] {
  const half = Math.ceil(count / 2)
  // Speech sits in the lower part of the spectrum: spread the half's bars over the lowest ~35 % of the bins.
  const span = Math.max(half, Math.floor(frequencies.length * 0.35))
  const side: number[] = []
  for (let i = 0; i < half; i++) {
    const from = Math.floor((i * span) / half)
    const to = Math.max(from + 1, Math.floor(((i + 1) * span) / half))
    let peak = 0
    for (let bin = from; bin < to && bin < frequencies.length; bin++) peak = Math.max(peak, frequencies[bin])
    side.push(Math.min(1, peak / 220))
  }
  // The lowest bands in the middle, the higher ones toward both ends; an odd count has one middle bar.
  const left = [...side].reverse()
  return count % 2 === 0 ? [...left, ...side] : [...left.slice(0, -1), ...side]
}
