import { useEffect, useState, type RefObject } from 'react'
import { chatStrings } from '../lib/chatStrings.ts'
import { prefersReducedMotion } from '../lib/motion.ts'
import { buttonLift, isAway } from '../lib/scrollAway.ts'
import { useSettings } from '../lib/settings.ts'

function measure(): boolean {
  return isAway(window.scrollY, window.innerHeight, document.documentElement.scrollHeight)
}

/**
 * A round button above the composer, while the customer is scrolled up from the latest message.
 * While an answer streams it shows three dots bouncing one after another; otherwise a down arrow.
 * A tap brings the thread to its end (smooth, or at once under reduced motion). It sits on the
 * composer's measured top (#762), so a taller composer (200 % text, the length note, a new layout)
 * or the mic's status line above it never covers it, and it paints above the composer.
 */
export function ScrollToLatest({ thinking, enabled, composer }: { thinking: boolean; enabled: boolean; composer: RefObject<HTMLElement | null> }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const [away, setAway] = useState(false)
  const [lift, setLift] = useState<number | null>(null)

  useEffect(() => {
    const form = composer.current
    if (!enabled || !form) return
    let frame = 0
    const place = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() =>
        setLift(buttonLift(window.innerHeight, form.getBoundingClientRect().top, [...form.querySelectorAll('*')].map((el) => el.getBoundingClientRect()))),
      )
    }
    place()
    // The composer grows with the text size and the length note; the mic's line appears above it.
    const resize = new ResizeObserver(place)
    resize.observe(form)
    const changes = new MutationObserver(place)
    changes.observe(form, { childList: true, subtree: true, characterData: true })
    window.addEventListener('resize', place)
    window.visualViewport?.addEventListener('resize', place)
    return () => {
      cancelAnimationFrame(frame)
      resize.disconnect()
      changes.disconnect()
      window.removeEventListener('resize', place)
      window.visualViewport?.removeEventListener('resize', place)
    }
  }, [composer, enabled])

  useEffect(() => {
    if (!enabled) return
    let frame = 0
    const check = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setAway(measure()))
    }
    check()
    window.addEventListener('scroll', check, { passive: true })
    window.addEventListener('resize', check)
    // The thread grows while an answer streams in: the bottom moves away without a scroll.
    const observer = new ResizeObserver(check)
    observer.observe(document.body)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', check)
      window.removeEventListener('resize', check)
      observer.disconnect()
    }
  }, [enabled])

  if (!enabled || !away) return null
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+84px)] z-[35] mx-auto flex max-w-[480px] justify-center px-4"
      style={lift === null ? undefined : { bottom: lift }}
    >
      <button
        type="button"
        aria-label={s.toLatest}
        onClick={() =>
          window.scrollTo({ top: document.documentElement.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
        }
        className="motion-fade pointer-events-auto inline-flex size-11 items-center justify-center rounded-pill border border-line bg-surface text-brand shadow-float hover:bg-sunken"
      >
        {thinking ? (
          <span aria-hidden="true" className="flex items-center gap-[3px]">
            {[0, 150, 300].map((delay) => (
              <span key={delay} className="dot-bounce size-[6px] rounded-pill bg-brand" style={{ animationDelay: `${delay}ms` }} />
            ))}
          </span>
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5.5 12.5L12 19l6.5-6.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>
    </div>
  )
}
