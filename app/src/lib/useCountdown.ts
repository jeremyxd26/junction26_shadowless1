import { useEffect, useState } from 'react'

/** Whole seconds left until `until` (a `Date.now()` time), ticking down; 0 when there is nothing to wait for. */
export function useCountdown(until: number | null): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (until === null) return
    const tick = () => {
      const current = Date.now()
      setNow(current)
      if (current >= until) window.clearInterval(id)
    }
    const id = window.setInterval(tick, 250)
    tick()
    return () => window.clearInterval(id)
  }, [until])

  if (until === null || now >= until) return 0
  return Math.ceil((until - now) / 1000)
}
