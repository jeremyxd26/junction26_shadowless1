// The POST /api/ask body (#875): voice mode names its channel; a typed question sends no extra field.
import { describe, expect, it } from 'vitest'
import { askRequest } from './useChat.ts'

describe('askRequest (#875)', () => {
  it('a typed question has no channel field, exactly as before', () => {
    const body = askRequest('CUST00860', null, 'Where did my money go?', 'en')
    expect(body).toEqual({ customer_id: 'CUST00860', conversation_id: null, message: 'Where did my money go?', language: 'en' })
    expect('channel' in body).toBe(false)
  })

  it('a voice-mode question says channel "voice"', () => {
    expect(askRequest('CUST00860', 'conv_1', 'Mihin rahani menivät?', 'fi', 'voice')).toEqual({
      customer_id: 'CUST00860',
      conversation_id: 'conv_1',
      message: 'Mihin rahani menivät?',
      language: 'fi',
      channel: 'voice',
    })
  })
})
