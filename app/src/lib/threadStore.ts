// The current dialog in this tab (Renat's decision): the thread, its conversation id and the next turn id under one
// sessionStorage key per persona, so a reload in the same tab shows the same chat. No history list, nothing in
// localStorage; closing the tab, New chat and a persona switch clear it. Every access is guarded: private windows,
// blocked storage and a full quota just mean no restore.
import { stopped } from './answer.ts'
import type { Turn } from './thread.ts'

/** The stored shape's version: an entry of another version is dropped silently. */
export const THREAD_VERSION = 1
const PREFIX = 'sentti.thread.'
/** Only the last turns are kept. */
export const MAX_STORED_TURNS = 30

export interface StoredThread {
  conversationId: string | null
  nextId: number
  turns: Turn[]
}

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    return null
  }
}

function validTurn(turn: unknown): turn is Turn {
  if (!turn || typeof turn !== 'object') return false
  const t = turn as Record<string, unknown>
  if (typeof t.id !== 'number' || typeof t.question !== 'string') return false
  if (t.kind === 'client') return typeof t.key === 'string' && typeof t.render === 'string'
  if (t.kind !== 'ask' || !t.answer || typeof t.answer !== 'object') return false
  const status = (t.answer as Record<string, unknown>).status
  return status === 'done' || status === 'error' || status === 'stopped' || status === 'streaming'
}

/** The stored dialog of this persona, or null. An answer that was streaming at the reload comes back stopped
 *  (with its "Ask again"); a bad or old entry is removed and gives null. */
export function loadThread(customerId: string | null): StoredThread | null {
  const store = storage()
  if (!store || !customerId) return null
  try {
    const raw = store.getItem(PREFIX + customerId)
    if (!raw) return null
    const data = JSON.parse(raw) as Record<string, unknown>
    if (!data || data.v !== THREAD_VERSION || !Array.isArray(data.turns)) {
      store.removeItem(PREFIX + customerId)
      return null
    }
    const turns = (data.turns as unknown[]).filter(validTurn).slice(-MAX_STORED_TURNS).map((turn) =>
      turn.kind === 'ask' && turn.answer.status === 'streaming' ? { ...turn, answer: stopped(turn.answer, 'you') } : turn,
    )
    if (turns.length === 0) return null
    const nextId = Math.max(typeof data.nextId === 'number' ? data.nextId : 1, ...turns.map((turn) => turn.id + 1))
    return { conversationId: typeof data.conversationId === 'string' ? data.conversationId : null, nextId, turns }
  } catch {
    return null
  }
}

/** Keeps this persona's dialog; an empty thread removes the entry. */
export function saveThread(customerId: string | null, thread: StoredThread): void {
  const store = storage()
  if (!store || !customerId) return
  try {
    if (thread.turns.length === 0) {
      store.removeItem(PREFIX + customerId)
      return
    }
    store.setItem(PREFIX + customerId, JSON.stringify({ v: THREAD_VERSION, conversationId: thread.conversationId,
      nextId: thread.nextId, turns: thread.turns.slice(-MAX_STORED_TURNS) }))
  } catch {
    // a full quota or blocked storage: the chat goes on, it is just not restored
  }
}

/** New chat and a persona switch: every stored dialog of this tab goes. */
export function clearThreads(): void {
  const store = storage()
  if (!store) return
  try {
    const keys: string[] = []
    for (let i = 0; i < store.length; i++) {
      const key = store.key(i)
      if (key?.startsWith(PREFIX)) keys.push(key)
    }
    keys.forEach((key) => store.removeItem(key))
  } catch {
    // nothing to clear when storage is blocked
  }
}
