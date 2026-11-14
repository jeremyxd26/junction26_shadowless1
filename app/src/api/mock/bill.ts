// Mock of the bill flow's three calls (contract section 11), loaded only when BILL_LIVE is off.
//
// From the contract, unchanged (via contract-examples.json, `npm run mocks:sync`):
// - `bill.read_response`, `bill.response`, `bill.response_unknown` and `bill.error`.
// Hand-written and PROVISIONAL, because the contract has no example for them yet (#249, #250):
// - the samples list and its tile images (inline SVG data URIs; the CSP allows `img-src data:`);
// - the readings of the other samples (sample_4 has a misread amount over the explain limit).
// The housing sample returns the contract's `bill.read_response` in the request's language: for
// Finnish exactly the example; for English the same values with English displays of the amount and
// the due date (provisional, like sample_1's).
// Every company is fictional (the contract's own "Esimerkki" names); the IBANs are test numbers.
//
// Explain rules of the mock:
// - the contract's barcode → `bill.response`; any other 54-digit barcode → `bill.error`
//   (`barcode_check`); a barcode that is not 54 digits → `barcode_length` or `barcode_chars`;
// - any `fields` → `bill.response_unknown` as an ECHO: the typed payee, IBAN, reference and due
//   date are copied into `bill` as sent, unformatted and unchecked. Its amount, checks,
//   sentences and numbers stay the example's, so they do not describe what was typed.
// - `forecast` (contract 0.3.4): the examples' own when they carry it, else the PROVISIONAL fixture
//   of billForecast.ts (barcode → covered; fields → outside_forecast; typed bills from
//   Esimerkki Vesi Oy → not_covered and Esimerkki Energia Oy → tight).
// Texts of the responses stay English in Finnish, as in the what-if mock.
import type { BillApi } from '../bill.ts'
import { BillApiError } from '../bill.ts'
import type {
  BillErrorEnvelope,
  BillExplainRequest,
  BillExplainResponse,
  BillReadField,
  BillReadResponse,
  BillSample,
  BillSamplesResponse,
} from '../billTypes.ts'
import type { Language } from '../types.ts'
import { FORECASTS } from './billForecast.ts'
import contract from './contract-examples.json'

const examples = contract.examples as unknown as {
  'bill.request': BillExplainRequest
  'bill.request_fields': BillExplainRequest
  'bill.response': BillExplainResponse
  'bill.response_unknown': BillExplainResponse
  'bill.error': BillErrorEnvelope
  'bill.read_response': BillReadResponse
}

function clone<T>(value: T): T {
  return structuredClone(value)
}

function later<T>(make: () => T, ms = 400): Promise<T> {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      try {
        resolve(make())
      } catch (error) {
        reject(error)
      }
    }, ms)
  })
}

// ---- Samples (provisional) ----------------------------------------------------------------

interface SampleSpec {
  sample_id: string
  title: Record<Language, string>
  language: Language
  payee: string
  /** What the paper bill prints; the image is a drawing of a bill, not data. */
  printed: { amount: string; due: string }
  accent: string
}

const SAMPLES: SampleSpec[] = [
  {
    sample_id: 'sample_1',
    title: { en: 'Renovation invoice', fi: 'Remonttilasku' },
    language: 'fi',
    payee: 'Esimerkki Remontti Oy',
    printed: { amount: '145,00 €', due: '20.10.2026' },
    accent: '#B5651D',
  },
  {
    sample_id: 'sample_2',
    title: { en: 'Rent', fi: 'Vuokra' },
    language: 'fi',
    payee: 'Esimerkki Asunnot Oy',
    printed: { amount: '812,40 €', due: '1.10.2026' },
    accent: '#1F6F50',
  },
  {
    sample_id: 'sample_3',
    title: { en: 'Water bill', fi: 'Vesilasku' },
    language: 'fi',
    payee: 'Esimerkki Vesi Oy',
    printed: { amount: '38,90 €', due: '12.10.2026' },
    accent: '#2B5C8A',
  },
  {
    sample_id: 'sample_4',
    title: { en: 'Electricity bill', fi: 'Sähkölasku' },
    language: 'fi',
    payee: 'Esimerkki Energia Oy',
    printed: { amount: '150,00 €', due: '12.10.2026' },
    accent: '#6B4FA0',
  },
]

