# Sentti design system

The design foundation for the Sentti money-coach module: a mobile web app, 375 px wide, embedded in S-mobiili through a WebView. Every screen uses these tokens and rules.

- Tokens: [`design/tokens.css`](design/tokens.css). These are CSS custom properties. Colour, type, radius, shadow and easing tokens use Tailwind v4 theme namespaces; spacing, durations, `--gutter` and `--tap-min` are mapped by hand.
- Data shapes: [`contracts/api.md`](../contracts/api.md), version 0.2.0. This file never redefines a field; it only says how to show one.
- The style is "in the spirit of" S-mobiili. It was derived only from public materials: the s-pankki.fi website and the S-mobiili listings in the App Store and Google Play. The palette, components and icons are our own. This repository contains no S-Pankki or S-Group logo, icons, images or font files.

**Status: draft.** Sections marked **TODO** are not final yet.

## 1. Principles
1. **One thought per screen.** 375 px, a 16 px gutter, no horizontal scroll. Details open in bottom sheets, not new pages.
2. **Cards carry the numbers; text explains them.** Every number is a tappable chip that leads to its transactions.
3. **Fact and estimate never look the same.** An estimate always carries the "Estimate" badge.
4. **Baskets are icon + label + colour, always together.** Colour is never the only signal.
5. **The thumb zone.** The input and the main buttons sit at the bottom. Touch targets are at least 44 × 44 px.
6. **Flat and calm.** White cards on a light green page, hairline borders, no drop shadows except on things that float.
7. **A friendly tone that never moralises.** See section 6.

## 2. Tokens

### 2.1 Colour
| Token | Value | Use |
|---|---|---|
| `--color-page` | `#F3F8F4` | Background behind everything |
| `--color-surface` | `#FFFFFF` | Cards, sheets, inputs |
| `--color-sunken` | `#EBF2ED` | Skeletons, bar tracks, the lesson box |
| `--color-line` | `#DCE6DF` | Decorative hairlines (card borders, row dividers) |
| `--color-line-strong` | `#7B8F83` | Borders that carry meaning (inputs, secondary buttons); 3:1 on white |
| `--color-ink` | `#0E3A25` | Primary text (dark green) |
| `--color-ink-2` | `#26302A` | Long body text |
| `--color-muted` | `#55635A` | Secondary text, captions, periods |
| `--color-brand` | `#00703C` | Links, action chips, the term underline, the focus ring |
| `--color-deep` | `#0B4A2E` | The "Sentti asks" card surface, the send button, user bubbles |
| `--color-mint` / `-hover` | `#8DF29A` / `#5EE97A` | Primary button background (text is `--color-ink`) |
| `--color-mint-tint` / `-line` | `#E4F5E8` / `#9FD8AB` | Number chips, suggested-question chips |
| `--color-estimate` / `-tint` | `#0B6378` / `#E2F1F5` | The "Estimate" badge |
| `--color-danger` / `-tint` | `#B3261E` / `#FDECEC` | Errors only, never spending |
| `--color-warning` / `-tint` | `#8A5300` / `#FFF2DA` | Warnings |
| `--color-up` / `--color-down` | `#00703C` / `#9A4A00` | Comparison tone, always with an arrow and words |
| `--color-scrim` | `rgba(14,58,37,.38)` | Behind bottom sheets |

**Baskets.** These are the keys from `contracts/api.md` section 1. The strong colour is used for text and bars; the tint is the chip and tile background.

| Basket | Icon | Strong | Tint |
|---|---|---|---|
| `regular_essentials` "Regular essentials" | 🏠 | `--color-basket-essentials` `#2F5DA8` | `#E8EFFA` |
| `unexpected_necessities` "Unexpected necessities" | 🔧 | `--color-basket-unexpected` `#9A4A00` | `#FFEFDA` |
| `everyday_spending` "Everyday spending" | ☕️ | `--color-basket-everyday` `#A12D68` | `#FBE8F1` |
| `unclassified` "Waiting for your answer" | ? | `--color-waiting` `#55635A` | `#EEF2EF` |

The `unclassified` state is neutral: a dashed tile, grey text and a hatched bar. It appears only while a review is pending, and it is never an answer option.

### 2.2 Contrast (WCAG 2.x AA)
Text pairs need 4.5:1. Non-text pairs (bars, meaningful borders, the focus ring) need 3:1. All 35 pairs pass. Ratios are computed from `tokens.css`.

