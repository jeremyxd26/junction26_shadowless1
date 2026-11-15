import { afterEach, describe, expect, it, vi } from 'vitest'
import { clientTurns, prefetchClientTurns } from './clientTurns.tsx'

describe('the client turns load their code at idle, ahead of the first tap (#728)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('prefetches every visible entry once, at idle, and leaves a failure to the turn', async () => {
    const idle: Array<() => void> = []
    vi.stubGlobal('window', { requestIdleCallback: (run: () => void) => idle.push(run), setTimeout })
    const bill = vi.fn(() => Promise.resolve())
    const hidden = vi.fn(() => Promise.reject(new Error('404')))
    const failing = vi.fn(() => Promise.reject(new Error('404')))
    const saved = { ...clientTurns }
    clientTurns.bill = { ...saved.bill, prefetch: bill }
    clientTurns.hidden = { ...saved.bill, visible: () => false, prefetch: hidden }
    clientTurns.failing = { ...saved.bill, prefetch: failing }
    try {
      prefetchClientTurns()
      prefetchClientTurns()
      expect(idle).toHaveLength(1)
      expect(bill).not.toHaveBeenCalled()
      idle[0]()
      expect(bill).toHaveBeenCalledTimes(1)
      expect(failing).toHaveBeenCalledTimes(1)
      expect(hidden).not.toHaveBeenCalled()
      // The failure is swallowed: no unhandled rejection reaches the page.
      await Promise.resolve()
    } finally {
      clientTurns.bill = saved.bill
      delete clientTurns.hidden
      delete clientTurns.failing
    }
  })

  // The whole test is one cold dynamic import of the bill flow's module graph. Warm it takes about 40 ms,
  // but on a loaded machine the first transform takes seconds and hit the default 5 s (#880), so it gets
  // an explicit budget.
  it("loads the same BillFlow module the bill turn renders", async () => {
    const module = (await clientTurns.bill.prefetch!()) as { BillFlow: unknown }
    expect(typeof module.BillFlow).toBe('function')
  }, 60_000)
})
