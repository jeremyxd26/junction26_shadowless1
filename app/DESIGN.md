# Sentti design system

The design foundation for the Sentti money-coach module: an embeddable web module for S-mobiili, 375 px, inside a WebView. Its first screen is one chat thread that Sentti opens (section 3, "Thread"). Every screen uses these tokens and rules.

- Tokens: [`design/tokens.css`](design/tokens.css). These are CSS custom properties. Colour, type, radius, shadow and easing tokens use Tailwind v4 theme namespaces; spacing, durations, `--gutter` and `--tap-min` are mapped by hand.
- Data shapes: [`contracts/api.md`](../contracts/api.md), version 0.3.2 (draft, on `dev`). This file never redefines a field; it only says how to show one.
- The style is "in the spirit of" S-mobiili. It was derived only from public materials: the s-pankki.fi website and the S-mobiili listings in the App Store and Google Play. Colour values follow that look closely (the greens, neutrals and page tint of S-mobiili); the components and icons are our own. This repository contains no S-Pankki or S-Group logo, icons, images or font files.

Component code and screens are built in their own issues and follow these rules. Section 8 lists what is still owed by other issues.

## 1. Principles
1. **One thought per screen.** 375 px, a 16 px gutter, no horizontal scroll. Details open in bottom sheets, not new pages.
2. **Cards carry the numbers; text explains them.** Every number is a tappable chip that leads to its transactions.
3. **Fact and estimate never look the same.** An estimate always carries the "Estimate" badge.
4. **Baskets are icon + label + colour, always together.** Colour is never the only signal.
5. **The thumb zone.** The input and the main buttons sit at the bottom. Touch targets are at least 44 × 44 px.
6. **Flat and calm, like S-mobiili.** White cards with a thin neutral border on a light green page, no shadows on cards. One strong green carries the brand; text is near black.
7. **A friendly tone that never moralises.** See section 6.

## 2. Tokens

### 2.1 Colour
| Token | Value | Use |
|---|---|---|
| `--color-page` | `#EBF7EC` | Light green page behind everything |
| `--color-surface` | `#FFFFFF` | Cards, sheets, inputs (flat, 1 px `--color-line` border) |
| `--color-sunken` | `#F5F5F5` | Skeletons, bar tracks, the lesson box (inputs use `--color-surface`) |
| `--color-line` | `#E6E6E6` | Thin neutral card border and row dividers (decorative) |
| `--color-line-strong` | `#808080` | Borders that carry meaning (inputs, secondary buttons); 3:1 on white and on the page |
| `--color-ink` | `#004628` | Key figures, takeaways, amounts (darkest green) |
| `--color-ink-2` | `#1F1F1F` | Body text (near black) |
| `--color-muted` | `#666666` | Meta text: captions, periods, dates |
| `--color-brand` | `#007841` | Bold titles, row labels, chevrons, pictograms, links, action chips, the term underline, the focus ring on light surfaces |
| `--color-deep` | `#004628` | The "Sentti asks" card surface, the send button, user bubbles |
| `--color-hero` / `--color-on-hero` / `--color-on-hero-muted` | `#007841` / `#FFFFFF` / `#D2FCD5` | The safe-to-spend block: white figures on green |
| `--color-on-deep` / `--color-on-deep-muted` | `#FFFFFF` / `#D2FCD5` | Text on `--color-deep` |
| `--color-mint` / `-hover` | `#91FA9B` / `#49F37B` | Primary button background (text is `--color-ink`) |
| `--color-mint-tint` / `-line` | `#D2FCD5` / `#99D59F` | Number chips, suggested-question chips |
| `--color-estimate` / `-tint` | `#363636` / `#F5F5F5` | The "Estimate" badge: neutral and dashed, so it never looks like a basket |
| `--color-danger` / `-tint` | `#B70000` / `#FFEDED` | Errors only, never spending |
| `--color-warning` / `-tint` | `#885600` / `#FFF1D8` | Warnings (rare; the same amber as ☕️, always with an icon and words) |
| `--color-up` / `--color-down` | `#007841` / `#885600` | Comparison tone, always with an arrow and words |
| `--color-scrim` | `rgba(31,31,31,.40)` | Behind bottom sheets |

**Baskets.** These are the keys from `contracts/api.md` section 1. The hues come from the same palette as the rest of the app (green, teal, amber), so no basket looks foreign. The strong colour is used for text and bars; the tint is the chip and tile background.

| Basket | Icon | Strong | Tint |
|---|---|---|---|
| `regular_essentials` "Regular essentials" | 🏠 | `--color-basket-essentials` `#007841` | `#EBF7EC` |
| `unexpected_necessities` "Unexpected necessities" | 🔧 | `--color-basket-unexpected` `#006E87` | `#E0F4FF` |
| `everyday_spending` "Everyday spending" | ☕️ | `--color-basket-everyday` `#885600` | `#FFF1D8` |
| `unclassified` "Waiting for your answer" | ? | `--color-waiting` `#666666` | `#F5F5F5` |

The 🏠 tint equals the page tint, so a 🏠 tile always sits on a white card, never directly on the page. The 🏠 strong colour equals `--color-brand`, so a 🏠 bar or chip is never shown without its icon and label; other green bars (such as "Actual" in guess first) use `--color-ink`. The `unclassified` state is neutral: a dashed tile, grey text and a hatched bar. It appears only while a review is pending, and it is never an answer option.

