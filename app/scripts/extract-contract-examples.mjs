// Copies the JSON examples the app's mock mode needs from contracts/api.md into
// src/api/mock/contract-examples.json, unchanged. Re-run after the contract changes:
//   npm run mocks:sync
// The build never reads ../contracts; it only uses the committed JSON.
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
  'label.response',
  'label.response_wanted',
  'label.response_undo',
  'label.error',
  'card.safe_to_save',
  'card.safe_to_save_aleksi',
  'card.safe_to_save_zero',
  'card.safe_to_save_everyday',
  'whatif.response',
]

const text = readFileSync(contractPath, 'utf8')
const version = /\*\*Version:\*\*\s*([0-9.]+)/.exec(text)?.[1] ?? 'unknown'
const pattern = /<!-- example: ([\w.]+) -->\s*```json\n([\s\S]*?)\n```/g

const examples = {}
for (const match of text.matchAll(pattern)) {
  const [, name, body] = match
  if (NEEDED.includes(name)) examples[name] = JSON.parse(body)
}

const missing = NEEDED.filter((name) => !(name in examples))
if (missing.length > 0) {
  console.error(`Missing examples in contracts/api.md: ${missing.join(', ')}`)
  process.exit(1)
}

writeFileSync(outPath, JSON.stringify({ contract_version: version, examples }, null, 2) + '\n')
console.log(`Wrote ${NEEDED.length} examples from contract ${version} to ${outPath}`)
