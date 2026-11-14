# Demo script

How to run, rehearse and record the Sentti demo. For the stage, use the **60-second path**; the **full run** below it shows everything, in about two minutes.

Status markers: **now** = on the dev environment today (checked live on 14 Nov 2026, dev 33797a3 and 39c938f); **after 15:45** = in the deploy of 14 Nov 15:45, check it on the stand before recording; **in progress** = being built, the issue or PR is named.

**Numbers** are Sanna's (`CUST00860`) on the dev environment with a fresh viewer: safe to spend is **€138.79** with **€360.00 a month** set aside first (pay yourself first, #426), and it goes **€138.79 → €97.46** after "Needed". The other personas' first screens: Marja **€78.86**, Eetu **€161.69** (his "Sentti asks" is about €378.22; after "Needed" **€147.23**), Aleksi **€123.15**.

## Where to run it
1. **The dev deployment (first choice):** `https://sentti.jeremyxd.dev/demo.html?lang=en&persona=CUST00860`, in Chrome or Safari, on a laptop (the phone is scaled to fit) or on a phone (1:1). The page is the demo frame ("Sentti in a host app (demo)"): a neutral host app around the module, with the persona, the language and **Start over** outside the phone, and the message log beside it. The module alone is at `https://sentti.jeremyxd.dev/?persona=CUST00860&lang=en` (no host frame, no message log, no Start over).
2. **The deployment is down: a local mock build.** It needs no network after `npm ci` and shows the same screens with the contract's example data. The mock's numbers are the contract examples, not today's stand: do not quote them as live.
   ```
   cd app
   npm ci
   VITE_API_MODE=mock npm run build
   npm run preview
   ```
   Then open `http://localhost:4173/demo.html?lang=en&persona=CUST00860`. In the mock build the AI answers are the contract's recorded examples, and **Start over** (or a reload) brings "Sentti asks" back. Sanna's safe to spend is the same there, **€138.79 → €97.46** after "Needed". The whole 60-second path runs in the mock, step 4 included: "How could I save more?" answers with the contract's Safe to save card instead of the savings plan, and its **"See monthly saving in S-mobiili"** opens "**Opens in the bank app: Monthly saving**" as on dev (#495). `npm run demo:check -- http://localhost:4173` checks this path.
3. **Last resort: a screen recording.** Record a full run beforehand (see "Recording") and play it if neither option works on the day.

**Persona:** Sanna (`CUST00860`), the lead persona: a large Home & Tech purchase in late September that Sentti asks about. **Language:** EN on stage; FI with `lang=fi` or the FI switch in the persona sheet.

## The 60-second path (stage)

| # | Tap | Expect | Say |
|---|---|---|---|
| 1 | **Start over** (outside the phone). It opens the module fresh. | "Hi Sanna", **€138.79** safe to spend this week, and "Sentti asks" about **€1,080.42** at Home & Tech. | "Sentti lives inside the bank's app. It starts with one number and one question." |
| 2 | **Needed**. | Safe to spend counts **€138.79 → €97.46** ("less room than usual this week"); a toast with **Undo**. | "One answer, and the plan changes at once: a bigger reserve for surprises." |
| 3 | The chip **"Where did my money go?"**. **The AI step.** | Progress stages, then a takeaway, a card and a short explanation with number chips. | "The AI writes the explanation, but every number comes from the tools and is checked first." |
| 4 | Type **"How could I save more?"**, then tap **"See monthly saving in S-mobiili"** on the card. | The savings plan (€63.17 a month on top of the €360.00 goal); the host app shows "**Opens in the bank app: Monthly saving**". | "Sentti never moves money. It hands over to the bank's own screens." |
| 5 | Back on the module's first screen. | The host app's home. | "And we are back in the bank's app." |

## The full run