### 2.2 Contrast (WCAG 2.x AA)
Text pairs need 4.5:1. Non-text pairs (bars, meaningful borders, focus rings, chevrons) need 3:1. All 46 rows pass (42 distinct colour pairs; a pair used for two purposes is listed once per use). Ratios are computed from `tokens.css`. `--color-brand` on `--color-deep` is only 1.97:1 (and invisible on `--color-hero`), so the focus ring on dark surfaces is `--color-mint`.

| Foreground | Background | Use | Ratio | Needs |
|---|---|---|---|---|
| `--color-ink` `#004628` | `--color-surface` `#FFFFFF` | Key figures, takeaways, amounts | 11.01:1 | 4.5:1 |
| `--color-ink` `#004628` | `--color-page` `#EBF7EC` | Key figures on the page | 9.99:1 | 4.5:1 |
| `--color-ink-2` `#1F1F1F` | `--color-surface` `#FFFFFF` | Body text | 16.48:1 | 4.5:1 |
| `--color-ink-2` `#1F1F1F` | `--color-page` `#EBF7EC` | Body text on the page | 14.95:1 | 4.5:1 |
| `--color-muted` `#666666` | `--color-surface` `#FFFFFF` | Meta text | 5.74:1 | 4.5:1 |
| `--color-muted` `#666666` | `--color-page` `#EBF7EC` | Meta text on the page | 5.21:1 | 4.5:1 |
| `--color-muted` `#666666` | `--color-sunken` `#F5F5F5` | Lesson box, skeleton labels | 5.27:1 | 4.5:1 |
| `--color-brand` `#007841` | `--color-surface` `#FFFFFF` | Bold titles, row labels, links, action chips | 5.58:1 | 4.5:1 |
| `--color-brand` `#007841` | `--color-page` `#EBF7EC` | Titles and links on the page | 5.06:1 | 4.5:1 |
| `--color-brand` `#007841` | `--color-mint-tint` `#D2FCD5` | Brand text on mint tint | 4.95:1 | 4.5:1 |
| `--color-ink` `#004628` | `--color-mint` `#91FA9B` | Primary button | 8.58:1 | 4.5:1 |
| `--color-ink` `#004628` | `--color-mint-hover` `#49F37B` | Primary button, hover | 7.55:1 | 4.5:1 |
| `--color-ink` `#004628` | `--color-mint-tint` `#D2FCD5` | Number chip, suggested-question chip | 9.77:1 | 4.5:1 |
| `--color-on-hero` `#FFFFFF` | `--color-hero` `#007841` | Safe-to-spend figure on the green block | 5.58:1 | 4.5:1 |
| `--color-on-hero-muted` `#D2FCD5` | `--color-hero` `#007841` | Secondary text on the green block | 4.95:1 | 4.5:1 |
| `--color-on-hero-muted` `#D2FCD5` | `--color-hero` `#007841` | Down arrow and "was €…" after a review answer (#35) | 4.95:1 | 4.5:1 |
| `--color-on-deep` `#FFFFFF` | `--color-deep` `#004628` | Review card text, user bubble | 11.01:1 | 4.5:1 |
| `--color-on-deep-muted` `#D2FCD5` | `--color-deep` `#004628` | Review card secondary text | 9.77:1 | 4.5:1 |
| `--color-estimate` `#363636` | `--color-estimate-tint` `#F5F5F5` | Estimate badge | 11.08:1 | 4.5:1 |
| `--color-estimate` `#363636` | `--color-surface` `#FFFFFF` | Estimate badge border/text on a card | 12.08:1 | 4.5:1 |
| `--color-danger` `#B70000` | `--color-danger-tint` `#FFEDED` | Error text | 6.17:1 | 4.5:1 |
| `--color-ink` `#004628` | `--color-danger-tint` `#FFEDED` | Error card body text | 9.75:1 | 4.5:1 |
| `--color-warning` `#885600` | `--color-warning-tint` `#FFF1D8` | Warning text | 5.57:1 | 4.5:1 |
| `--color-basket-essentials` `#007841` | `--color-basket-essentials-tint` `#EBF7EC` | 🏠 basket chip | 5.06:1 | 4.5:1 |
| `--color-basket-unexpected` `#006E87` | `--color-basket-unexpected-tint` `#E0F4FF` | 🔧 basket chip | 5.18:1 | 4.5:1 |
| `--color-basket-everyday` `#885600` | `--color-basket-everyday-tint` `#FFF1D8` | ☕️ basket chip | 5.57:1 | 4.5:1 |
| `--color-waiting` `#666666` | `--color-waiting-tint` `#F5F5F5` | Waiting chip | 5.27:1 | 4.5:1 |
| `--color-waiting` `#666666` | `--color-surface` `#FFFFFF` | Waiting row text | 5.74:1 | 4.5:1 |
| `--color-up` `#007841` | `--color-surface` `#FFFFFF` | "Better" tone text | 5.58:1 | 4.5:1 |
| `--color-down` `#885600` | `--color-surface` `#FFFFFF` | "Worse" tone text | 6.22:1 | 4.5:1 |
| `--color-surface` `#FFFFFF` | `--color-ink` `#004628` | Toast text (white on ink) | 11.01:1 | 4.5:1 |
| `--color-basket-essentials` `#007841` | `--color-surface` `#FFFFFF` | 🏠 bar (non-text) | 5.58:1 | 3:1 |
| `--color-basket-unexpected` `#006E87` | `--color-surface` `#FFFFFF` | 🔧 bar (non-text) | 5.87:1 | 3:1 |
| `--color-basket-everyday` `#885600` | `--color-surface` `#FFFFFF` | ☕️ bar (non-text) | 6.22:1 | 3:1 |
| `--color-basket-essentials` `#007841` | `--color-sunken` `#F5F5F5` | 🏠 bar on its track (non-text) | 5.12:1 | 3:1 |
| `--color-basket-unexpected` `#006E87` | `--color-sunken` `#F5F5F5` | 🔧 bar on its track (non-text) | 5.38:1 | 3:1 |
| `--color-basket-everyday` `#885600` | `--color-sunken` `#F5F5F5` | ☕️ bar on its track (non-text) | 5.70:1 | 3:1 |
| `--color-ink` `#004628` | `--color-sunken` `#F5F5F5` | Guess-first "Actual" bar on its track (non-text) | 10.10:1 | 3:1 |
| `--color-line-strong` `#808080` | `--color-surface` `#FFFFFF` | Meaningful borders (non-text) | 3.95:1 | 3:1 |
| `--color-line-strong` `#808080` | `--color-page` `#EBF7EC` | Meaningful borders on the page (non-text) | 3.58:1 | 3:1 |
| `--color-brand` `#007841` | `--color-surface` `#FFFFFF` | Focus ring, term underline, chevrons (non-text) | 5.58:1 | 3:1 |
| `--color-brand` `#007841` | `--color-page` `#EBF7EC` | Focus ring on the page (non-text) | 5.06:1 | 3:1 |
| `--color-mint` `#91FA9B` | `--color-deep` `#004628` | Focus ring on the review card, user bubble, send button (non-text) | 8.58:1 | 3:1 |
| `--color-mint` `#91FA9B` | `--color-hero` `#007841` | Focus ring on the safe-to-spend block (non-text) | 4.35:1 | 3:1 |
| `--color-mint` `#91FA9B` | `--color-ink` `#004628` | Focus ring on the toast (non-text) | 8.58:1 | 3:1 |
| `--color-on-deep-muted` `#D2FCD5` | `--color-deep` `#004628` | Question icon on the review card (non-text) | 9.77:1 | 3:1 |

### 2.3 Type
Typeface: **Figtree** (SIL OFL 1.1), self-hosted, through `--font-sans` (Figtree, then the system UI fonts). It was chosen from three open fonts set side by side with the S-mobiili UI font (S Bonus UX, proprietary): Inter is wider and more technical; Nunito Sans is softer; Figtree is closest in width and letter shapes (two-storey a, round friendly bowls) and has tabular figures. Every amount uses tabular figures (`font-variant-numeric: tabular-nums`), so counters never jitter.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--text-xs` | 12 / 16 | 400–600 | Captions, periods, the AI disclosure, badges |
| `--text-sm` | 14 / 20 | 400–600 | Secondary lines, chips |
| `--text-base` | 16 / 24 | 400 | Body text. **Inputs are never below 16 px** (iOS zooms otherwise). |
| `--text-answer` | 16 / 26 | 400 | Coach answer text (looser leading for longer reading) |
| `--text-lg` | 18 / 26 | 600–700 | Sheet titles |
| `--text-xl` | 20 / 28 | 700 | The takeaway line; the greeting, one line (600) |
| `--text-card-title` | 17 / 22 | 700, `--color-brand` | Card titles and row labels (bold green, as in S-mobiili) |
| `--text-review-amount` | 30 / 34 | 700, tabular | The amount on the review card (#35) |
| `--text-2xl` | 24 / 30 | 700 | Secondary big numbers |
| `--text-hero` | 40 / 44 | 700, −0.02em, `--color-on-hero` | Safe to spend, white on the green block |
| `--text-stage` | 56 / 60 | 700 | Reserved; no screen uses it yet |

### 2.4 Spacing, radii, elevation
- **Spacing** has a 4 px base: `--space-1` 4, `-2` 8, `-3` 12, `-4` 16, `-5` 20, `-6` 24, `-8` 32, `-10` 40. `--gutter` is 16 px, `--tap-min` is 44 px.
- **Radii** match the app's cards: `--radius-sm` 6 (small tags), `-md` 8 (basket tiles, boxes), `-lg` 12 (cards, list groups, answer buttons), `-xl` 16 (the hero block and the review card), `-sheet` 20 (the top of bottom sheets), `-pill` (all buttons, chips and inputs).
- **Elevation:** cards are flat (`--shadow-none`): white, with a 1 px `--color-line` border, never a shadow. `--shadow-sheet` is only for bottom sheets. `--shadow-float` is only for the flying amount (#35), toasts and popovers.

### 2.5 Motion
| Token | Value | Use |
|---|---|---|
| `--duration-fast` | 150 ms | Press states, cross-fades (reduced motion) |
| `--duration-base` | 250 ms | Sheet in and out, card collapse, toast in |
| `--duration-slow` | 500 ms | Row flash, the guess reveal |
| `--duration-money` | 900 ms | Number counters |
| `--duration-flight` | 600 ms | The amount's flight between baskets (#35) |
| `--duration-long-press` | 600 ms | Long-press that opens the persona picker |
| `--ease-standard` | `cubic-bezier(.33,0,.34,1)` | Default |
| `--ease-entry` / `--ease-exit` | `(0,0,.3,1)` / `(.5,0,1,1)` | Things entering and leaving |
| `--ease-expressive` | `(.46,0,.19,1)` | The amount's flight between baskets |
| `--ease-spring` | `(.34,1.36,.64,1)` | Landing, check marks |

**Reduced motion** (`prefers-reduced-motion: reduce`): there is no flight and no counting. Numbers cross-fade in 150 ms, and toasts still appear.

## 3. Components

### Shell
- **Header:** 52 px, a grid of three cells. The module has no logo and no bottom navigation, because it lives inside S-mobiili.
  - **Left cell:** the back chevron (44 px target) when there is somewhere to go: a host is listening, or the module has its own history (an inner screen or an open sheet) (#175, `canGoBack()` in `src/lib/url.ts`). Outside a host, when there is no chevron, the visible persona button takes this cell (#323); the chevron always wins it.
  - **Centre:** the title "Sentti", a small visible **AI** tag next to it, and an ⓘ button (44 px target) that opens `ai_disclosure` as received in a small bottom sheet. The visible AI tag stays for transparency; the full sentence is behind ⓘ.
  - **Right cell:** the overview button that opens the overview sheet (#322).
  - There is no EN/FI switch in the header: the language comes from the host (`?lang=` now, `host.context` later) and, in the demo, from the persona sheet.
- **Host messages:** every message to the host is `{type: 'sentti.<name>', v: 1, payload}` with a camelCase name: `close` (back on the first screen), `paymentDraft` and `openHostScreen`. iOS gets the object through `webkit.messageHandlers.sentti`, Android a JSON string through `window.sentti` (#175, `src/lib/hostBridge.ts`). Without a host nothing is sent and the module uses its own navigation.
- **Composer:** pinned to the bottom ("Ask anything…"). The input is 48 px high with 16 px text; the send button is a 48 px circle in `--color-deep`. Bottom padding adds `env(safe-area-inset-bottom)`. The whole bar is 73 px high at 375 px with no inset (12 + 48 + 12 + border). A microphone appears only behind the voice flag (later).
- **Toast:** sits above the composer, never over it: its bottom is 8 px above the composer's top, so the input and the send button stay reachable while Undo is shown. It closes when a question is sent, and the toast of a review answer also goes by itself after 6 s; a toast with an error and Retry stays until it is closed.
- **No toast when the reply says it:** when Sentti's reply under the question already shows the answer's confirmation (the label response's `effect`, contract 0.3.2), no toast is shown, so nothing covers the reply. Undo is then the 44 px Undo on the answered card, and the live region reads `message.text_rendered` once. Without `effect`, the toast shows as above.

### Thread
- The first screen is **one thread on `/`** that Sentti opens. `/chat` redirects to `/` with `replace`, so Back never returns to it.
- **Turn 0 is the opening** (see "Opening turn"); every question and answer after it is a later turn in the same thread.
- **One thought per screen:** the opening shows one number and one question. Baskets, bills, safe to save, insights and the what-if entry come as Sentti's answers in the thread (for example after "Where did my money go?" or "How could I save more?") and in the overview sheet.
- The thread scrolls with the **document** (window scroll). There is no inner scroll container, because the review flight (#35) measures window scroll.
- The composer stays pinned to the bottom; the thread gets bottom padding equal to the composer's height, so the last turn is never under it.
- The module has no navigation of its own. The overview is reached from the header button (#322) and opens as a bottom sheet (see "Overview sheet").

### Opening turn
The opening is a client template built only from `GET /api/overview` fields, until the contract has a server-written opening (#338). Top to bottom, under the header:
1. **Greeting:** `greeting` as received, one line in `--text-xl` (20 / 28, 600), for example "Hi Sanna 👋". No second line; the AI disclosure is behind the header's ⓘ.
2. **One big card (safe to spend):** the green block (`--color-hero`, `--radius-xl`). It shows:
   - the hero's `primary.display` as sent, in `--text-hero` (40 / 44), white. No client rounding; a whole-euro display is a contract request (#338);
   - one caption, a client string without a number, chosen by `hero.status`: "Safe to spend this week" (`ok`), "Less room than usual this week" (`below_usual`), "Nothing free this week" (`nothing_free`); FI from the app's strings;
   - the Estimate badge in its on-green form, and a chevron ›.

   The whole card is one button: a tap opens a bottom sheet with the hero's `components` ("how it is made"), each part a number chip.
3. **One question card ("Sentti asks"):** `reviews[0]`'s question and its two answer buttons (see the "Sentti asks" review card below). The question already carries the amount (its `{{n1}}` token is a chip), so there is no separate amount line. `why` is behind an ⓘ on the card.
4. **2–3 chips:** the first three `suggested_questions`, as sent, in server order. A tap sends the question as a new turn.
5. **The composer**, pinned (see "Shell").

**Text limits on the first screen:** a card title has at most 4 words, a caption at most 8; no paragraph anywhere.

**No client sentence carries a number:** every number is an API `display`, and the template's own words never state or compare amounts.

**Fallbacks:**
- `hero: null`: no big card (contract 0.2.2 hides it for a known reason); the question card moves up.
- `reviews` empty: no question card; the chips move up.
- An overview error: the opening shows the error card (see "States"), and the composer offers 3 starter chips.

### Fit budget
**The check:** at 375 × 812 and at 375 × 768 (the demo frame's module iframe), everything from the header down to the last chip is on screen above the composer's top, with no scrolling. The #35 moment then also fits (below). The spike that led to this layout is in PR #355; its screenshots are kept outside the repository.

**Measured** on a local build of PR #157 (`fab214d`, mock mode, Sanna with the review pending, Chromium; both sizes give the same block heights, only the bottom anchors move):

| What | 375 × 812 | 375 × 768 |
|---|---|---|
| Header bottom | 52 | 52 |
| Composer top (bar height 73) | 739 | 695 |
| Toast height (3-line message) | 124 | 124 |
| Greeting line | 28 | 28 |
| Hero amount chip (`--text-hero`) | 64 high | 64 high |
| Review answer buttons | 56 high | 56 high |
| Review card collapsed after an answer | 144 | 144 |

The dashboard stack of #157 (hero 313 and review card 390, each in full) did not fit: 703 px against 687 px between the header and the composer at 812. That is why the first screen holds one number and one question.

**Expected heights of the new opening** (px; the thread starts at 60, the header plus an 8 px top padding):

| Block | About |
|---|---|
| Greeting, one line | 28 |
| Big card: 16 padding, 44 amount, 4, 20 caption, 16 padding | 100 |
| Question card: 16 padding, a 24 header row ("Sentti asks", ⓘ), 8, a question of up to 3 lines (72), 12, 56 answer buttons, 16 padding | 204 |
| 3 chips stacked, 44 each, 8 between | 148 |
| Gaps | 12 between blocks |

Sum: 28 + 12 + 100 + 12 + 204 + 12 + 148 = 516, so the last chip ends at 576: 163 px above the composer at 812 and 119 px at 768. Each building issue re-measures and reports against this check.

**The #35 moment in this layout:** after "It was needed":
1. The question card collapses to one line (a check, the chosen label).
2. The big card counts from `changes[].before` to `after` (for example €138.79 → €97.46).
3. Sentti answers right under the question with a short turn: a **mini basket row** where the amount (€1,080.42) flies from "Waiting for your answer" into the chosen basket, and under it `effect.text` with its tokens as chips. On a core without `effect`, a client sentence without a number comes first instead ("Moved to 🔧 Unexpected necessities", the basket label from the API).
4. With `effect` there is no toast: Undo is on the answered card (see "Toast" in "Shell"). Without `effect`, the toast with Undo appears above the composer.

The big card, the mini basket row and the reply's text are on screen together at both sizes, so the flight and the count can be seen without scrolling. If a size or setting breaks this (320 px wide, 200 % zoom, large text, a long Finnish question), the glide sequence built in #157 is the specified behaviour: the big card counts first, the page glides to the mini basket row, then the amount flies.

### Overview sheet
- Opens from the header's overview button (#322), as a bottom sheet and a history entry, so Back closes it.
- **Contents:** the full hero with its reserve line and links (see "Safe-to-spend widget"), the baskets, bills, safe to save, insights and the what-if entry.
- **No review card and no motion** in the sheet; the review lives only in the thread.

### Basket chip and basket row
- **Chip:** a pill in the basket tint with a white circle holding the emoji, and the label in the strong colour (600).
- **Row:** a list row (see "List rows") with a 40 px tinted tile holding the emoji, the label (`--text-card-title`, bold `--color-brand`), and the amount on the right (700, tabular, `--color-ink`). A 6 px bar in the strong colour on a `--color-sunken` track runs under it. The period caption ("Monthly average, April to September 2026") sits under the list.

### List rows
- The S-mobiili pattern: an icon or tile on the left, a bold green label with a grey meta line under it, the value on the right, and a `--color-brand` chevron (›, 2 px stroke, 20 px) at the far right when the row opens something.
- Rows sit in one white card with `--color-line` dividers between them; the whole row is the tap target (at least 56 px high).
- Pictograms are our own outlined line icons in `--color-brand` (2 px stroke), never S-Pankki pictograms.

### Number chip (evidence)
- A pill in `--color-mint-tint` with a 1 px `--color-mint-line` border, `--color-ink` text (600, tabular) and a small receipt mark.
- Its visible text is `display` exactly as received (with `label` in front when the surrounding text does not name the number). The app does not format it.
- **Tap:** opens the evidence sheet (`GET /api/evidence/{evidence_ref}`).
- **Size:** the chip is 32 px high when it stands alone. Inside running text it stays visually as high as the line, and its touch area is extended to at least 44 × 44 px with a transparent pseudo-element or padding. There is no exception to the 44 px rule.
- **Screen readers:** a Number object has no `text_rendered`. The chip's accessible name is "`label` `display`, show transactions", for example "Restaurants €312.80, show transactions". Whole texts with tokens (answers, insights, the label `message`) also come as `text_rendered`; screen readers and copying use that.

### Glossary term (#36)
- The term is plain text with a 2 px dotted `--color-brand` underline, offset 4 px. It has no background, so it never looks like a number chip.
- **Open term:** gets a light `--color-estimate-tint` (grey) highlight.
- **Tap:** opens a short bottom sheet (at most about 46 % of the screen) with the definition and, when the glossary entry has one, the customer's own number as a number chip.

### Takeaway line
The answer's first sentence: `--text-lg` in the normal weight (400), `--color-ink`, 32 px line height (#684). It is a little larger than the rest, not large bold. One per answer. An answer never shows more than 3 emphasised spans. Only a clarifying question keeps large bold (`--text-xl`, 700), because it is the whole answer.

### Fact vs estimate
- **Estimate:** a dashed, neutral `--color-estimate` pill on `--color-estimate-tint` with a "≈" glyph and `estimate.label`. On the green hero block it is drawn in `--color-on-hero` with a dashed `--color-on-hero-muted` border. It is a button that reveals `estimate.text`.
- **Fact:** no badge, or a quiet "From your transactions" in `--color-muted`.

### Answer card
A card inside a chat answer is part of one answer that is read once (#684, #696). The question is in the bubble above and the takeaway is the sentence before the card, so the card repeats neither.
- **Frame:** a flat white card with a 12 px radius (`--radius-lg`), a 1 px `--color-line` border, no shadow and 16 px padding.
- **No bold title.** The card title restates the question, so it is not drawn. A name that is itself the result (the spender profile, the peer comparison, a what-if that is not offered) is shown in the normal weight (`--text-lg`, `--color-ink`).
- **Caption:** the period, once (`period.label` of the main number, xs, muted). A later card of the same answer drops it when it is the same period.
- **Estimate marker:** top right, on the caption's line. A fact has no marker.
- **One main number** per answer: the first card's main number, large, as plain text, never a green pill (`size lg`, `tone plain`). A later card turns its main number into its first row.
- **"Label — value" rows** under it: the label in small muted text on the left, the value in normal ink on the right. With large text the value moves under its label. Changes read "▲ €91.70 more", with an arrow and a word, never colour alone.
- **The parts that make up the main number are never cut** (every basket, "Waiting for your answer" included, and every bill): a hidden part would make the rows not add up to the total. **Other figures are capped at 3 rows.**
- **What each type shows** (`lib/answerFigures.ts`, chosen by card type, never by matching texts):

  | Card type | Main number | Rows |
  |---|---|---|
  | `metric` | `primary` | comparison, then `secondary` |
  | `breakdown` | `total` | comparison, then the items |
  | baskets breakdown | `total` | every basket (all parts), then the comparison |
  | `bills` | `total` | every bill's amount due before payday (all parts) |
  | `safe_to_save` | `monthly` | the reason, weekly, daily, stock |
  | `whatif` | saving a month | a week, a year, the baseline |
  | `profile` | the deciding feature | the other features |
  | `peer` | you | the median, the gap, the percentile |

- **What-if caveats:** shown as sent, in a `--color-warning-tint` box, when the status is not a plain `estimate` (`estimate_with_caveat`, `not_offered`), as in the what-if sheet.
- Numbers are tappable text when they have an evidence ref, and plain text without one.
- Card `actions` are not drawn on the card: the answer offers at most one next step (below).
- **The review card** is the exception. Inside an answer it points to the "Sentti asks" card in the opening, or, when nothing shows that question, it is that card with its answer buttons (#318, #450), in the answer card's white frame. It has no large main number: the question text from the API already carries the amount, shown once as a number in the text, so nothing is repeated.

### Answer order
1. Takeaway: the first sentence, `--text-lg`, normal weight.
2. Cards, each in the shape above; only the first has a large number.
3. The rest of the text: `--text-base`, `--color-ink-2`.
4. A quiet note when the template answered without the AI model.
5. The `lesson` in a `--color-sunken` box.
6. **One next step**, a link-like button (brand, underlined, at least 44 px), chosen from what the response carries (`lib/nextStep.ts`). Nothing is invented: when the response carries nothing, there is no next step.
   - A refusal: only the way to a human ("Contact S-Pankki"), or nothing when the response does not carry it.
   - A "nothing found" fallback: the first follow-up question; "Contact S-Pankki" only when there is none (Maxim's decision, #696).
   - The "I can't answer that one yet" answer (a clarification that carries the way to a human): its `clarify.options` are its follow-up questions, shown as chips. "Contact S-Pankki" shows only when it has no options.
   - Any other answer, in this order: the answer's own action; then a card action that leads somewhere (the what-if, the bank's own screen, a question); then the first follow-up question; then a card's "how is this calculated".
   - A follow-up question, and a clarification's options, show only on the latest answer. On an older fallback or "not yet" answer, where they are hidden, the step falls back to "Contact S-Pankki".
   - A general clarifying question offers its options as chips instead.

The AI disclosure is not repeated in the answer. It sits behind the header's AI badge and ⓘ (#685). The stream never autoscrolls: the view stays pinned to the start of the answer.

### Chips
- **Suggested question / follow-up:** `--color-mint-tint` with a `--color-mint-line` border and ink text.
- **Action:** white with a 1.5 px `--color-brand` border and brand text.
- Both are at least 44 px high, 14 px, 600.

### Evidence bottom sheet
- 20 px top radius (`--radius-sheet`) with a grab handle; at most about 78 % of the screen, over the scrim.
- **Contents:**
  - the title and the total;
  - "N transactions · reconciles ✓";
  - a "How it was counted" box in plain words, built from `method` and `query`;
  - transaction rows: merchant label, date and time, and the amount as the row's `display`, as sent (section 4);
  - "Show all N";
  - `privacy_note` with a lock icon.

### Safe-to-spend widget
- **The green block** (like the S-mobiili Bonus hero): `--color-hero` background, the brand green `#007841` on purpose. The "Sentti asks" card uses the darker `--color-deep`, so a question never looks like the hero.
- **Block style:** `--radius-xl`, no border and no shadow. Everything on it is white or `--color-on-hero-muted`.
- **Top:** the title in `--color-on-hero-muted` (`--text-sm`, 600) and the "Estimate" badge in its on-green form.
- **Middle:** the hero number (`--text-hero`, `--color-on-hero`) and the subtitle period. Then one sentence with "Free until payday" and the irregular reserve as number chips (mint tint, `--color-ink` text, which stays AA on the chip).
- **Bottom:** the "How is this calculated? ›" link in white with a white chevron. It opens a sheet that writes `components` as a sentence formula, for example "balance − bills − essentials − reserve − cushion = free until payday".
- **Focus** on the block uses `--color-mint` (4.35:1).
- **Safe to save** is a separate, lower white card. It is never added to safe to spend.

### "Sentti asks" review card (#35)
- **Surface:** `--color-deep` (darker than the hero green), `--radius-xl`, a mint question icon and "Sentti asks". It must never look like an answer.
- **Header row:** the question icon, "Sentti asks", an ⓘ that shows `why`, and "Not sure" at the right. "Not sure" only closes the card, with no API call.
- **Contents:** the question text only: `question` is `{en, fi}`, shown as `question[language]`, the language of the request. Its `{{n1}}` (the amount) and `{{date}}` tokens become chips, so there is no separate amount line.
- **Answers:** two answer buttons side by side, white, at least 56 px high, each with a basket tile and a 4 px basket-colour stripe. Labels are `options[].label[language]`.
- **After a tap** (the thread layout, see "Fit budget"):
  1. The card keeps its header (with a 44 px Undo while the answer can be undone), the question in a compact size, and a check with the chosen label. It shows no effect line: what the answer did is Sentti's reply.
  2. The big card's number counts from `changes[].before` to `after` (900 ms, tabular figures; see section 4).
  3. Sentti answers right under the question with a short turn, mounted at the tap so it is on screen when the answer arrives: a **mini basket row**, and under it `effect.text` with its tokens as chips (on a core without `effect`, a client sentence without a number comes first instead, for example "Moved to 🔧 Unexpected necessities" with the basket label from the API). In the row the amount, as a pill, flies from "Waiting for your answer" to the chosen basket: `--duration-flight` (600 ms) with `--ease-expressive`; its border colour turns to the target basket's, and the waiting cell fades out. The flight looks for its cells only inside this reply and never scrolls the page.
  4. With `effect`, no toast is shown; the live region reads `message.text_rendered` once, and Undo is on the card. Without `effect`, a toast above the composer shows `message.text` with each `{{nN}}` token rendered as a number chip from `message.numbers`, and an Undo button; `message.text_rendered` (tokens already replaced) is only for screen readers (the live region) and copying.
  5. **Undo** sends `basket: null` and counts the changed numbers back. If the review is less than 7 days old, the purchase returns to "Waiting for your answer" and the question comes back. If it is older, the review closes and the purchase returns to the basket its rules give it; the card does not come back.
- **No reload:** the overview is refetched in the background after the animation.
- **Expiry:** a pending review expires 7 days after creation; after that its `tx_ref` returns 404 `tx_ref_not_found`. The app then removes the card quietly and shows no error.
- **What the big card shows after the answer:** "It was needed" lowers safe to spend. After counting, the big card shows the new `display`, and for 6 s a down arrow with "was <old display>" under it in `--color-on-hero-muted` (4.95:1 on the green block); the caption stays the client string of `hero.status`. "I chose it" leaves safe to spend unchanged: the number does not count, and the hint says "stays the same". Grey `--color-muted` or `--color-down` are never used on the green block (1.03:1 and 1.11:1), and red is never used for this.

### Guess first (#37)
- The number is blurred (10 px) and hidden from screen readers. Four range chips (for example €50 / €100 / €200 / €300+), "Skip, just show me" and "Reveal".
- **Reveal:** two bars grow from 0 over 500 ms: "Your guess" (hatched) and "Actual" (solid `--color-ink`, so it never reads as the 🏠 basket), with neutral copy.
- At most one per screen. Never used for safe to spend, Health or other sensitive categories.

### What-if slider
- The track has a 44 px hit area, a 6 px line and a 28 px thumb, in whole percent from 1 to 100. The request is sent on the input's native `change` event, so VoiceOver and TalkBack update it too (#154).
- The result is in `--text-2xl`, with per month, week and year below, and the "Estimate" badge.
- The previous value stays until the new response arrives.

### Persona picker (demo only)
- **Opens:** with a long-press (`--duration-long-press`, 600 ms) on the header title, or with `?persona=`. A visible button in the header's left cell opens it too, but only outside a host (neither `webkit.messageHandlers.sentti` nor `window.sentti` exists) and only while there is no back chevron: the chevron always wins the left cell (#323). Inside S-mobiili the customer comes from the bank, so there is no visible picker.
- **Contents:** a bottom sheet titled "Demo personas" with the personas and the EN/FI language switch.

### States
| State | Rule |
|---|---|
| Loading | Stage lines from `status` events, using their `label`. Done stages get a check, and the current one a spinner. A card skeleton appears at once. The send button becomes a stop button. |
| Opening (no "empty") | The thread is never empty: Sentti opens it (see "Opening turn"). On an overview error the opening shows the error card, and the composer offers 3 starter chips near the thumb. Never "Ask me anything". |
| Error | A `--color-danger-tint` card with `error.message` as is. "Try again" appears only when `retryable` is true. |
| Clarify | `clarify.question` in the takeaway style and `clarify.options` as chips that send at once. Typing still works. |
| Off-topic / refusal | A normal bubble with a grey left rule, `refusal.label` in xs, the template text and the `follow_ups` chips. |
| Fallback | `outcome: "fallback"`: the same cards and the template line, plus one quiet note that the written explanation is unavailable and the numbers come from the transactions. |

## 4. Numbers and language
- **The app does not format or translate numbers.** It shows `display` and the localised labels from the API. EN looks like `€1,080.42`, FI like `1 080,42 €`.
- **The one exception: counter frames.** When a number changes after a review answer (#35), it counts from one API `display` to the next. The frames in between are computed by `src/lib/motion.ts` (#157); the first and the last frame are the API's `display` strings. The frames are `aria-hidden`, and the accessible text is the final `display`. The chip cannot be tapped while it counts. With reduced motion there are no frames: the number cross-fades to the new `display`.
- **Evidence rows** are no exception: each row of `GET /api/evidence/{ref}` carries `display`, its amount written by the server in the request language with the bank sign (`-€24.50`, FI `-24,50 €`; contract section 9), and the app shows it as sent. The row's `amount` stays the exact decimal string and is never formatted by the app.
- **Signs:** amounts never get a plus sign. Changes use an arrow and words ("was €138.79", "▲ €91.70").
- **Language:** the EN/FI switch sets `?lang=` and `language`. Long Finnish words wrap inside chips and never truncate.

## 5. Accessibility and WebView
- **Contrast:** all text pairs meet AA (section 2.2). Colour is never the only signal (WCAG 1.4.1).
- **Focus:** a `--focus-ring-width` (3 px) outline with a 2 px offset: `--color-brand` on light surfaces, `--color-mint` on dark ones (`--color-deep`, `--color-ink`, `--color-hero`). `--color-brand` is only 1.97:1 on `--color-deep` and `--color-ink` and invisible on `--color-hero` (the same green), so it is never used there.
- **Targets:** at least 44 × 44 px everywhere, including inline chips (extended with a pseudo-element or padding).
- **Viewport:** `viewport-fit=cover`, safe-area padding on the composer and sheets, and height from `100dvh` minus `env(safe-area-inset-bottom)`.
- **No service worker in production:** WKWebView does not run it. Mock data is for development only.
- **Larger Text:** WKWebView ignores the system text-size setting. All sizes are in px tokens, so the layout must survive 200 % browser zoom and reflow at 320 px without horizontal scroll (WCAG 1.4.4, 1.4.10). An in-app text-size switch is a follow-up (section 8).

## 6. Tone of voice
- Short, friendly, second person ("you"), no jargon. One idea per sentence.
- No moralising and no shame. Say "everyday spending", never "leakage". When a guess was low, say "Most people underestimate this one". When it was high, say "Less than you thought. Good to know where you stand".
- Say what Sentti can do before the user asks; refuse briefly and offer what it can do instead.
- AI texts come from the core. The app's own strings (buttons, empty states) follow the same rules.

## 7. Licences
Only MIT-compatible material goes into `app/`.

| Item | Licence | Decision | Notes |
|---|---|---|---|
| Figtree (typeface) | SIL OFL 1.1 | Use | Self-host through `@fontsource/figtree` (package licence OFL-1.1). OFL is compatible with an MIT repository: keep the OFL text with the font files and do not sell the font on its own. |
| Inter, Nunito Sans (typefaces) | SIL OFL 1.1 | Considered, not used | Compared with Figtree for #92; Figtree is closer to the S-mobiili UI font. |
| shadcn/ui | MIT | Use | Components are copied in. |
| Vercel AI Elements | Apache-2.0 | Use with care | Compatible. Keep `LICENSE`/`NOTICE` and mark modified files. Reportedly being deprecated in favour of shadcn/ui copy-in patterns (date not verified); prefer those. |
| 21st.dev blocks | Per component, no default | Not used yet | Each block is checked before it is copied in, and its licence is added as a row here. A block with no stated licence ("unknown") is rejected. |
| S Bonus UX / S Bonus Display | Proprietary (S Group) | Rejected | Replaced by Figtree. |
| S-Pankki / S-Group logos, pictograms, images | Proprietary | Rejected | None in the repo. Basket icons are system emoji, and line icons and chevrons are our own inline SVG. Colour values are not assets: they follow the public look of S-mobiili. |

## 8. Follow-ups (outside #65)
- **Component code:** shadcn/ui-based components and the mapping of `tokens.css` into the Tailwind `@theme` arrive with the app shell and screen issues. They keep these variable names.
- **Finnish texts:** basket names and glossary definitions come from the core (contract 0.2, #34). The app shows them as received.
- **21st.dev:** each block chosen later gets a row in the licence table (section 7) before it is used.
- **Text size:** an in-app text-size switch for WKWebView (section 5).
- **More card renderers:** `bills`, `peer`, `stores`, `profile` and `safe_to_save` cards, and the other evidence kinds (for example composite evidence with `parts`), get their rules when their screens are built. They reuse the answer-card frame, number chips and the fact/estimate markers above.