| Foreground | Background | Use | Ratio | Needs |
|---|---|---|---|---|
| `--color-ink` `#0E3A25` | `--color-surface` `#FFFFFF` | Body text, titles | 12.72:1 | 4.5:1 |
| `--color-ink` `#0E3A25` | `--color-page` `#F3F8F4` | Text on the page background | 11.84:1 | 4.5:1 |
| `--color-ink-2` `#26302A` | `--color-surface` `#FFFFFF` | Long body text | 13.65:1 | 4.5:1 |
| `--color-muted` `#55635A` | `--color-surface` `#FFFFFF` | Secondary text | 6.33:1 | 4.5:1 |
| `--color-muted` `#55635A` | `--color-page` `#F3F8F4` | Secondary text on page | 5.89:1 | 4.5:1 |
| `--color-muted` `#55635A` | `--color-sunken` `#EBF2ED` | Lesson box, skeleton labels | 5.56:1 | 4.5:1 |
| `--color-brand` `#00703C` | `--color-surface` `#FFFFFF` | Links, action chips | 6.21:1 | 4.5:1 |
| `--color-brand` `#00703C` | `--color-page` `#F3F8F4` | Links on page | 5.78:1 | 4.5:1 |
| `--color-brand` `#00703C` | `--color-mint-tint` `#E4F5E8` | Brand text on mint tint | 5.48:1 | 4.5:1 |
| `--color-ink` `#0E3A25` | `--color-mint` `#8DF29A` | Primary button | 9.27:1 | 4.5:1 |
| `--color-ink` `#0E3A25` | `--color-mint-tint` `#E4F5E8` | Number chip, suggested-question chip | 11.22:1 | 4.5:1 |
| `--color-estimate` `#0B6378` | `--color-estimate-tint` `#E2F1F5` | Estimate badge | 5.91:1 | 4.5:1 |
| `--color-danger` `#B3261E` | `--color-danger-tint` `#FDECEC` | Error text | 5.72:1 | 4.5:1 |
| `--color-warning` `#8A5300` | `--color-warning-tint` `#FFF2DA` | Warning text | 5.72:1 | 4.5:1 |
| `--color-basket-essentials` `#2F5DA8` | `--color-basket-essentials-tint` `#E8EFFA` | 🏠 basket chip | 5.58:1 | 4.5:1 |
| `--color-basket-unexpected` `#9A4A00` | `--color-basket-unexpected-tint` `#FFEFDA` | 🔧 basket chip | 5.55:1 | 4.5:1 |
| `--color-basket-everyday` `#A12D68` | `--color-basket-everyday-tint` `#FBE8F1` | ☕️ basket chip | 5.80:1 | 4.5:1 |
| `--color-waiting` `#55635A` | `--color-waiting-tint` `#EEF2EF` | Waiting chip | 5.60:1 | 4.5:1 |
| `--color-waiting` `#55635A` | `--color-surface` `#FFFFFF` | Waiting row text | 6.33:1 | 4.5:1 |
| `--color-on-deep` `#FFFFFF` | `--color-deep` `#0B4A2E` | Review card text | 10.33:1 | 4.5:1 |
| `--color-on-deep-muted` `#BFE3CB` | `--color-deep` `#0B4A2E` | Review card secondary text | 7.41:1 | 4.5:1 |
| `--color-mint` `#8DF29A` | `--color-deep` `#0B4A2E` | Question icon on review card (non-text) | 7.53:1 | 3:1 |
| `--color-basket-essentials` `#2F5DA8` | `--color-surface` `#FFFFFF` | 🏠 bar (non-text) | 6.46:1 | 3:1 |
| `--color-basket-unexpected` `#9A4A00` | `--color-surface` `#FFFFFF` | 🔧 bar (non-text) | 6.26:1 | 3:1 |
| `--color-basket-everyday` `#A12D68` | `--color-surface` `#FFFFFF` | ☕️ bar (non-text) | 6.79:1 | 3:1 |
| `--color-line-strong` `#7B8F83` | `--color-surface` `#FFFFFF` | Borders that carry meaning (non-text) | 3.44:1 | 3:1 |
| `--color-brand` `#00703C` | `--color-surface` `#FFFFFF` | Focus ring, term underline (non-text) | 6.21:1 | 3:1 |
| `--color-ink` `#0E3A25` | `--color-danger-tint` `#FDECEC` | Error card text | 11.14:1 | 4.5:1 |
| `--color-surface` `#FFFFFF` | `--color-ink` `#0E3A25` | Toast text (white on ink) | 12.72:1 | 4.5:1 |
| `--color-mint` `#8DF29A` | `--color-ink` `#0E3A25` | Toast Undo link | 9.27:1 | 4.5:1 |
| `--color-surface` `#FFFFFF` | `--color-deep` `#0B4A2E` | User bubble, send icon | 10.33:1 | 4.5:1 |
| `--color-down` `#9A4A00` | `--color-surface` `#FFFFFF` | "Worse" tone text | 6.26:1 | 4.5:1 |
| `--color-up` `#00703C` | `--color-surface` `#FFFFFF` | "Better" tone text | 6.21:1 | 4.5:1 |
| `--color-muted` `#55635A` | `--color-mint-tint` `#E4F5E8` | Muted text on mint tint | 5.58:1 | 4.5:1 |
| `--color-ink` `#0E3A25` | `--color-estimate-tint` `#E2F1F5` | Open term highlight | 10.99:1 | 4.5:1 |

