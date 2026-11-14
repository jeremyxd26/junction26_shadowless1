# Sample bills (synthetic)

Four invoices for the demo gallery (#249). In the demo a visitor picks one of these; a visitor's own bill is never sent anywhere.

**Everything here is synthetic test data:**
- **Companies:** fictional ("Esimerkki ... Oy", from the table of known payee names of the bill explanation, #242).
- **People and places:** a fictional payer, and addresses with the postal code 00000, which does not exist.
- **Left out:** no brand, logo, phone number or business id.
- **IBANs are test values.** Their bank part is `0000`, and no Finnish monetary institution code begins with 0 (Finance Finland, *Finnish Monetary Institution Codes and BICs*, 16.3.2026), so they belong to no account. Their check digits are correct.

| Sample | Language | Payee | Amount | Due date | Payment data | Warning signs for CUST00860 on 2026-09-30 |
|---|---|---|---|---|---|---|
| `sample_1` | fi | Esimerkki Asunnot Oy | €836.65, the usual Housing amount | 8.10.2026 | barcode version 4 | none |
| `sample_2` | fi | Esimerkki Energia Oy | €312.70, at least 150% of the usual €186.40 for Utilities | 13.10.2026 | barcode version 4 | `amount_above_usual` |
| `sample_3` | fi | Esimerkki Remontti Oy | €486.00 | 2.10.2026, a 3-day term | RF reference, barcode version 5 | `new_payee`, `short_term` |
| `sample_4` | en | Esimerkki Vesi Oy | €42.75 | 20.10.2026 | the reference's check digit is wrong; no barcode | `reference_check_failed` |

The warning signs are those of `contracts/api.md` section 11.2.

**Files:**
- `sample_N.png`: 1200 px wide. The service serves it (`GET /api/bill/samples`).
- `sample_N.pdf`: the same page as a one-page PDF.
- `samples.json`: the answer key. `truth` holds the true fields, `checks` what the validators of `core/bills/parse.py` say, and `signals` the expected warning signs. It is for tests and for checking a reading (#250); no endpoint returns the true fields.

**Regenerate** with `python scripts/make_sample_bills.py`. It needs Pillow, a development dependency, and the header of the script explains the fonts. The test `core/bills/tests/test_bills_samples.py` checks every value against the parser.
