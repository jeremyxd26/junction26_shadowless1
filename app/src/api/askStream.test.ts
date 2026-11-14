// The stream parser against the contract's own examples (contracts/api.md section 7),
// copied unchanged into contract-examples.json by `npm run mocks:sync`.
import { describe, expect, it } from 'vitest'
import { ApiError } from './errors.ts'
import { readAskStream } from './askStream.ts'
import contract from './mock/contract-examples.json'
import { SseParser, readSse } from './sse.ts'
import type { AskEvent } from './types.ts'

const examples = contract.examples as unknown as Record<string, unknown>
const FULL = examples['ask.sse.stream'] as string
const ERROR = examples['ask.sse.stream_error'] as string

const encoder = new TextEncoder()

/** A byte stream that delivers `bytes` cut at the given offsets. */
function streamOf(bytes: Uint8Array, cuts: number[] = []): ReadableStream<Uint8Array> {
  const points = [0, ...cuts.filter((cut) => cut > 0 && cut < bytes.length).sort((a, b) => a - b), bytes.length]
  const chunks = points.slice(1).map((end, index) => bytes.slice(points[index], end))
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  })
}

function everyByte(bytes: Uint8Array): number[] {
  return Array.from({ length: bytes.length }, (_, index) => index)
}

/** Deterministic pseudo-random cut points (no flaky tests). */
function randomCuts(length: number, count: number, seed: number): number[] {
  let state = seed
  const next = () => {
    state = (state * 1103515245 + 12345) % 2147483648
    return state / 2147483648
  }
  return Array.from({ length: count }, () => 1 + Math.floor(next() * (length - 1)))
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<AskEvent[]> {
  const events: AskEvent[] = []
  for await (const event of readAskStream(stream)) events.push(event)
  return events
}

async function failure(stream: ReadableStream<Uint8Array>): Promise<ApiError> {
  try {
    await collect(stream)
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('expected the stream to fail')
}

const deltaText = (events: AskEvent[]) =>
  events.flatMap((event) => (event.event === 'delta' ? [event.data.text] : [])).join('')

describe('readAskStream on the full-stream example (ask.sse.stream)', () => {
  it('yields the events in order with the payloads of the event examples', async () => {
    const events = await collect(streamOf(encoder.encode(FULL)))
    expect(events.map((event) => event.event)).toEqual([
      'meta',
      'status',
      'card',
      'numbers',
      'delta',
      'numbers',
      'delta',
      'delta',
      'done',
    ])
    expect(events[0].data).toEqual(examples['ask.sse.meta'])
    expect(events[1].data).toEqual(examples['ask.sse.status'])
    expect(events[2].data).toEqual(examples['ask.sse.card'])
    expect(events[3].data).toEqual(examples['ask.sse.numbers_1'])
    expect(events[4].data).toEqual(examples['ask.sse.delta_1'])
    expect(events[5].data).toEqual(examples['ask.sse.numbers_2'])
    expect(events[6].data).toEqual(examples['ask.sse.delta_2'])
    expect(events[7].data).toEqual(examples['ask.sse.delta_3'])
    expect(events[8].data).toEqual(examples['ask.sse.done'])
  })

  it('joins the deltas into the full text of `done`', async () => {
    const events = await collect(streamOf(encoder.encode(FULL)))
    const done = events.at(-1)
    expect(done?.event).toBe('done')
    if (done?.event === 'done') expect(deltaText(events)).toBe(done.data.text)
  })

  it('gives the same events when every byte is its own chunk (splits "€" and every token)', async () => {
    const bytes = encoder.encode(FULL)
    const whole = await collect(streamOf(bytes))
    const split = await collect(streamOf(bytes, everyByte(bytes)))
    expect(split).toEqual(whole)
    // No number token is ever cut: each delta carries whole tokens only.
    for (const event of split) {
      if (event.event === 'delta') expect(event.data.text).not.toMatch(/\{\{(?!n[0-9]+\}\})/)
    }
    expect(deltaText(split)).toContain('{{n1}}')
  })

  it('gives the same events for random chunk boundaries inside events', async () => {
    const bytes = encoder.encode(FULL)
    const whole = await collect(streamOf(bytes))
    for (const seed of [1, 7, 42, 2026, 31337]) {
      expect(await collect(streamOf(bytes, randomCuts(bytes.length, 25, seed)))).toEqual(whole)
    }
  })

  it('reads CRLF and CR line endings, also with a cut between CR and LF', async () => {
    const whole = await collect(streamOf(encoder.encode(FULL)))
    const crlf = encoder.encode(FULL.replace(/\n/g, '\r\n'))
    const cutsInsideCrlf = everyByte(crlf).filter((index) => crlf[index - 1] === 0x0d)
    expect(await collect(streamOf(crlf, cutsInsideCrlf))).toEqual(whole)
    expect(await collect(streamOf(encoder.encode(FULL.replace(/\n/g, '\r'))))).toEqual(whole)
  })
})

describe('readAskStream on the error-stream example (ask.sse.stream_error)', () => {
  it('skips the `: ping` comment and ends with the error envelope', async () => {
    const events = await collect(streamOf(encoder.encode(ERROR)))
    expect(events.map((event) => event.event)).toEqual(['meta', 'status', 'error'])
    expect(events[2].data).toEqual(examples['ask.sse.error'])
    const last = events[2]
    if (last.event === 'error') expect(last.data.error.retryable).toBe(true)
  })

  it('gives the same events for a cut at every position', async () => {
    const bytes = encoder.encode(ERROR)
    const whole = await collect(streamOf(bytes))
    for (let cut = 1; cut < bytes.length; cut += 1) {
      expect(await collect(streamOf(bytes, [cut]))).toEqual(whole)
    }
    expect(await collect(streamOf(bytes, everyByte(bytes)))).toEqual(whole)
  })
})

describe('readAskStream on broken streams', () => {
  it('fails with a retryable error when the stream stops before `done`', async () => {
    const cut = FULL.indexOf('event: done')
    const error = await failure(streamOf(encoder.encode(FULL.slice(0, cut))))
    expect(error.code).toBe('stream_ended')
    expect(error.retryable).toBe(true)
  })

  it('fails with a retryable error on a payload that is not JSON', async () => {
    const error = await failure(streamOf(encoder.encode('event: meta\ndata: {"answer_id":\n\n')))
    expect(error.code).toBe('bad_stream')
    expect(error.retryable).toBe(true)
  })

  it('fails on a payload with the wrong shape', async () => {
    const error = await failure(streamOf(encoder.encode('event: delta\ndata: {"text":42}\n\n')))
    expect(error.code).toBe('bad_stream')
  })

  it('skips events it does not know and stops reading after `done`', async () => {
    const done = FULL.slice(FULL.indexOf('event: done'))
    const text = `event: future\ndata: {"x":1}\n\n${done}\n\nevent: delta\ndata: {"text":"late"}\n\n`
    const events = await collect(streamOf(encoder.encode(text)))
    expect(events.map((event) => event.event)).toEqual(['done'])
  })
})

describe('SseParser', () => {
  it('joins several data lines, strips one leading space and ignores id and retry', () => {
    const parser = new SseParser()
    const out = parser.push('id: 1\nretry: 10\nevent: x\ndata:  two spaces\ndata:b\n\n')
    expect(out).toEqual([{ event: 'x', data: ' two spaces\nb' }])
  })

  it('names an event without `event:` "message" and drops an event without data', () => {
    const parser = new SseParser()
    expect(parser.push('event: empty\n\ndata: plain\n\n')).toEqual([{ event: 'message', data: 'plain' }])
  })

  it('strips a byte order mark at the start of the stream', async () => {
    const bytes = encoder.encode('﻿event: a\ndata: 1\n\n')
    const out = []
    for await (const message of readSse(streamOf(bytes, everyByte(bytes)))) out.push(message)
    expect(out).toEqual([{ event: 'a', data: '1' }])
  })
})
