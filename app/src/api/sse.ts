// A text/event-stream reader over fetch() and a ReadableStream (contract section 7.2).
// The browser's EventSource only supports GET, and /api/ask is a POST, so the app parses the
// stream itself. This follows the event-stream rules of the HTML standard, minus reconnection:
// - lines end in CRLF, LF or CR, also when a chunk boundary falls between CR and LF;
// - a blank line dispatches the event; lines starting with ':' (such as `: ping`) are comments;
// - `event:` names the event, `data:` lines are joined with '\n', `id:` and `retry:` are ignored;
// - bytes are decoded as UTF-8 across chunk boundaries, so a split '€' is still one '€'.

export interface SseMessage {
  event: string
  data: string
}

const LINE_END = /[\r\n]/g

/** Incremental parser: feed it decoded text in any chunk sizes, get whole events back. */
export class SseParser {
  private buffer = ''
  private started = false
  private eventName = ''
  private dataLines: string[] = []

  /** Adds decoded text and returns the events it completed. */
  push(chunk: string): SseMessage[] {
    let text = this.buffer + chunk
    if (!this.started && text.length > 0) {
      this.started = true
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
    }
    const out: SseMessage[] = []
    let start = 0
    LINE_END.lastIndex = 0
    for (let match = LINE_END.exec(text); match; match = LINE_END.exec(text)) {
      const at = match.index
      // A CR at the very end may be the first half of CRLF: wait for the next chunk.
      if (text[at] === '\r' && at + 1 === text.length) break
      this.line(text.slice(start, at), out)
      start = at + (text[at] === '\r' && text[at + 1] === '\n' ? 2 : 1)
      LINE_END.lastIndex = start
    }
    this.buffer = text.slice(start)
    return out
  }

  /**
   * The stream ended. A last event without its closing blank line is still delivered: the
   * server closes the stream right after `done` or `error`, and the contract's examples end
   * that way too.
   */
  end(): SseMessage[] {
    const out: SseMessage[] = []
    const rest = this.buffer.replace(/\r$/, '')
    this.buffer = ''
    if (rest.length > 0) this.line(rest, out)
    this.line('', out)
    return out
  }

  private line(line: string, out: SseMessage[]) {
    if (line === '') {
      if (this.dataLines.length > 0) out.push({ event: this.eventName || 'message', data: this.dataLines.join('\n') })
      this.eventName = ''
      this.dataLines = []
      return
    }
    if (line.startsWith(':')) return
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.eventName = value
    else if (field === 'data') this.dataLines.push(value)
  }
}

/**
 * Reads a byte stream as server-sent events. Stopping early (a `break` in the consumer)
 * cancels the stream, which closes the HTTP response.
 */
export async function* readSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = stream.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = new SseParser()
  let finished = false
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      yield* parser.push(decoder.decode(value, { stream: true }))
    }
    finished = true
    yield* parser.push(decoder.decode())
    yield* parser.end()
  } finally {
    if (!finished) await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
