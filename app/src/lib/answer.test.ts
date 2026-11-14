import { afterEach, describe, expect, it, vi } from 'vitest'
import { readAskStream } from '../api/askStream.ts'
import contract from '../api/mock/contract-examples.json'
import { mockAsk } from '../api/mock/mockAsk.ts'
import type { AskEvent } from '../api/types.ts'
import {
  EMPTY_ANSWER,
  actionsOf,
  applyAskEvent,
  splitTakeaway,
  withoutPartialToken,
  writtenByTemplate,
  type Answer,
} from './answer.ts'

const examples = contract.examples as unknown as Record<string, unknown>

function streamOf(text: string): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text)
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes)
      controller.close()
    },
  })
}

async function events(stream: ReadableStream<Uint8Array>): Promise<AskEvent[]> {
  const out: AskEvent[] = []
  for await (const event of readAskStream(stream)) out.push(event)
  return out
}

function replay(list: AskEvent[], upTo = list.length): Answer {
  return list.slice(0, upTo).reduce(applyAskEvent, EMPTY_ANSWER)
}

describe('applyAskEvent on the full-stream example', () => {
  it('builds the finished answer: meta, one card, all cited numbers and the text of done', async () => {
    const list = await events(streamOf(examples['ask.sse.stream'] as string))
    const answer = replay(list)
    expect(answer.status).toBe('done')
    expect(answer.meta).toEqual(examples['ask.sse.meta'])
    expect(answer.cards.map((card) => card.card_id)).toEqual(['card_ans7f_01'])
    expect(Object.keys(answer.numbers).sort()).toEqual(['n1', 'n3', 'n5', 'n8'])
    expect(answer.done?.outcome).toBe('answered')
    expect(answer.text).toBe((examples['ask.sse.done'] as { text: string }).text)
  })

  it('moves through the stages in order and keeps the status label', async () => {
    const list = await events(streamOf(examples['ask.sse.stream'] as string))
    expect(replay(list, 1).stage).toBe(0)
    const afterStatus = replay(list, 2)
    expect(afterStatus.stage).toBe(1)
    expect(afterStatus.labels.tool).toBe('Looking at where your money went in September')
    expect(replay(list, 3).stage).toBe(1)
    expect(replay(list, 4).stage).toBe(2)
  })
})

describe('applyAskEvent on the error-stream example', () => {
  it('ends in the error state with the envelope', async () => {
    const answer = replay(await events(streamOf(examples['ask.sse.stream_error'] as string)))
    expect(answer.status).toBe('error')
    expect(answer.error).toEqual((examples['ask.sse.error'] as { error: unknown }).error)
    expect(answer.labels.understanding).toBe('Reading your question')
  })
})

describe('answer shape helpers', () => {
  it('takes the first sentence as the takeaway', () => {
    const text = (examples['ask.sse.done'] as { text: string }).text
    const { takeaway, rest } = splitTakeaway(text)
    expect(takeaway).toBe('September cost {{n1}}, which is {{n3}} more than August.')
    expect(rest.startsWith('Most of the increase is Travel at {{n5}}')).toBe(true)
  })

  it('keeps a one-sentence text whole', () => {
    expect(splitTakeaway('Which period do you mean?')).toEqual({ takeaway: 'Which period do you mean?', rest: '' })
  })

  it('does not cut at an abbreviation followed by a lower-case word', () => {
    const fi = 'Käytit ruokaan esim. kaupoissa {{n1}}. Ero on pieni.'
    expect(splitTakeaway(fi)).toEqual({ takeaway: 'Käytit ruokaan esim. kaupoissa {{n1}}.', rest: 'Ero on pieni.' })
    const en = 'You spend approx. three times more on Fridays. That is a habit.'
    expect(splitTakeaway(en)).toEqual({ takeaway: 'You spend approx. three times more on Fridays.', rest: 'That is a habit.' })
  })

  it('cuts before a capital letter, also a Finnish one, and before a number token', () => {
    expect(splitTakeaway('Hyvä alku. Älä huoli.')).toEqual({ takeaway: 'Hyvä alku.', rest: 'Älä huoli.' })
    expect(splitTakeaway('Groceries went up! {{n2}} more than in August.')).toEqual({
      takeaway: 'Groceries went up!',
      rest: '{{n2}} more than in August.',
    })
  })

  it('never shows half a number token', () => {
    expect(withoutPartialToken('September cost {{n1')).toBe('September cost ')
    expect(withoutPartialToken('September cost {{n1}')).toBe('September cost ')
    expect(withoutPartialToken('September cost {')).toBe('September cost ')
    expect(withoutPartialToken('September cost {{n1}}')).toBe('September cost {{n1}}')
    expect(splitTakeaway('Cost {{n1}}. Up {{n')).toEqual({ takeaway: 'Cost {{n1}}.', rest: 'Up' })
  })

  it('lists the card actions once, at most 2 per card', async () => {
    const answer = replay(await events(streamOf(examples['ask.sse.stream'] as string)))
    expect(actionsOf([...answer.cards, ...answer.cards]).map((action) => action.type)).toEqual([
      'open_evidence',
      'open_whatif',
    ])
  })
})

