# Sentti app

The mobile web module of Sentti: a 375 px wide app that runs inside the bank's mobile app (a WebView). It opens on the overview: this week's safe to spend, the three spending baskets and questions to ask. Every number is a chip that opens how it was calculated.

Stack: Vite, React, TypeScript and Tailwind CSS. The build is static. In production it is served from the same host as the core, so the API is `/api` on the same origin.

## Run

Node 20.19+ or 22.12+ (Vite's requirement). From this folder:

```
npm ci
npm run dev          # http://localhost:5173, mock data
npm run build        # static bundle in dist/
npm run lint
npm run typecheck
```

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
- Overviews: Sanna (pending review) and Aino (CUST00042). Other personas get the contract's `customer_not_found` error.
- Evidence: the two contract examples; the safe-to-spend parts and the review purchase, built from the overview's own data. Other numbers show their method with a note that the contract has no example for them yet.
- What-if: the contract's one example (Restaurants, 20%). The mock scales the contract example for other cuts by the contract's rule (the saving is the cut of the baseline; per week × 7 / 30.4375, per year × 12), so 20% gives the example's numbers exactly, and writes the amounts in the request language like the core (`€53.68 a month` / `53,68 € / kk`). Any other selection answers 422 `invalid_scenario` with the contract's message, in English or Finnish.
- The examples are English only. With `?lang=fi`, the app's own texts and the review question switch to Finnish; the API texts stay as served.

## URLs

| URL | Shows |
|---|---|
| `/` | Overview |
| `/chat?q=<question>` | Chat (placeholder until the stream issue) |
| `?evidence=<ref>` | The evidence sheet over the current screen. Back closes it. |
| `?whatif=<kind>:<value>&cut=<pct>` | The what-if sheet, for example `?whatif=category:Restaurants&cut=20`. `kind` is `category`, `basket`, `mcc` or `merchant`; `cut` is a whole percentage from 1 to 100 (20 if missing). Releasing the slider updates `cut`. Back closes it. |
| `?persona=<customer_id>` | Demo persona. A long press on the header opens the persona and language switch. |
| `?lang=en` or `?lang=fi` | Language |

The static host must answer unknown paths (such as `/chat`) with `index.html`.

## Layout rules

- 375 px first, no horizontal scroll, `viewport-fit=cover` with safe-area insets.
- Touch targets at least 44 px, inputs at least 16 px.
- No own bottom navigation and no logo: a minimal header with back and "Sentti". Details open as bottom sheets.
- Every number shows the API's `display` string unchanged; the app never recomputes totals.

## Design tokens

The app uses `design/tokens.css` directly (rules in `DESIGN.md`). `src/index.css` imports it, and `@theme inline` there maps the colour, font, radius and shadow tokens to Tailwind utilities (`bg-page`, `text-ink`, `bg-hero`, `rounded-lg`, …), so a change in the token file changes the look without touching components. The font is Figtree (SIL OFL 1.1) from `@fontsource/figtree`, bundled with the app in weights 400, 500, 600 and 700.