function escapeXml(text: string): string {
  return text.replace(/[<>&'"]/g, (char) => `&#${char.charCodeAt(0)};`)
}

/** A small drawing of a paper bill: a header band, the payee, a few lines and the amount box. */
function billImage(spec: SampleSpec): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 200" width="160" height="200">
<rect width="160" height="200" rx="6" fill="#ffffff"/>
<rect width="160" height="34" rx="6" fill="${spec.accent}"/>
<rect y="28" width="160" height="6" fill="${spec.accent}"/>
<text x="12" y="22" font-family="sans-serif" font-size="11" font-weight="700" fill="#ffffff">LASKU</text>
<text x="12" y="52" font-family="sans-serif" font-size="9" font-weight="700" fill="#1a1a1a">${escapeXml(spec.payee)}</text>
<rect x="12" y="62" width="96" height="4" rx="2" fill="#d9d9d9"/>
<rect x="12" y="72" width="120" height="4" rx="2" fill="#d9d9d9"/>
<rect x="12" y="82" width="80" height="4" rx="2" fill="#d9d9d9"/>
<text x="12" y="112" font-family="sans-serif" font-size="8" fill="#555555">Eräpäivä ${escapeXml(spec.printed.due)}</text>
<rect x="12" y="122" width="136" height="30" rx="4" fill="none" stroke="#9a9a9a"/>
<text x="20" y="142" font-family="sans-serif" font-size="12" font-weight="700" fill="#1a1a1a">${escapeXml(spec.printed.amount)}</text>
<g fill="#1a1a1a">${Array.from({ length: 34 }, (_, i) => `<rect x="${12 + i * 4}" y="166" width="${i % 3 === 0 ? 2 : 1}" height="22"/>`).join('')}</g>
</svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

function samples(lang: Language): BillSamplesResponse {
  const list: BillSample[] = SAMPLES.map((spec) => ({
    sample_id: spec.sample_id,
    title: `${spec.title[lang]} · ${spec.payee}`,
    language: spec.language,
    image_url: billImage(spec),
  }))
  return { samples: list }
}

// ---- Readings ---------------------------------------------------------------------------

function field(
  value: string,
  display: string,
  status: BillReadField['status'],
  source: BillReadField['source'],
  note: string | null = null,
): BillReadField {
  return { value, display, status, source, note }
}

const REFERENCE_NOTE: Record<Language, string> = {
  en: 'This reference number does not pass its check. Compare it with the paper bill.',
  fi: 'Tämä viitenumero ei läpäise tarkistusta. Vertaa sitä paperilaskuun.',
}

function readSample(sampleId: string, lang: Language): BillReadResponse {
  // The contract example, answered in the request's language (contract 11.4).
  if (sampleId === 'sample_2') {
    const reading = { ...clone(examples['bill.read_response']), language: lang }
    if (lang === 'en') {
      if (reading.fields.amount) reading.fields.amount.display = '€812.40'
      if (reading.fields.due_date) reading.fields.due_date.display = '1 Oct 2026'
    }
    return reading
  }
  if (sampleId === 'sample_1') {
    // The typed bill of the contract (bill.request_fields), as a reader would see it on paper.
    return {
      sample_id: sampleId,
      language: lang,
      fields: {
        payee: field('Esimerkki Remontti Oy', 'Esimerkki Remontti Oy', 'unchecked', 'printed'),
        iban: field('FI7112345600009876', 'FI71 1234 5600 0098 76', 'checked', 'printed'),
        reference: field('12345', '12345', 'unchecked', 'printed', REFERENCE_NOTE[lang]),
        amount: field('145.00', lang === 'fi' ? '145,00 €' : '€145.00', 'unchecked', 'printed'),
        due_date: field('2026-10-20', lang === 'fi' ? '20.10.2026' : '20 Oct 2026', 'unchecked', 'printed'),
        barcode: null,
      },
      needs_confirmation: true,
    }
  }
  if (sampleId === 'sample_4') {
    // A misread amount: the bill prints 150,00 €, the reader proposes 150000.00, which is over the
    // explain limit. Without a barcode, "Looks right" must open the fields and show the problem.
    return {
      sample_id: sampleId,
      language: lang,
      fields: {
        payee: field('Esimerkki Energia Oy', 'Esimerkki Energia Oy', 'unchecked', 'printed'),
        iban: field('FI7112345600009876', 'FI71 1234 5600 0098 76', 'checked', 'printed'),
        reference: field('45609', '45609', 'checked', 'printed'),
        amount: field('150000.00', lang === 'fi' ? '150 000,00 €' : '€150,000.00', 'unchecked', 'printed'),
        due_date: field('2026-10-12', lang === 'fi' ? '12.10.2026' : '12 Oct 2026', 'unchecked', 'printed'),
        barcode: null,
      },
      needs_confirmation: true,
    }
  }
  if (sampleId === 'sample_3') {
    // Shows the typed fallback: the reader is unavailable (section 11.4, 503 model_unavailable).
    throw new BillApiError(503, {
      code: 'model_unavailable',
      message: MODEL_UNAVAILABLE[lang],
      retryable: false,
    })
  }
  throw new BillApiError(404, { code: 'not_found', message: NOT_FOUND[lang], retryable: false })
}

const MODEL_UNAVAILABLE: Record<Language, string> = {
  en: 'Reading the bill is not available right now. You can type its details instead.',
  fi: 'Laskun lukeminen ei ole nyt käytettävissä. Voit kirjoittaa sen tiedot itse.',
}

const NOT_FOUND: Record<Language, string> = {
  en: 'This sample bill was not found.',
  fi: 'Tätä esimerkkilaskua ei löytynyt.',
}

// ---- Explain ----------------------------------------------------------------------------

const BILL_ERRORS: Record<string, Record<Language, string>> = {
  barcode_check: {
    en: examples['bill.error'].error.message,
    fi: 'Tämä viivakoodi ei läpäise tarkistusta. Vertaa sitä paperilaskuun tai kirjoita tiedot.',
  },
  barcode_length: {
    en: 'A virtual barcode has 54 digits. Compare it with the paper bill, or type the fields.',
    fi: 'Virtuaaliviivakoodissa on 54 numeroa. Vertaa sitä paperilaskuun tai kirjoita tiedot.',
  },
  barcode_chars: {
    en: 'A virtual barcode has only digits. Compare it with the paper bill, or type the fields.',
    fi: 'Virtuaaliviivakoodissa on vain numeroita. Vertaa sitä paperilaskuun tai kirjoita tiedot.',
  },
  one_of_barcode_or_fields: {
    en: 'Send either the barcode or the fields of the bill.',
    fi: 'Lähetä joko viivakoodi tai laskun tiedot.',
  },
  payee_with_fields: {
    en: 'The payee goes inside the fields.',
    fi: 'Saajan nimi kuuluu laskun tietoihin.',
  },
}

function invalidBill(reason: string, lang: Language): BillApiError {
  return new BillApiError(422, { code: 'invalid_bill', message: BILL_ERRORS[reason][lang], retryable: false, reason })
}

const noSpaces = (text: string) => text.replace(/\s+/g, '')

function explain(request: BillExplainRequest): BillExplainResponse {
  const lang = request.language
  const hasBarcode = request.barcode != null
  const hasFields = request.fields != null
  if (hasBarcode === hasFields) throw invalidBill('one_of_barcode_or_fields', lang)
  if (hasFields && request.payee != null) throw invalidBill('payee_with_fields', lang)

  if (request.barcode != null) {
    const digits = noSpaces(request.barcode)
    if (/\D/.test(digits)) throw invalidBill('barcode_chars', lang)
    if (digits.length !== 54) throw invalidBill('barcode_length', lang)
    if (digits !== examples['bill.request'].barcode) throw invalidBill('barcode_check', lang)
    const response = { ...clone(examples['bill.response']), language: lang }
    response.forecast = response.forecast ?? clone(FORECASTS.covered)
    return response
  }

  const fields = request.fields!
  const response = clone(examples['bill.response_unknown'])
  response.language = lang
  response.bill = { ...response.bill, payee: fields.payee, iban: fields.iban, reference: fields.reference, due_date: fields.due_date }
  const provisional = PROVISIONAL_FORECAST_BY_PAYEE[fields.payee.trim()]
  response.forecast = provisional ? clone(provisional) : (response.forecast ?? clone(FORECASTS.outside_forecast))
  return response
}

/**
 * PROVISIONAL: typed bills from these fictional payees get a hand-written forecast, so every status
 * can be seen in the demo (the water bill is the typed fallback sample).
 */
const PROVISIONAL_FORECAST_BY_PAYEE: Record<string, BillExplainResponse['forecast']> = {
  'Esimerkki Vesi Oy': FORECASTS.not_covered,
  'Esimerkki Energia Oy': FORECASTS.tight,
}

export function createMockBillApi(): BillApi {
  return {
    samples: (lang) => later(() => samples(lang), 200),
    read: (request) => later(() => readSample(request.sample_id, request.language), 700),
    explain: (request) => later(() => explain(request), 500),
  }
}