describe('mock /api/ask', () => {
  const request = { customer_id: 'CUST00042', conversation_id: null, language: 'en' as const }

  it('answers the contract refusal question with the refusal example', async () => {
    const message = (examples['ask.json.request_refusal'] as { message: string }).message
    const stream = await mockAsk({ ...request, message })
    const answer = (await events(stream)).reduce(applyAskEvent, EMPTY_ANSWER)
    const expected = examples['ask.json.response_refusal'] as { text: string; refusal: unknown; follow_ups: string[] }
    expect(answer.done?.outcome).toBe('refused')
    expect(answer.done?.refusal).toEqual(expected.refusal)
    expect(answer.text).toBe(expected.text)
    expect(answer.done?.follow_ups).toEqual(expected.follow_ups)
  }, 15000)

  it('answers the contract clarify question with the clarify example', async () => {
    const stream = await mockAsk({ ...request, message: 'How much did I spend?' })
    const answer = (await events(stream)).reduce(applyAskEvent, EMPTY_ANSWER)
    expect(answer.done?.outcome).toBe('clarify')
    expect(answer.done?.clarify?.options).toEqual(['This month', 'Last month', 'The last three months'])
  }, 15000)

  it('rejects an unknown customer before the stream, as the contract says', async () => {
    await expect(mockAsk({ ...request, customer_id: 'CUST99999', message: 'Hi' })).rejects.toMatchObject({
      code: 'customer_not_found',
    })
  })
})

describe('the template note (#282): warning llm_unavailable, whatever the outcome', () => {
  const request = { customer_id: 'CUST00042', conversation_id: null, language: 'en' as const, message: 'Where did my money go?' }
  const withMock = (mock: string) => vi.stubGlobal('window', { location: { search: `?mock=${mock}` } })
  afterEach(() => vi.unstubAllGlobals())

  const done = (outcome: string, warnings: string[]) =>
    ({ ...(examples['ask.sse.done'] as object), outcome, warnings }) as Answer['done']

  it('shows for llm_unavailable on any outcome, and never for fallback alone', () => {
    expect(writtenByTemplate(done('answered', ['llm_unavailable']))).toBe(true)
    expect(writtenByTemplate(done('clarify', ['llm_unavailable']))).toBe(true)
    expect(writtenByTemplate(done('fallback', ['llm_unavailable']))).toBe(true)
    expect(writtenByTemplate(done('fallback', []))).toBe(false)
    expect(writtenByTemplate(done('answered', ['period_clamped', 'something_new']))).toBe(false)
    expect(writtenByTemplate(null)).toBe(false)
  })

  it('mock ?mock=template: answered by the template, with the warning and the card', async () => {
    withMock('template')
    const answer = (await events(await mockAsk(request))).reduce(applyAskEvent, EMPTY_ANSWER)
    expect(answer.done?.outcome).toBe('answered')
    expect(answer.done?.warnings).toEqual(['llm_unavailable'])
    expect(answer.text).toBe('Here is what I found for September.')
    expect(answer.cards.length).toBeGreaterThan(0)
    expect(writtenByTemplate(answer.done)).toBe(true)
  }, 15000)

  it("mock ?mock=fallback: the core's fixed short text with the card, and no template note", async () => {
    withMock('fallback')
    const answer = (await events(await mockAsk(request))).reduce(applyAskEvent, EMPTY_ANSWER)
    expect(answer.done?.outcome).toBe('fallback')
    expect(answer.text).toBe('I could not find data for that question.')
    expect(answer.cards.length).toBeGreaterThan(0)
    expect(writtenByTemplate(answer.done)).toBe(false)
  }, 15000)
})
