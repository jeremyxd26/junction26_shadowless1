# Demo script

How to run, rehearse and record the Sentti demo. For the stage, use the **60-second path**; the **full run** below it shows everything, in about two minutes.

Status markers: **dev** = on the dev environment now; **in progress** = being built, the issue or PR is named. The expected screens follow `app/DESIGN.md` section 3; where the dev build still differs, the step says so.

**Numbers** are Sanna's on dev on 14 Nov 2026. Safe to spend goes **€221.58 → €180.26** after "Needed". After PR #426 (a savings goal, put aside first) the same step reads **€138.79 → €97.46**. Check which one the build shows before going on stage.

## Where to run it
1. **The dev deployment (first choice):** `https://sentti.jeremyxd.dev/demo.html?lang=en&persona=CUST00860`, in Chrome or Safari, on a laptop (the phone is scaled to fit) or on a phone (1:1). The page is the demo frame: a neutral host app ("Bank app (demo)") around the module, with the persona, the language and **Start over** outside the phone, and the message log beside it.
   - **Today the frame is not on the host yet:** the host runs an older build, and `/demo.html` answers with the app's `index.html`. The frame appears there after the redeploy of #442. Until then use option 2, or open the module itself at `https://sentti.jeremyxd.dev/?persona=CUST00860&lang=en` (no host frame, no message log, no Start over).
2. **The deployment is down or old: a local mock build.** It needs no network after `npm ci` and shows the same screens with the contract's example data (Sanna, €221.58 → €180.26):
   ```
   cd app
   npm ci
   VITE_API_MODE=mock npm run build
   npm run preview
   ```
   Then open `http://localhost:4173/demo.html?lang=en&persona=CUST00860`. In the mock build the AI answers are the contract's recorded examples, and **Start over** (or a reload) brings "Sentti asks" back.
3. **Last resort: a screen recording.** Record a full run beforehand (see "Recording") and play it if neither option works on the day.

**Persona:** Sanna (`CUST00860`), the lead persona: a large Home & Tech purchase in late September that Sentti asks about. **Language:** EN on stage; FI with `lang=fi` or the FI switch.

## The 60-second path (stage)

| # | Tap | Expect | Say |
|---|---|---|---|
| 1 | **Start over** (outside the phone). It opens the module fresh. | "Hi Sanna", safe to spend **€221.58**, and "Sentti asks" about **€1,080.42** at Home & Tech. | "Sentti lives inside the bank's app. It starts with one number and one question." |
| 2 | **Needed**. | Safe to spend counts **€221.58 → €180.26**; the purchase flies into 🔧 Unexpected necessities; a toast with **Undo**. | "One answer, and the plan changes at once: a bigger reserve for surprises." |
| 3 | The chip **"Where did my money go?"**. **The AI step.** | Progress stages, then a takeaway, a card and a short explanation with number chips. | "The AI writes the explanation, but every number comes from the tools and is checked first." |
| 4 | **"How could I save more?"**, then **"See monthly saving in S-mobiili"** on the card. | The safe-to-save card; the host app shows "**Opens in the bank app: Monthly saving**". | "Sentti never moves money. It hands over to the bank's own screens." |
| 5 | Back on the module's first screen. | The host app's home ("Money coach · Sentti"). | "And we are back in the bank's app." |

## The full run (9 steps)

