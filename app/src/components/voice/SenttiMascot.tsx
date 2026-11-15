// Sentti's mascot (#798), our own drawing: the cat with the coin, for the voice mode (#811).
// All motion is CSS in index.css inside `prefers-reduced-motion: no-preference`, keyed on the svg's
// `data-state`; the only script is the speaking mouth, which sets one SVG attribute per frame
// (an attribute, not a style, so the app's CSP allows it) and never re-renders React.
import { useEffect, useRef } from 'react'
import type { Language } from '../../api/types.ts'
import { usePrefersReducedMotion } from '../../lib/motion.ts'
import { mouthRy, smoothLevel } from './mascotLevel.ts'
import { mascotStateLabel, type MascotState } from './mascotStrings.ts'

interface Props {
  state: MascotState
  /** The voice's loudness now, 0 to 1 (see `levelFromAnalyser`); opens the mouth while speaking. */
  level?: number
  /** Width and height in px (160 by default). */
  size?: number
  lang: Language
}

const FUR = '#004628'
const FACE = '#EBF7EC'
const MINT = '#91FA9B'
const BRAND = '#007841'
const TEAL = '#006E87'
const RIM = '#885600'
const GOLD = '#F6C452'
const GLINT = '#FFE3A3'

/** The coin's face, the same at any place and size; `r` is the outer radius. */
function Coin({ cx, cy, r }: { cx: number; cy: number; r: number }) {
  return (
    <g>
      <circle cx={cx} cy={cy} r={r} fill={GOLD} stroke={RIM} strokeWidth="3" />
      <circle cx={cx} cy={cy} r={r - 5} fill="none" stroke={RIM} strokeWidth="1.4" opacity=".55" />
      <path d={`M${cx + 5.5} ${cy - 6.2} a8 8 0 1 0 0 12.4`} fill="none" stroke={RIM} strokeWidth="2.6" strokeLinecap="round" />
      <path d={`M${cx - 8} ${cy - 2} h9 M${cx - 8} ${cy + 2.6} h9`} stroke={RIM} strokeWidth="2.2" strokeLinecap="round" />
      <path d={`M${cx - r + 6} ${cy - 6} a${r - 3} ${r - 3} 0 0 1 7 -7`} fill="none" stroke={GLINT} strokeWidth="2.4" strokeLinecap="round" />
    </g>
  )
}

/** A paw: an oval in the face colour with a fur outline. */
function Paw({ cx, cy, angle }: { cx: number; cy: number; angle: number }) {
  return <ellipse cx={cx} cy={cy} rx="7.5" ry="6.5" transform={`rotate(${angle} ${cx} ${cy})`} fill={FACE} stroke={FUR} strokeWidth="2" />
}

/**
 * Sentti's mascot in one of five states: `idle` blinks slowly, `listening` lifts the ears inside a
 * soft pulsing ring, `thinking` looks up beside three dots, `speaking` opens the mouth with `level`,
 * and `celebrate` throws the coin with both arms up for about 1.2 s, then rests.
 *
 * Under reduced motion the cat is the still neutral pose and the state shows as text below it
 * (`mascotStateLabel`). The drawing is hidden from screen readers, and so is that text: the voice
 * mode's own status caption is what they read.
 */
