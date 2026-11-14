import { useEffect, useState } from 'react'
import { chatStrings } from '../lib/chatStrings.ts'
import { prefersReducedMotion } from '../lib/motion.ts'
import { isAway } from '../lib/scrollAway.ts'
import { useSettings } from '../lib/settings.ts'

function measure(): boolean {
  return isAway(window.scrollY, window.innerHeight, document.documentElement.scrollHeight)
}

/**
 * A round button above the composer, at the bottom right, while the customer is scrolled up from the
 * latest message. While an answer streams it shows three dots bouncing one after another; otherwise a
 * down arrow. A tap brings the thread to its end (smooth, or at once under reduced motion).
 */
export function ScrollToLatest({ thinking, enabled }: { thinking: boolean; enabled: boolean }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const [away, setAway] = useState(false)

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
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+84px)] z-30 mx-auto flex max-w-[480px] justify-center px-4">
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
