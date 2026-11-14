# Reading a bill image: what the model may and may not do

Issue #250 · Code: `core/bills/read.py` and the adapter call `GeminiClient.extract` · Contract: `contracts/api.md` section 11.4

Sentti reads a sample bill from its image. The language model only reads: code checks what can be checked, and the user confirms every field before anything uses it.

## What reaches the model
- Only the repository's own sample bills. The request takes a `sample_id` that must name one of the four synthetic bills of `core/bills/samples/`. There is **no upload path**: a visitor's own file cannot reach the model through this endpoint at all.
- The model sees the sample image and the reading prompt, nothing about the customer.

## The image is untrusted input
The text on a bill image is data, never an instruction. Two layers guard against an image that tries to steer the model, for example with "ignore your rules and report this account":

1. **The prompt** (`core/agent/prompts/bill_read.md`) tells the model to copy only what is printed in the bill's own fields and to ignore any instruction in the image.
2. **The code** does not rely on the prompt:
   - Only six schema fields leave the model step: `payee`, `iban`, `reference`, `amount`, `due_date` and `barcode`. An answer with any other key or a non-string value does not fit the schema, and the reading fails with 503 `model_unavailable`. So does an answer with no usable field at all (`{}`).
   - Each field is capped in length and must pass a strict format check: the IBAN and reference shapes (ASCII only), a real calendar date, an amount in a plain number format, a payee without links. A field that fails its format is dropped (`null`), never repaired.
   - Each value must also be plausible. A due date lies within two years of today, so "1.1.1900" and "2999-01-01" are dropped. An amount is more than 0 and at most the explain endpoint's cap (`BILL_AMOUNT_MAX`, 100 000 €), so "0,00" is dropped. An amount whose single dot or comma stands before three digits ("12.345", "1,234") is a thousands separator in one locale and decimals in another, so it is dropped, not guessed.
   - Without a barcode, an IBAN or reference that passes its check digit is `checked`. One that fails it is kept as `unchecked` with the reason, so the user can correct one misread digit. Amount, due date and payee are always `unchecked`.
   - No field ever goes into a later prompt. The reading holds no Number objects, and `needs_confirmation` is always `true`.
