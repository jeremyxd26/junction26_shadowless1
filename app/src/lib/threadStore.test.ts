import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { EMPTY_ANSWER } from './answer.ts'
import type { Turn } from './thread.ts'
import { MAX_STORED_TURNS, THREAD_VERSION, clearThreads, loadThread, saveThread } from './threadStore.ts'

class MemoryStorage {
  data = new Map<string, string>()
  get length() { return this.data.size }
  key(i: number) { return [...this.data.keys()][i] ?? null }
  getItem(k: string) { return this.data.has(k) ? this.data.get(k)! : null }
  setItem(k: string, v: string) { this.data.set(k, v) }
  removeItem(k: string) { this.data.delete(k) }
  clear() { this.data.clear() }
}

const ask = (id: number, status: 'done' | 'streaming'): Turn => ({
  kind: 'ask', id, question: `q${id}`, answer: { ...EMPTY_ANSWER, status, text: `a${id}` },
})

describe('the current dialog in sessionStorage', () => {
  let store: MemoryStorage
  beforeEach(() => {
    store = new MemoryStorage()
    ;(globalThis as unknown as { window: unknown }).window = { sessionStorage: store }
  })
  afterEach(() => {
    delete (globalThis as unknown as { window?: unknown }).window
  })

  it('comes back for the same persona with its conversation id; a streaming answer comes back stopped', () => {
    saveThread('CUST00860', { conversationId: 'conv_a', nextId: 3, turns: [ask(1, 'done'), ask(2, 'streaming')] })
    const back = loadThread('CUST00860')!
    expect(back.conversationId).toBe('conv_a')
    expect(back.nextId).toBe(3)
    expect(back.turns.map((t) => (t.kind === 'ask' ? t.answer.status : t.kind))).toEqual(['done', 'stopped'])
    expect(loadThread('CUST00493')).toBeNull()
  })

  it('keeps the last turns only, and drops an old version or a broken entry silently', () => {
    const many = Array.from({ length: MAX_STORED_TURNS + 5 }, (_, i) => ask(i + 1, 'done'))
    saveThread('CUST00860', { conversationId: null, nextId: 99, turns: many })
    expect(loadThread('CUST00860')!.turns).toHaveLength(MAX_STORED_TURNS)
    store.setItem('sentti.thread.CUST00860', JSON.stringify({ v: THREAD_VERSION + 1, turns: [ask(1, 'done')] }))
    expect(loadThread('CUST00860')).toBeNull()
    store.setItem('sentti.thread.CUST00860', '{not json')
    expect(loadThread('CUST00860')).toBeNull()
  })

  it('New chat and a persona switch clear every stored dialog; an empty thread removes the entry', () => {
    saveThread('CUST00860', { conversationId: 'c', nextId: 2, turns: [ask(1, 'done')] })
    saveThread('CUST00493', { conversationId: 'd', nextId: 2, turns: [ask(1, 'done')] })
    store.setItem('other.key', 'kept')
    clearThreads()
    expect(store.getItem('sentti.thread.CUST00860')).toBeNull()
    expect(store.getItem('sentti.thread.CUST00493')).toBeNull()
    expect(store.getItem('other.key')).toBe('kept')
    saveThread('CUST00860', { conversationId: null, nextId: 1, turns: [] })
    expect(store.getItem('sentti.thread.CUST00860')).toBeNull()
  })

  it('without storage nothing breaks', () => {
    delete (globalThis as unknown as { window?: unknown }).window
    expect(loadThread('CUST00860')).toBeNull()
    expect(() => saveThread('CUST00860', { conversationId: null, nextId: 1, turns: [ask(1, 'done')] })).not.toThrow()
    expect(() => clearThreads()).not.toThrow()
  })
})
