# Sentti app

Sentti is an embeddable web module for S-mobiili, 375 px, inside a WebView. It opens on this week's safe to spend, the three spending baskets and questions to ask; the chat-first thread is specified in `DESIGN.md` section 3. Every number is a chip that opens how it was calculated.

Stack: Vite, React, TypeScript and Tailwind CSS. The build is static. In production it is served from the same host as the core, so the API is `/api` on the same origin.

## Run

Node 20.19+ or 22.12+ (Vite's requirement). From this folder:

```
npm ci
npm run dev          # http://localhost:5173, mock data
npm run build        # static bundle in dist/
npm run lint
npm run typecheck
npm run test         # unit tests (vitest): the /api/ask stream parser on the contract's examples
```

### Demo-path check

`npm run demo:check -- <base-url> [--lang en|fi] [--persona CUST00860]` walks the 60-second path of `docs/demo-script.md` in a headless Chromium (`playwright-core`). It prints one PASS, FAIL or SKIP line per step, and exits 0 only when no step fails. It uses a local Chrome or chrome-headless-shell, or the one in `DEMO_CHECK_BROWSER=<path>`, and never downloads a browser. CI does not run it.

- Dev host: `npm run demo:check -- https://sentti.jeremyxd.dev`. Each run asks the coach two questions, so do not loop it.
- Local mock build: `VITE_API_MODE=mock npm run build && npm run preview`, then `npm run demo:check -- http://localhost:4173`.

### Mock and live mode

`VITE_API_MODE` picks the API client at build time (see `.env.example`):

| Mode | What it does |
|---|---|
| `mock` (default) | Serves the examples of `contracts/api.md` from `src/api/mock/contract-examples.json`. No network and no service worker, so it also runs in iOS WKWebView. |
| `live` | Calls the core at `/api` on the same origin. |

```
npm run dev                                                      # mock
VITE_API_MODE=live VITE_API_PROXY=http://localhost:8000 npm run dev   # live, /api proxied to a local core
VITE_API_MODE=live npm run build                                 # live build, served next to the core
```

After `contracts/api.md` changes, refresh the mock data with `npm run mocks:sync`.

What mock mode has, and what it does not invent:
- Personas: the contract's list, plus Sanna (CUST00860, the demo start) from `core/config/personas.yaml`.
- Overviews: Sanna (pending review) and Aino (CUST00042). Other personas get the contract's `customer_not_found` error. `?mock=no_hero` serves Aino the contract's `overview.response_no_hero` (`hero: null`).
- Evidence: the two contract examples; the safe-to-spend parts and the review purchase, built from the overview's own data. Other numbers show their method with a note that the contract has no example for them yet.
- Review answers (`POST /api/baskets/label`): the contract's label examples. "It was needed", "I chose it", undo, the same answer twice (`changed: false`) and a basket that is not an option (422) all work. The mock remembers the answer until the page reloads: the next overview has the example's `after` numbers, no review card and no waiting row. Undoing "I chose it" has no contract example, so it is that example run backwards. The basket shares in that overview are each basket amount over the total, as the core counts them; the contract has no example of the overview after an answer.
- Chat (`POST /api/ask`): the contract's examples as a `text/event-stream` byte stream with realistic delays, read by the same parser as live mode. The contract's refusal question (or any question about stocks or investing), its clarify question ("How much did I spend?") and its Finnish question get their examples, turned into stream events; every other question gets the full stream example. `?mock=error` plays the error-stream example, `?mock=template` a model-off answer (the full stream's card, the contract's template line "Here is what I found for September.", outcome `answered` with the `llm_unavailable` warning, which shows the template note), `?mock=fallback` a fallback answer (the same card with the core's fixed short text "I could not find data for that question.", outcome `fallback`, no note), and `?mock=slow` makes every delay four times longer. Unknown personas get `customer_not_found` before the stream.
- `?mock=review` (#450) adds the contract's `card.review` to the full stream's answer. While the opening shows that question, the answer shows only "Sentti already asked about this purchase." and "Show"; after "Not sure" in the opening, the answer shows the review card itself, answerable in the thread (Sanna, `CUST00860`).
- Contract 0.3.3 in the chat (#439): the first answer of a conversation carries the AI disclosure, later answers do not. `?mock=refusal` answers any question with the first-answer refusal (`ask.json.response_refusal_first`): the disclosure and the "Contact S-Pankki" chip, which hands over `sentti.openHostScreen` with `{target: "contact_bank"}`. The contract's refusal question gets the same on a conversation's first answer.
- What-if: the contract's one example (Restaurants, 20%). The mock scales the contract example for other cuts by the contract's rule (the saving is the cut of the baseline; per week × 7 / 30.4375, per year × 12), so 20% gives the example's numbers exactly, and writes the amounts in the request language like the core (`€53.68 a month` / `53,68 € / kk`). Any other selection answers 422 `invalid_scenario` with the contract's message, in English or Finnish.
- The examples are English only. With `?lang=fi`, the app's own texts and the review question switch to Finnish; the API texts stay as served.

### The review card ("Sentti asks", #35)

Open Sanna (`?persona=CUST00860`, the default in mock mode). Answer one of the two options, then press Undo in the toast; "Not sure" only closes the card. Reload the page to start again. The question and the answers are the API's texts (`question[lang]`, `options[].label[lang]`); `{{n1}}` and `{{date}}` in the question become chips of the card's amount and date. On the live core the answers are kept per viewer session (a cookie the core sets), so a fresh private window starts from the pending question.

## URLs

| URL | Shows |
|---|---|
| `/` | The thread: Sentti's opening turn (the overview), then the questions and answers on the `/api/ask` stream, with the composer at the bottom |
| `/?q=<question>` | The thread sends `<question>` at once, then drops `q` from the URL. The question chips and the cards' ask actions set it on `/` by replacing the entry, so asking adds no history entry. |
| `/chat` | An old link: redirects to `/` (the query kept) by replacing the entry, so Back never returns to it |
| `?evidence=<ref>` | The evidence sheet over the current screen. Back closes it. |
| `?whatif=<kind>:<value>&cut=<pct>` | The what-if sheet, for example `?whatif=category:Restaurants&cut=20`. `kind` is `category`, `basket`, `mcc` or `merchant`; `cut` is a whole percentage from 1 to 100 (20 if missing). Releasing the slider updates `cut`. Back closes it. |
| `?persona=<customer_id>` | Demo persona. A long press on the header opens the persona and language switch. |
| `?lang=en` or `?lang=fi` | Language |

The static host must answer unknown paths (such as `/chat`) with `index.html`.

## Layout rules

- 375 px first, no horizontal scroll, `viewport-fit=cover` with safe-area insets.
- Touch targets at least 44 px, inputs at least 16 px.
- No own bottom navigation and no logo: a minimal header with back and "Sentti". Details open as bottom sheets.
- Every number shows the API's `display` string unchanged; the app never recomputes totals. After a review answer, changed numbers count from `changes[].before` to `after`. The frames in between are animation only, and the last frame is the API's `display`. With reduced motion there is no counting.

## Design tokens

The app uses `design/tokens.css` directly (rules in `DESIGN.md`). `src/index.css` imports it, and `@theme inline` there maps the colour, font, radius and shadow tokens to Tailwind utilities (`bg-page`, `text-ink`, `bg-hero`, `rounded-lg`, …), so a change in the token file changes the look without touching components. The font is Figtree (SIL OFL 1.1) from `@fontsource/figtree`, bundled with the app in weights 400, 500, 600 and 700.
