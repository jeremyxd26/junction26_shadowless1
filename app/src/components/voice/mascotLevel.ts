// Sentti's mascot (#798): from an audio level to the open mouth. Pure, so it is tested without audio.

/** How far one frame moves toward a louder level (fast, so the mouth opens on each syllable)... */
const ATTACK = 0.5
/** ...and toward a quieter one (slow, so it closes softly instead of flickering). */
const RELEASE = 0.12
/** The widest open mouth: the muzzle ends at y 89.5 and the mouth sits at y 82.5. */
export const MOUTH_MAX_RY = 5
/** Below this level the mouth stays shut, so room noise does not make it twitch. */
const QUIET = 0.02
/** Speech has an RMS of about 0.05 to 0.3; this gain (the mic meter's, in lib/stt.ts) makes it fill 0..1. */
export const LEVEL_GAIN = 4

function clamp01(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0
}

/** One frame of smoothing, 0 to 1: a fast attack toward a louder `next`, a slow release toward a quieter one. */
export function smoothLevel(prev: number, next: number): number {
  const from = clamp01(prev)
  const to = clamp01(next)
  const step = from + (to - from) * (to > from ? ATTACK : RELEASE)
  return step < 0.001 ? 0 : step
}

/** The mouth ellipse's `ry` for a level, 0 (shut) to MOUTH_MAX_RY, rounded to 0.01. */
export function mouthRy(level: number): number {
  const value = clamp01(level)
  if (value < QUIET) return 0
  return Math.round(value * MOUTH_MAX_RY * 100) / 100
}

/**
 * The level the mouth follows this frame (#893): `getLevel()` when the parent gives one, polled every
 * frame so the parent never re-renders for it (the voice mode passes `() => session.level()`); else the
 * newest `level` prop.
 */
export function levelSource(getLevel: (() => number) | undefined, level: number): number {
  return getLevel ? getLevel() : level
}

/** When the next frame runs: `requestAnimationFrame` in the browser, a hand-driven queue in tests. */
export interface FrameClock {
  request(step: () => void): number
  cancel(frame: number): void
}

/**
 * The speaking mouth's loop: each frame it reads the level, smooths it and sets the mouth's `ry` only
 * when the shown value changes. Returns the stop, which cancels the next frame and shuts the mouth.
 */
export function runMouth(read: () => number, setRy: (ry: string) => void, clock: FrameClock): () => void {
  let smoothed = 0
  let shown = '0'
  let frame = 0
  const step = () => {
    smoothed = smoothLevel(smoothed, read())
    const ry = String(mouthRy(smoothed))
    if (ry !== shown) {
      setRy(ry)
      shown = ry
    }
    frame = clock.request(step)
  }
  frame = clock.request(step)
  return () => {
    clock.cancel(frame)
    setRy('0')
  }
}

/**
 * How loud the sound through an AnalyserNode is now, 0 to 1: the RMS of one frame of
 * `getByteTimeDomainData` (128 is silence) times LEVEL_GAIN, clamped. `buf` is reused between
 * frames; give it the analyser's `fftSize` as its length.
 */
export function levelFromAnalyser(
  analyser: Pick<AnalyserNode, 'getByteTimeDomainData'>,
  buf: Uint8Array<ArrayBuffer>,
): number {
  if (buf.length === 0) return 0
  analyser.getByteTimeDomainData(buf)
  let sum = 0
  for (let i = 0; i < buf.length; i++) {
    const x = (buf[i] - 128) / 128
    sum += x * x
  }
  return clamp01(Math.sqrt(sum / buf.length) * LEVEL_GAIN)
}