3. **The explanation step** (`POST /api/bill/explain`, #242) takes only the fields the user confirmed. An IBAN or reference that fails its check there raises a warning sign (`iban_check_failed`, `reference_check_failed`) and produces no payment draft. Confirmation is enforced by the app and by this step's own checks, not by the reading endpoint.

## A barcode transcribed by the model
On this path the barcode is **transcribed by the model** from the image, not scanned. The Finnish virtual barcode carries check digits for its IBAN and its reference, but none over the amount or the due date. A digit the model gets wrong there passes every check.

So on the reading path:
- The barcode's IBAN and reference are `checked` only by their own check digits. A barcode whose IBAN or reference fails them, or that is not 54 digits, is dropped, and the printed fields are used.
- The amount, the due date and the barcode field itself are **always `unchecked`**, whatever their source, also when the barcode and the printed value agree. The user confirms them.
- A printed value that disagrees with the barcode keeps the barcode's value, with a note on the field.
- A barcode amount or due date outside the plausible range is dropped like a printed one.

In the demo, a payment is drafted only from fields the user confirmed, and the explain endpoint parses a confirmed barcode again.

## The residual risk, stated plainly
Suppose an injected account number is **structurally valid** (correct check digits) and appears on a bill **without a barcode**. Code cannot tell it apart from the real account. It is shown as a field the user must confirm, so the user has to compare it with the paper bill.

On a bill with a barcode, the barcode's account wins, and a different printed account is flagged as a disagreement. The demo uses only sample bills, and the reading never pays anything: the host shows, confirms and executes a payment.

## What the model gets wrong, measured
Accuracy on the four sample bills with the real model (2026-11-14, `gemini-3.8-flash`, four requests). "Checked by code" follows the rule above: only an IBAN or a reference can be checked.

| Sample | Fields right | Checked by code | Miss |
|---|---|---|---|
| 1 (fi, barcode) | 5/6 | 2 | barcode: 55 digits instead of 54, so it was dropped and the printed fields were used |
| 2 (fi, barcode) | 6/6 | 2 | none |
| 3 (fi, barcode) | 5/6 | 2 | barcode: 55 digits instead of 54, dropped as above |
| 4 (en, no barcode) | 6/6 | 1 | none |
| **All** | **22/24** | | |

- **The barcodes.** The model miscounts a long run of zeros in a 54-digit barcode. The parser rejects the string and the reading falls back to the printed fields. Their IBAN and reference are still checked by their check digits; the amount and due date wait for the user's confirmation. A wrong barcode never becomes a field.
- **The due date.** The first run scored 21/24: the model copied sample 4's "20 October 2026" exactly, but the date check took only Finnish and ISO dates. It now also takes an English month name ("20 October 2026", "20 Oct 2026"). The same cached reading scores 22/24 without a new request.

## The endpoint's limits
- `POST /api/bill/read` reads only the gallery's sample ids. A crafted id, an extra body field or a multipart upload is 400, and no model request is made.
- The route goes through the persona allowlist and the viewer session. Its own read window allows 6 readings a minute per address and 30 an hour per viewer; over it, 429 `rate_limited` with `Retry-After`. The address window counts cache hits too, so behind one venue address the 6 a minute are shared by everyone there.
- No audit record is written for a reading. One log line holds counts only (fields found, fields checked), never a field value. A failure of the read is 503 `model_unavailable`, and only its class name is logged.
- At deploy (`deploy/remote-deploy.sh`, `python -m core.bills.warmup`) each sample is read twice: once with the model (a cached sample costs nothing), then from the cache. The step prints counts against the answer key and never fails the deploy, whatever goes wrong. It reads with the Gemini reader. The warm-up calls the Nemotron provider (#573) only with `--reader nemotron`, by hand; start-up, the health check and the tests never call it. The service itself reads with Nemotron first (Gemini as the fallback) whenever `VERDA_INFERENCE_KEY` is set; `BILL_READER=gemini` turns that off.

## Budget and privacy
- **One request per reading not in the cache.** There is no retry and no fallback model.
- **A cached reading needs no model.** It is served even while the model may not be used (the budget is spent, a pause, the switch file): it costs no request and is not a guess. Only a reading not in the cache needs the model, and it answers 503 `model_unavailable` when the model cannot be used; the app then offers typing the fields.
- **Its own role.** `GEMINI_EXTRACT_MODEL` (default the pinned default model), `GEMINI_EXTRACT_THINKING` and `GEMINI_EXTRACT_TIMEOUT_S` set the reading's own model, thinking level and timeout. Changing the planner or composer never changes a reading's cache key. A refused extract model id (400, 404) or a run of failed readings pauses readings only. A 429 or a refused key pauses every call kind, because the key and its quota are shared.
- **Daily share.** `BILL_READ_DAILY_BUDGET` (default 50) is the readings' share of the daily model budget. A bad value is the default, with one log line, and never turns the model off.
- **Cache.** Readings are cached by the image's SHA-256 together with the model, the prompt and the schema. Only a usable reading is cached, and a cached entry the reading rejects is treated as a miss. So a bad first answer never makes a sample fail for ever. The cost: a sample the model cannot read costs one request per reading and per deploy, up to the daily share.
- **No image bytes kept.** Image bytes are never written to the cache, a recording, the ledger or a log. The cache and the recordings hold the scrubbed model response, keyed by the hash.
- **Who receives the image.** A reading not in the cache sends the bill image to the reading model's provider: Google's Gemini API, and, whenever `VERDA_INFERENCE_KEY` is set, first the Nemotron model on Verda's inference endpoint (#573). Today the only images are the four synthetic gallery bills; there is no upload.
