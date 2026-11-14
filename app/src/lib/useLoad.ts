import { useCallback, useEffect, useState } from 'react'

export type Loaded<T> =
  | { status: 'loading' }
  | { status: 'error'; error: unknown; retry: () => void }
  | { status: 'ready'; data: T; refresh: () => void }

interface Settled<T> {
  key: string
  attempt: number
  data?: T
  error?: unknown
}

/**
 * Loads data for `key`; a new key (or a retry) shows loading again. `load` must be stable
 * for a given key (wrap it in useCallback). `key` null means "nothing to load yet".
 * `refresh` loads again in the background: the old data stays on screen until the new data
 * arrives, and a failed refresh keeps the old data.
 */
export function useLoad<T>(key: string | null, load: () => Promise<T>): Loaded<T> {
  const [attempt, setAttempt] = useState(0)
  const [refreshes, setRefreshes] = useState(0)
  const [settled, setSettled] = useState<Settled<T> | null>(null)
  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  const refresh = useCallback(() => setRefreshes((n) => n + 1), [])

  useEffect(() => {
    if (key === null) return
    let cancelled = false
    load().then(
      (data) => {
        if (!cancelled) setSettled({ key, attempt, data })
      },
      (error: unknown) => {
        if (cancelled) return
        setSettled((previous) =>
          previous && previous.key === key && previous.attempt === attempt && !('error' in previous)
            ? previous
            : { key, attempt, error },
        )
      },
    )
    return () => {
      cancelled = true
    }
  }, [key, attempt, refreshes, load])

  if (key === null || !settled || settled.key !== key || settled.attempt !== attempt) return { status: 'loading' }
  if ('error' in settled) return { status: 'error', error: settled.error, retry }
  return { status: 'ready', data: settled.data as T, refresh }
}