export function SenttiMascot({ state, level = 0, size = 160, lang }: Props) {
  const reduced = usePrefersReducedMotion()
  const mouth = useRef<SVGEllipseElement>(null)
  // The loop reads the newest level from a ref, so a new level never restarts it or re-renders.
  const latest = useRef(level)
  useEffect(() => {
    latest.current = level
  }, [level])

  const talking = state === 'speaking' && !reduced
  useEffect(() => {
    const el = mouth.current
    if (!talking || !el) return
    let smoothed = 0
    let shown = '0'
    let frame = 0
    const step = () => {
      smoothed = smoothLevel(smoothed, latest.current)
      const ry = String(mouthRy(smoothed))
      if (ry !== shown) {
        el.setAttribute('ry', ry)
        shown = ry
      }
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => {
      cancelAnimationFrame(frame)
      el.setAttribute('ry', '0')
    }
  }, [talking])

  const label = mascotStateLabel(state, lang)
  return (
    <div className="sentti-mascot inline-flex flex-col items-center gap-1">
      <svg
        viewBox="0 0 160 160"
        width={size}
        height={size}
        aria-hidden="true"
        focusable="false"
        data-state={state}
        className="block shrink-0"
      >
        {/* Listening: a soft ring pulses behind the cat. */}
        <circle className="mascot-ring" cx="80" cy="80" r="70" fill="none" stroke={BRAND} strokeWidth="4" />
        <g className="mascot-cat">
          <path d="M110 146 C140 146 146 120 132 104 C126 97 118 100 121 108" fill="none" stroke={FUR} strokeWidth="11" strokeLinecap="round" />
          <path d="M46 150 C38 114 52 90 80 90 C108 90 122 114 114 150 Z" fill={FUR} />
          <ellipse cx="80" cy="126" rx="21" ry="22" fill={FACE} />
          <ellipse cx="62" cy="150" rx="12" ry="6" fill={FACE} />
          <ellipse cx="98" cy="150" rx="12" ry="6" fill={FACE} />
          {/* Celebrate: confetti, behind the head. */}
          <g className="mascot-cheer">
            <rect x="14" y="30" width="5" height="9" rx="2" transform="rotate(-30 14 30)" fill={MINT} />
            <rect x="150" y="96" width="5" height="9" rx="2" transform="rotate(25 150 96)" fill={GOLD} />
            <rect x="22" y="96" width="5" height="9" rx="2" transform="rotate(15 22 96)" fill={TEAL} />
            <rect x="142" y="128" width="5" height="9" rx="2" transform="rotate(-20 142 128)" fill={MINT} />
            <rect x="10" y="62" width="5" height="9" rx="2" transform="rotate(40 10 62)" fill={GOLD} />
            <rect x="96" y="8" width="5" height="9" rx="2" transform="rotate(-35 96 8)" fill={TEAL} />
          </g>
          {/* At rest: both arms hold the coin. */}
          <g className="mascot-rest">
            <path d="M56 104 Q60 118 64 114" fill="none" stroke={FUR} strokeWidth="12" strokeLinecap="round" />
            <path d="M104 104 Q100 118 96 114" fill="none" stroke={FUR} strokeWidth="12" strokeLinecap="round" />
            <Coin cx={80} cy={116} r={17} />
            <Paw cx={63} cy={115} angle={-20} />
            <Paw cx={97} cy={115} angle={20} />
          </g>
          <g className="mascot-head">
            <g className="mascot-ear-l">
              <path d="M44 52 L49 16 L72 36 Z" fill={FUR} stroke={FUR} strokeWidth="4" strokeLinejoin="round" />
              <path d="M52 40 L54 25 L64 35 Z" fill={MINT} stroke={MINT} strokeWidth="2" strokeLinejoin="round" />
            </g>
            <g className="mascot-ear-r">
              <path d="M116 52 L111 16 L88 36 Z" fill={FUR} stroke={FUR} strokeWidth="4" strokeLinejoin="round" />
              <path d="M108 40 L106 25 L96 35 Z" fill={MINT} stroke={MINT} strokeWidth="2" strokeLinejoin="round" />
            </g>
            <ellipse cx="80" cy="62" rx="41" ry="34" fill={FUR} />
            <ellipse cx="80" cy="77" rx="18" ry="12.5" fill={FACE} />
            <g className="mascot-rest">
              <g className="mascot-eyes">
                <ellipse cx="64" cy="60" rx="7.2" ry="8.4" fill={FACE} />
                <ellipse cx="96" cy="60" rx="7.2" ry="8.4" fill={FACE} />
                <g className="mascot-pupils">
                  <ellipse cx="64.5" cy="61" rx="3.8" ry="5.4" fill={FUR} />
                  <ellipse cx="96.5" cy="61" rx="3.8" ry="5.4" fill={FUR} />
                  <circle cx="66" cy="58.6" r="1.5" fill="#FFFFFF" />
                  <circle cx="98" cy="58.6" r="1.5" fill="#FFFFFF" />
                </g>
              </g>
            </g>
            {/* Celebrate: happy closed eyes. */}
            <g className="mascot-cheer">
              <path d="M57 62 q7 -9 14 0" fill="none" stroke={FACE} strokeWidth="3.6" strokeLinecap="round" />
              <path d="M89 62 q7 -9 14 0" fill="none" stroke={FACE} strokeWidth="3.6" strokeLinecap="round" />
            </g>
            <path d="M76.2 71.2 h7.6 q1.4 0 .5 1.2 l-3.2 3.6 q-.9 1 -1.8 0 l-3.2 -3.6 q-.9 -1.2 .1 -1.2 z" fill={FUR} />
            {/* Speaking: the open mouth, under the lip; its ry follows the level (0 is shut). */}
            <ellipse ref={mouth} className="mascot-mouth" cx="80" cy="82.5" rx="3.6" ry="0" fill={FUR} />
            <path className="mascot-rest" d="M74 80 q3 3.6 6 0 q3 3.6 6 0" fill="none" stroke={FUR} strokeWidth="1.9" strokeLinecap="round" />
            <path className="mascot-cheer" d="M74 79 q6 8 12 0 z" fill={FUR} />
            <path d="M60 76 l-14 -2 M60 80 l-13 3 M100 76 l14 -2 M100 80 l13 3" stroke={FACE} strokeWidth="1.6" strokeLinecap="round" opacity=".85" />
          </g>
          {/* Celebrate: arms up, the coin thrown high, two motion lines. */}
          <g className="mascot-cheer">
            <path d="M54 98 Q44 102 34 66" fill="none" stroke={FUR} strokeWidth="12" strokeLinecap="round" />
            <path d="M106 98 Q116 102 126 66" fill="none" stroke={FUR} strokeWidth="12" strokeLinecap="round" />
            <Paw cx={32} cy={60} angle={-25} />
            <Paw cx={128} cy={60} angle={25} />
            <path d="M118 34 q8 -10 18 -6 M112 26 q4 -10 14 -10" fill="none" stroke={BRAND} strokeWidth="2" strokeLinecap="round" opacity=".7" />
            <Coin cx={140} cy={20} r={12} />
          </g>
        </g>
        {/* Thinking: three dots beside the head. */}
        <g className="mascot-dots" fill={BRAND}>
          <circle cx="130" cy="26" r="3.4" />
          <circle cx="141" cy="26" r="3.4" />
          <circle cx="152" cy="26" r="3.4" />
        </g>
      </svg>
      {label ? (
        <p aria-hidden="true" className="hidden text-center text-base font-semibold [overflow-wrap:anywhere] motion-reduce:block">
          {label}
        </p>
      ) : null}
    </div>
  )
}