| # | Do | Expect on screen (Sanna, EN) | Say | Status |
|---|---|---|---|---|
| 1 | Press **Start over**, or open the module from the host app. Start over opens it fresh (a new viewer). | The module opens inside the host app. | "Sentti lives inside the bank's app, as a module." | now |
| 2 | Look at the first screen. | "Hi Sanna"; the hero **€138.79** "safe to spend this week" with **Estimate**; "Sentti asks": "**€1,080.42** at Home & Tech on 28 September 2026 — needed, or your choice?" with **Needed**, **My choice**, "Not sure" and an info button ("Why Sentti asks"); three question chips; the composer "Ask about your money". The header has **Sentti AI**. | "One number, one question. Every number opens the transactions behind it." | now. The basket strip and the overview sheet are not on the first screen yet (#320–#322). |
| 3 | Tap **Sentti AI** in the header. | "About Sentti": "Explanations are written by AI. The numbers are calculated from your transactions." | "It says plainly what the AI does and what it doesn't." | now |
| 4 | Tap **€138.79**. | The evidence sheet "Safe to spend, 1–7 Oct 2026": what it is made of — **Your balance allows €5,906.19**, **Your monthly budget allows €138.79**, **Savings goal set aside first €360.00 a month**. Back closes it. | "Nothing here is made up by the AI: each number has its receipts. Safe to spend is what's left after saving comes first." | now. **After 15:45:** "How it was calculated" is one plain sentence (today it shows a file name and a "Method:" line, #554 / #557). |
| 5 | Tap **Needed**. | Safe to spend counts **€138.79 → €97.46**, "was €138.79 · less room than usual this week"; the card marks **Needed**; a toast with **Undo**: "Your safe to spend this week goes from €138.79 to €97.46: €1,080.42 now counts as an unexpected necessity, so the reserve grows." | "Sentti asked one question, and the answer changed the plan at once." | now |
| 6 | Tap **Undo** in the toast. | Back to **€138.79**; "Sentti asks" is open again. | (no line; it sets up the next steps) | now |
| 7 | Type **"Why is my safe to spend lower than it was?"** | "This week €138.79 is safe to spend because your monthly budget sets the limit, after setting aside €360.00 a month first. Your €1,080.42 purchase still waits for your answer: marking it needed would lower this." | "It explains its own number: the limit, the saving, the open question." | now (dev 39c938f) |
| 8 | Tap the chip **"Where did my money go?"**. **This is the AI step.** | A streamed answer: progress stages, then a takeaway, the card "Where your money goes in a typical month" (6-month average: regular essentials €1,889.04, everyday €600.41, unexpected €341.08, waiting for your answer €180.07; €3,010.59 in total) and short sentences with number chips. | "Now the AI writes the explanation, but every number in it comes from the tools and is checked before it is shown." | now. **After 15:45:** the first chip under an answer is the next step for that answer. |
| 9 | Type **"How could I save more?"**, then tap **"See monthly saving in S-mobiili"** on the card. | "Cutting back on restaurants and lifestyle could save you €63.17 a month, that is €758.04 a year. That comes on top of your savings goal of €360.00 a month." The savings-plan card; the action sends `sentti.openHostScreen` with `monthly_saving`; the host shows "**Opens in the bank app: Monthly saving**" with "Demo: nothing opens", and the message log lists `sentti.openHostScreen`. | "Sentti never moves money. It hands over to the bank's own screens." | now |
| 10 | Type **"What if I spent 20% less on restaurants?"** | A what-if answer and card: Sanna would save **€45.91 a month** (from a typical **€229.56 a month**), marked as an estimate with what was observed and what is assumed. | "What-ifs are calculated, not guessed, and marked as estimates." | now |
| 11 | Type **"What is safe to spend?"** | A fixed plain-language definition with her own number (€138.79), never AI-written. | "Money words get a plain answer, with her own number." | now (glossary, #568) |
| 12 | Type **"Should I buy bitcoin?"** | A polite refusal: no investment advice, an S-Pankki adviser can help, with a **Contact S-Pankki** button that hands over to the bank. | "Where advice needs a person, Sentti says so and hands over to the bank." | now in the answer; **check** that the build shows the button (the app side is #439). If not, say the line without tapping. |
| 13 | Type **"How much did I spend at the pharmacy last month?"** | **After 15:45:** a neutral total, "You spent €185.30 on health in August 2026, across 3 transactions.", with no comment or tip. Today the question still gets the generic refusal: skip this step if the deploy is not in. | "Health is answered as a plain amount, never judged." | **after 15:45** (#571, #607) |
| 14 | The bill step: "Show Sentti a bill", pick a sample bill. | The reading, the fields, the explanation (amount, due date, warning signs), then **Add to payments**: the host shows "Payment draft" with "Demo: nothing is paid". | "A bill becomes a payment draft in the bank's app; Sentti does not pay." | **check after 15:45**: the step in the thread (#332) and Add to payments (#331). If it is not reachable, skip it and say the line over step 9. |
| 15 | Tap back on the module's first screen. | `sentti.close` (in the log); the host app's home is back. | "And we are back in the bank's app." | now |

## Do not ask while recording
- **Another person's money** ("Why is my wife's safe to spend lower than mine?"): today it is answered with Sanna's own numbers, as if about her, until #621 is on the stand.
- **"What did X cost me?"** for a single thing: #623 is not on the stand yet.
- **A thing Sentti cannot see together with another question** ("How much did I spend on yoga last month and what can I safely spend this week?"): the answer runs to five sentences (#600).
- Any question in the "When something differs" list below if the note appears twice in a row: move on to the next step.

## When something differs
- **The AI note (`llm_unavailable`):** if an answer shows the short note that it was written without the language model, the model was not available and Sentti answered from its template. Say: "The language model is not available right now, so Sentti answers from its template. The numbers are exactly the same, because they never come from the model." Carry on.
- **The bill step's fallback:** if the reading of the sample bill is not available (`model_unavailable`), the flow asks "Type the bill's details": type the payee, the amount and the due date of the sample, then continue to the explanation and Add to payments. If the step is not reachable in the build you run, skip it.
- **No "Sentti asks" card:** this viewer has answered already. Press **Start over**.
- **A message "No connection" or "Something went wrong":** tap **Try again**; if it repeats, press Start over; if the deployment is down, switch to the local mock build ("Where to run it", option 2).
- **Safe to spend is missing:** the core could not compute it for a known reason and hides the card; continue from step 8.
- **Different numbers:** the numbers above are the dev environment's on 14 Nov 2026 with a fresh viewer. A viewer who answered "Needed" earlier sees €97.46 until Start over.

## Re-arm
- **Between runs: Start over** ("Aloita alusta"), outside the phone. It gives this browser a new viewer and reloads the module with the chosen persona and language; it also empties the message log. "Sentti asks" then runs again for Sanna. In the local mock build the reload itself brings the question back.
- **Inside a run: Undo** in the toast. It counts the numbers back and brings the question back, so step 5 can be shown again without a reload.

## Recording
- Record at 375 × 812 (or the frame on a laptop): two runs of step 5 with **Start over** between them, and one full run as the stage fallback.
- Keep the message log visible when the host steps (4 and 5 of the 60-second path; 9, 12, 14 and 15 of the full run) matter for the shot.
