// Copies the examples the app's mock mode and tests need from contracts/api.md into
// src/api/mock/contract-examples.json, unchanged. Re-run after the contract changes:
//   npm run mocks:sync
// The build never reads ../contracts; it only uses the committed JSON.
// JSON examples are stored parsed; text examples (the /api/ask wire streams) as strings.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const contractPath = resolve(here, '../../contracts/api.md')
const outPath = resolve(here, '../src/api/mock/contract-examples.json')

const NEEDED = [
  'personas.response',
  'overview.response',
  'overview.response_pending',
  'evidence.response',
  'evidence.response_composite',
  'evidence.error',
  'error.response',
  'label.request',
  'label.response',
  'label.request_wanted',
  'label.response_wanted',
  'label.request_undo',
  'label.response_undo',
  'label.error',
  // POST /api/ask (section 7)
  'ask.sse.meta',
  'ask.sse.status',
  'ask.sse.card',
  'ask.sse.numbers_1',
  'ask.sse.delta_1',
  'ask.sse.numbers_2',
  'ask.sse.delta_2',
  'ask.sse.delta_3',
  'ask.sse.done',
  'ask.sse.error',
  'ask.sse.stream',
  'ask.sse.stream_error',
  'ask.json.request_fi',
  'ask.json.response_fi',
  'ask.json.request_refusal',
  'ask.json.response_refusal',
  // A refusal as the first answer of a conversation: the contact_bank action and the AI disclosure (0.3.3, #439)
  'ask.json.request_refusal_first',
  'ask.json.response_refusal_first',
  'ask.json.request_clarify',
  'ask.json.response_clarify',
  'card.safe_to_save',
  'card.safe_to_save_aleksi',
  'card.safe_to_save_zero',
  'card.safe_to_save_everyday',
  'card.profile',
  'card.peer',
  'card.whatif',
  'card.review',
  'overview.response_no_hero',
  'whatif.response',
  // POST /api/bill/explain and the sample-bill reading (section 11)
  'bill.request',
  'bill.request_fields',
  'bill.error',
  'bill.response',
  'bill.response_unknown',
  'bill.read_response',
  'host.payment_draft',
  // The action open_host_screen and the host message it sends (contract 0.3.1, #268)
  'action.open_host_screen',
  'host.open_host_screen',
]

const text = readFileSync(contractPath, 'utf8')
const version = /\*\*Version:\*\*\s*([0-9.]+)/.exec(text)?.[1] ?? 'unknown'
const pattern = /<!-- example: ([\w.]+) -->\s*```(json|text)\n([\s\S]*?)\n```/g

const examples = {}
for (const match of text.matchAll(pattern)) {
  const [, name, kind, body] = match
  if (NEEDED.includes(name)) examples[name] = kind === 'json' ? JSON.parse(body) : `${body}\n`
}

const missing = NEEDED.filter((name) => !(name in examples))
if (missing.length > 0) {
  console.error(`Missing examples in contracts/api.md: ${missing.join(', ')}`)
  process.exit(1)
}

writeFileSync(outPath, JSON.stringify({ contract_version: version, examples }, null, 2) + '\n')
console.log(`Wrote ${NEEDED.length} examples from contract ${version} to ${outPath}`)
