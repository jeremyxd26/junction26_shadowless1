# Sentti financial-literacy corpus (RAG-ready)

Built from the verified research catalogue (Finnish official courses, curricula, materials and open
datasets for every age group, in English and Finnish) plus numbers fetched live from Statistics Finland. Every file is JSON Lines,
one record per line, with a JSON Schema in `schema/`. Nothing here is lesson text: lessons stay human-written
(EN/FI) as in `core/agent/template.py` and the Learn tab. The corpus is what a retriever searches to pick and
ground them.

| File | One record is | Use it for |
|---|---|---|
| `sources.jsonl` | a source (course, guide, curriculum, dataset), deduplicated | the registry: links, licence, tier, ages, topics, where to get the data |
| `chunks.jsonl` | a retrievable unit in **one** language (`en` or `fi`) | the index: embed `text`, filter on metadata |
| `facts.jsonl` | one typed number (value, unit, period, age group) with its PxWeb query | numbers in lessons: render from the record, never from model text |
| `manifest.json` | counts, input hash, skipped items, validation result | checking a build |
| `fact_specs.json` | the PxWeb queries behind `facts.jsonl` | adding or changing benchmark tables |

## Chunk kinds

- `source_card`: our templated description of a source (name, publisher, type, ages, topics, languages, link),
  EN and FI. Exists for every source. Holds no text copied from the source.
- `page_text`: the source's own text, split at headings into chunks of about 1,100 characters. Only sources
  whose `licence_class` is `open_attribution`. Each chunk keeps its `section`, `position` and `attribution`.
- `fact`: one Statistics Finland number as a sentence, EN and FI, with `fact_id` pointing to `facts.jsonl`.

## Fields used for filtering and ranking

The names follow `core/agent/sbank_kb.Entry` (`id`, `topic`, `source_url`, `retrieved_at`, `keywords.en/fi`),
so a retriever can stand behind a `find_*_entry()` lookup like the S-Bank knowledge base does.

- `lang`: `en` or `fi`, the app's languages (like S-Pankki). Filter `lang == request.lang`. Courses that exist only
  in Swedish are left out (listed in `manifest.json` under `skipped`).
- `age_bands`: app bands `0-12, 13-17, 18-24, 25-34, 35-44, 45-54, 55-64, 65-74, 75+`, or `all`.
  Filter `user_band in age_bands or "all" in age_bands`. Native labels are kept (`age_bands_native` on
  sources, `age_native` on facts). Mapping: a native range covers an app band when it overlaps at least half
  of it (`30-49` → `25-34, 35-44, 45-54`); `75-84` and `85-` → `75+`; household tables use a floor of 17–18,
  so a reference person `-24` is `18-24`.
- `topics` / `topic`: the controlled tags (budgeting, three_baskets_fixed_variable, small_purchases,
  emergency_buffer, saving_goals, ...); `topic` is the first known one. `keywords.en/fi` are the tags' labels.
- `lesson_keys`: the existing lesson keys a source supports (`safety_buffer`, ...) or ideas as `new:<slug>`.
- `priority` (0–1): the ranking prior. `tier weight × verification confidence`. Tier weights: authority 1.0,
  public_education 0.95, international_org 0.85, academic 0.8, nonprofit 0.7, industry_association 0.6,
  bank 0.6, other 0.4. Confidence: high 1.0, medium 0.85, low 0.6. `official` is true for authority and
  public_education. A simple final score: `similarity × (0.5 + 0.5 × priority)`.
- `licence_class`: what may be shown or stored (below).

## Licence classes

Set by rules from the licence text the verifier copied from the publisher's site; the verbatim text stays in
`sources.licence`. The narrower restriction wins.

| Class | Meaning | Stored here |
|---|---|---|
| `open_attribution` | CC BY 4.0, CC0, or the publisher's explicit free reuse (Statistics Finland, THL, Kela open data, InfoFinland, Suomi.fi, vero.fi guidance) | text and numbers, with `attribution` |
| `open_share_alike` | CC BY-SA | card only (share-alike does not fit an MIT repository) |
| `noncommercial_only` | CC BY-NC(-ND) or terms limited to private/non-commercial use | card only |
| `terms_allow_reuse` | site terms let you use text with the source named, no formal licence (KKV, Kela, ETK) | card only; candidates to ask |
| `registration_required` | data behind registration or an application (FSD class B) | card only |
| `all_rights_reserved` | © with only the statutory quotation right | card only |
| `not_stated` | nothing found | card only |

Validation fails the build (exit 1) on a `page_text` chunk outside `open_attribution` and on Cyrillic in a
chunk. Russian team notes stay in the research catalogue and are not part of the corpus.

## Facts

Each fact keeps the exact `query` POSTed to `api_url` (PxWeb v1, json-stat2), so any number can be re-fetched
and checked. `value` is the number, `unit` the PxWeb unit, `period` the year/month/quarter, `dims` every other
variable with EN and FI labels. Tables: household consumption by age (14q4, already used in
`core/config/national_context.yaml`), background and income by age (14q9, 12eb), wealth and debt (151s, 15j6,
158a), enforcement and debt restructuring (11q7, 11hu), saving ability and unexpected expenses (132d, 13iu),
housing costs (12g9), consumer confidence (11vq), rents in large cities (15fc), internet banking use (13ud),
inflation (122p). Add a table by appending to `fact_specs.json` with codes from its metadata
(`GET <base>/en/<table>`).

## How it was made and how to load it

The files were generated on 2026-11-15 from a verified research run (every URL opened, licence copied from the
publisher's site) and live numbers from the Statistics Finland PxWeb API; `fact_specs.json` holds the PxWeb
queries behind `facts.jsonl`. They are data: edit them only by regenerating. Load them into PostgreSQL with
`python -m core.finlit.ingest` (see `core/finlit/README.md`).

## Not included

No embeddings, vector store or retriever code, and no lesson texts. Course pages under copyright are
pointers, not text: to quote one in a lesson, paraphrase and link.