### 2.3 Type
Typeface: **Inter** (SIL OFL 1.1), self-hosted. Every amount uses tabular figures (`font-variant-numeric: tabular-nums`), so counters never jitter.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--text-xs` | 12 / 16 | 400–600 | Captions, periods, the AI disclosure, badges |
| `--text-sm` | 14 / 20 | 400–600 | Secondary lines, chips |
| `--text-base` | 16 / 24 (26 for answers) | 400 | Body text. **Inputs are never below 16 px** (iOS zooms otherwise). |
| `--text-lg` | 18 / 26 | 600–700 | Sheet titles |
| `--text-xl` | 20 / 28 | 700 | The takeaway line |
| `--text-2xl` | 24 / 30 | 700 | Greeting, secondary big numbers |
| `--text-hero` | 40 / 44 | 700, −0.02em | Safe to spend |
| `--text-stage` | 56 / 60 | 700 | Projector mode (`[data-stage]`) |

### 2.4 Spacing, radii, elevation
- **Spacing** has a 4 px base: `--space-1` 4, `-2` 8, `-3` 12, `-4` 16, `-5` 20, `-6` 24, `-8` 32, `-10` 40. `--gutter` is 16 px, `--tap-min` is 44 px.
- **Radii:** `--radius-sm` 8 (small tiles), `-md` 12 (basket tiles, boxes), `-lg` 16 (cards, answer buttons), `-xl` 20 (the review card), `-sheet` 24 (the top of bottom sheets), `-pill` (chips, buttons, inputs).
- **Elevation:** surfaces are flat, with a 1 px `--color-line` border and no shadow. `--shadow-sheet` is only for bottom sheets. `--shadow-float` is only for the flying amount (#35), toasts and popovers.

### 2.5 Motion
| Token | Value | Use |
|---|---|---|
| `--duration-fast` | 150 ms | Press states, cross-fades (reduced motion) |
| `--duration-base` | 250 ms | Sheet in and out, card collapse, toast in |
| `--duration-slow` | 500 ms | Row flash, the guess reveal |
| `--duration-money` | 900 ms | Number counters |
| `--ease-standard` | `cubic-bezier(.33,0,.34,1)` | Default |
| `--ease-entry` / `--ease-exit` | `(0,0,.3,1)` / `(.5,0,1,1)` | Things entering and leaving |
| `--ease-expressive` | `(.46,0,.19,1)` | The amount's flight between baskets |
| `--ease-spring` | `(.34,1.36,.64,1)` | Landing, check marks |

**Reduced motion** (`prefers-reduced-motion: reduce`): there is no flight and no counting. Numbers cross-fade in 150 ms, and toasts still appear.

## 3. Components

### Shell
- **Header:** 52 px, with a back chevron (44 px target), the title "Sentti" with a small "AI" tag, and the EN/FI switch. The module has no logo and no bottom navigation, because it lives inside S-mobiili.
- **Composer:** pinned to the bottom. The input is 48 px high with 16 px text; the send button is a 48 px circle in `--color-deep`. Bottom padding adds `env(safe-area-inset-bottom)`.
- **Disclosure:** the overview's `ai_disclosure`, shown as is in `--text-xs` with an info icon. It is also the first message of an empty chat.

### Basket chip and basket row
- **Chip:** a pill in the basket tint with a white circle holding the emoji, and the label in the strong colour (600).
- **Row:** a 40 px tinted tile with the emoji, the label (600), and the amount on the right (700, tabular). A 6 px bar in the strong colour on a `--color-sunken` track runs under it. The period caption ("Monthly average, April to September 2026") sits under the list.

### Number chip (evidence)
- A pill in `--color-mint-tint` with a 1 px `--color-mint-line` border, `--color-ink` text (600, tabular) and a small receipt mark.
- It shows `display` exactly as received; the app never formats numbers.
- **Tap:** opens the evidence sheet (`GET /api/evidence/{evidence_ref}`).
- **Inside running text:** the hit area extends to at least 32 px (the WCAG 2.5.8 inline exception).
- **Screen readers:** read `text_rendered` plus "show transactions".

### Glossary term (#36)
- The term is plain text with a 2 px dotted `--color-brand` underline, offset 4 px. It has no background, so it never looks like a number chip.
- **Open term:** gets a light `--color-estimate-tint` highlight.
- **Tap:** opens a short bottom sheet (at most about 46 % of the screen) with the definition and, when the glossary entry has one, the customer's own number as a number chip.

### Takeaway line
`--text-xl`, 700, `--color-ink`: one per answer. An answer never shows more than 3 emphasised spans.

### Fact vs estimate
- **Estimate:** a dashed `--color-estimate` pill with a "≈" glyph and `estimate.label`. It is a button that reveals `estimate.text`.
- **Fact:** no badge, or a quiet "From your transactions" in `--color-muted`.

### Answer card
- A white card with a 16 px radius and 16 px padding: the title (16/22, 700), the subtitle (xs, muted), and the estimate or fact marker top right.
- `metric`, `breakdown` and `whatif` share this frame.
- At most 2 card `actions`, shown as action chips under the explanation.

### Answer order
1. Takeaway (bold).
2. Card.
3. One to three sentences.
4. Action chips (outline).
5. Follow-up chips (mint).

The `lesson` sits in a `--color-sunken` box before the chips. The stream never autoscrolls: the view stays pinned to the start of the answer.

### Chips
- **Suggested question / follow-up:** `--color-mint-tint` with a `--color-mint-line` border and ink text.
- **Action:** white with a 1.5 px `--color-brand` border and brand text.
- Both are at least 44 px high, 14 px, 600.

### Evidence bottom sheet
- 24 px top radius with a grab handle; at most about 78 % of the screen, over the scrim.
- **Contents:**
  - the title and the total;
  - "N transactions · reconciles ✓";
  - a "How it was counted" box in plain words, built from `method` and `query`;
  - transaction rows (merchant label, date and time, amount in the bank sign, as received);
  - "Show all N";
  - `privacy_note` with a lock icon.

### Safe-to-spend widget
- **Top:** the title and the "Estimate" badge.
- **Middle:** the hero number (`--text-hero`) and the subtitle period. Then one sentence with "Free until payday" and the irregular reserve as number chips.
- **Bottom:** the "How is this calculated?" link. It opens a sheet that writes `components` as a sentence formula, for example "balance − bills − essentials − reserve − cushion = free until payday".
- **Safe to save** is a separate, lower card. It is never added to safe to spend.

### "Sentti asks" review card (#35)
- **Surface:** `--color-deep`, radius 20, a mint question icon and "Sentti asks". It must never look like an answer.
- **Header row:** "Not sure" sits at the right. It only closes the card, with no API call.
- **Contents:** the amount (30 px, 700, tabular); the date, category and merchant label; the `question` as is.
- **Answers:** two answer buttons side by side, white, at least 56 px high, each with a basket tile and a 4 px basket-colour stripe. Labels come from `options[].label` in the request language.
- **After a tap:**
  1. The card collapses to one line: a check, the chosen label and `options[].effect`.
  2. The amount, as a pill, flies from the "Waiting for your answer" row to the chosen basket row: 600 ms with `--ease-expressive`. Its border colour turns to the target basket's.
  3. Every changed number counts from `changes[].before` to `after` (900 ms, tabular figures), and the bars resize.
  4. The waiting row fades out. "was …" hints stay for 6 s.
  5. A toast shows `message.text_rendered`, with number tokens as chips, and an Undo button. Undo sends `basket: null` and counts everything back.
- **No reload:** the overview is refetched in the background after the animation.
- **Expiry:** a pending review expires 7 days after creation; after that its `tx_ref` returns 404 `tx_ref_not_found`. The app then removes the card quietly and shows no error.
- **Direction of change:** "It was needed" lowers safe to spend, and the hero then shows a grey down arrow with "was €…" and the reserve line. "I chose it" leaves safe to spend unchanged ("stays the same"). Red is never used for this.

### Guess first (#37)
- The number is blurred (10 px) and hidden from screen readers. Four range chips (for example €50 / €100 / €200 / €300+), "Skip, just show me" and "Reveal".
- **Reveal:** two bars grow from 0 over 500 ms: "Your guess" (hatched) and "Actual" (solid brand), with neutral copy.
- At most one per screen. Never used for safe to spend, Health or other sensitive categories.

### What-if slider
- The track has a 44 px hit area, a 6 px line and a 28 px thumb, in steps of 5 %.
- The result is in `--text-2xl`, with per month, week and year below, and the "Estimate" badge.
- The previous value stays until the new response arrives.

### Persona picker (demo only)
- **Opens:** with a long-press (600 ms) on the header title, or with `?persona=`.
- **Contents:** a bottom sheet titled "Demo personas", plus a stage mode switch (`data-stage` on the root, which swaps in `--text-stage`) and "Reset reviews".

### States
| State | Rule |
|---|---|
| Loading | Stage lines from `status` events, using their `label`. Done stages get a check, and the current one a spinner. A card skeleton appears at once. The send button becomes a stop button. |
| Empty | An empty chat is never "Ask me anything". It says what Sentti can and can't do, shows the disclosure and 3 question chips, near the thumb. |
| Error | A `--color-danger-tint` card with `error.message` as is. "Try again" appears only when `retryable` is true. |
| Clarify | `clarify.question` in the takeaway style and `clarify.options` as chips that send at once. Typing still works. |
| Off-topic / refusal | A normal bubble with a grey left rule, `refusal.label` in xs, the template text and the `follow_ups` chips. |
| Fallback | `outcome: "fallback"`: the same cards and the template line, plus one quiet note that the written explanation is unavailable and the numbers come from the transactions. |

## 4. Numbers and language
- **The app never formats or translates numbers.** It shows `display` and the localised labels from the API. EN looks like `€1,080.42`, FI like `1 080,42 €`.
- **Signs:** amounts never get a plus sign. Changes use an arrow and words ("was €221.58", "▲ €91.70").
- **Language:** the EN/FI switch sets `?lang=` and `language`. Long Finnish words wrap inside chips and never truncate.

## 5. Accessibility and WebView
- **Contrast:** all text pairs meet AA (section 2.2). Colour is never the only signal (WCAG 1.4.1).
- **Focus:** a 3 px `--color-brand` outline with a 2 px offset.
- **Targets:** at least 44 px; inline chips get a padded hit area.
- **Viewport:** `viewport-fit=cover`, safe-area padding on the composer and sheets, and height from `100dvh` minus `env(safe-area-inset-bottom)`.
- **No service worker in production:** WKWebView does not run it. Mock data is for development only.
- **Larger Text:** WKWebView ignores the system setting. **TODO:** decide on an in-app text-size option.

## 6. Tone of voice
- Short, friendly, second person ("you"), no jargon. One idea per sentence.
- No moralising and no shame. Say "everyday spending", never "leakage". When a guess was low, say "Most people underestimate this one". When it was high, say "Less than you thought. Good to know where you stand".
- Say what Sentti can do before the user asks; refuse briefly and offer what it can do instead.
- AI texts come from the core. The app's own strings (buttons, empty states) follow the same rules.

## 7. Licences
Only MIT-compatible material goes into `app/`.

| Item | Licence | Decision | Notes |
|---|---|---|---|
| Inter (typeface) | SIL OFL 1.1 | Use | Self-host through `@fontsource/inter` (package MIT, font OFL). Keep the OFL text with the font files. |
| shadcn/ui | MIT | Use | Components are copied in. |
| Vercel AI Elements | Apache-2.0 | Use with care | Compatible. Keep `LICENSE`/`NOTICE` and mark modified files. Upstream announced its deprecation for the end of November 2026 in favour of shadcn/ui copy-in patterns; prefer those. |
| 21st.dev blocks | Per component, no default | **TODO** | Check each block before use. "Unknown" means rejected. |
| S Bonus UX / S Bonus Display | Proprietary (S Group) | Rejected | Replaced by Inter. |
| S-Pankki / S-Group logos, icons, images | Proprietary | Rejected | None in the repo. Basket icons are system emoji, and line icons are our own inline SVG. |

## 8. TODO
- Final component code (shadcn/ui based) and the mapping of `tokens.css` into the Tailwind `@theme`.
- Finnish basket names and glossary texts from the core (contract 0.2, #34).
- The 21st.dev licence review once blocks are chosen.
- An in-app text-size option for WKWebView (section 5).