| # | Do | Expect on screen (Sanna, EN) | Say | Status |
|---|---|---|---|---|
| 1 | Press **Start over**, or tap "Money coach · Sentti" in the host app. Start over opens the module fresh (a new viewer); the row card opens it as it is. | The module opens inside the host app, with a back chevron. | "Sentti lives inside the bank's app, as a module." | Frame: dev (#325); on the host after the redeploy (#442). |
| 2 | Look at the first screen. | "Hi Sanna" with the AI tag; safe to spend **€221.58**; "Sentti asks" about **€1,080.42** at Home & Tech on 28 September 2026, with **Needed** and **My choice**; the basket strip; the chips; the composer. | "One number, one question. Every number opens the transactions behind it." | dev: the thread with the opening (#311), the AI tag, greeting, hero, "Sentti asks" and the basket strip (#312, #320). The first screen with one thought (#408): in progress. |
| 3 | Tap **€221.58** (or any number chip). | The evidence sheet: how the number is made and its transactions. Back closes it. | "Nothing here is made up by the AI: each number has its receipts." | dev |
| 4 | Tap **Needed**. | Safe to spend counts **€221.58 → €180.26**; the purchase flies from "Waiting for your answer" into 🔧 Unexpected necessities (€341.08 → €521.15 a month); a toast with **Undo**: "Thanks. Sentti now keeps a bigger reserve for surprises like this, so your safe to spend is lower." After #426: **€138.79 → €97.46**. | "Sentti asked one question, and the answer changed the plan at once." | dev (#157) |
| 5 | Tap the chip **"Where did my money go?"**. **This is the AI step.** | A streamed answer: progress stages ("Reading your question → Checking your transactions → Writing"), then a bold takeaway, a card and one to three sentences with number chips. | "Now the AI writes the explanation, but every number in it comes from the tools and is checked before it is shown." | dev (#87) |
| 6 | Tap **"How could I save more?"**, then **"See monthly saving in S-mobiili"** on the card. | The safe-to-save card; the action sends `sentti.openHostScreen` with `monthly_saving`; the host shows "**Opens in the bank app: Monthly saving**" with "Demo: nothing opens", and the message log lists `sentti.openHostScreen`. | "Sentti never moves money. It hands over to the bank's own screens." | dev: the card (#88), the action (#268, bridged in #427), the host sheet and the log (#326). |
| 7 | Open "What if I spent 20% less on restaurants?" and move the slider. | The what-if sheet; at 20 % Sanna saves €45.91 a month; the number updates when the slider is released. | "What-ifs are calculated, not guessed, and marked as estimates." | dev (#154) |
| 8 | The bill step: "Show Sentti a bill", pick a sample bill. | The reading, the fields, the explanation (amount, due date, warning signs), then **Add to payments**: the host shows "Payment draft" with "Demo: nothing is paid". | "A bill becomes a payment draft in the bank's app; Sentti does not pay." | In progress: the step in the thread (#332) and Add to payments (#331). The reading and the fields are on dev in `/cards` of a mock build (#247). |
| 9 | Tap back on the module's first screen. | `sentti.close` (in the log); the host app's home is back. | "And we are back in the bank's app." | dev (#175, #325) |

## When something differs
- **The AI note (`llm_unavailable`):** if an answer shows the short note that it was written without the language model, the model was not available and Sentti answered from its template. Say: "The language model is not available right now, so Sentti answers from its template. The numbers are exactly the same, because they never come from the model." Carry on. (The note follows the warning `llm_unavailable`, #282.)
- **The bill step's fallback:** if the reading of the sample bill is not available (`model_unavailable`), the flow asks "Type the bill's details": type the payee, the amount and the due date of the sample, then continue to the explanation and Add to payments. If the step is not reachable in the build you run, skip it and say: "The same flow reads a bill and turns it into a payment draft."
- **No "Sentti asks" card, or no flight:** this viewer has answered already. Press **Start over**.
- **A message "No connection" or "Something went wrong":** tap **Try again**; if it repeats, press Start over; if the deployment is down, switch to the local mock build ("Where to run it", option 2).
- **Safe to spend is missing:** the core could not compute it for a known reason and hides the card (contract 0.2.2); continue from step 3 with another number.
- **Different numbers on stage:** if the build has #426, the hero reads €138.79 → €97.46 instead of €221.58 → €180.26.

## Re-arm
- **Between runs: Start over** ("Aloita alusta"), outside the phone. It points the module at `/api/viewer/reset`, which gives this browser a new viewer cookie and redirects to `/`; the frame then reloads the module with the chosen persona and language and installs the host stub again. It also empties the message log. "Sentti asks" and the flight then run again for Sanna. In the local mock build there is no reset endpoint; the reload itself brings the question back.
- **Inside a run: Undo** in the toast. It counts the numbers back and brings the question back (while the review is less than 7 days old), so step 4 can be shown again without a reload.

## Recording
- Record at 375 × 812 (or the frame on a laptop): two runs of step 4 with **Start over** between them, and one full run as the stage fallback.
- Keep the message log visible when the host steps (4 and 5 of the 60-second path, 6, 8 and 9 of the full run) matter for the shot.
