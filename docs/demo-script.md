# Demo script

How to run, rehearse and record the Sentti demo. Read it once before the first run; each run takes about two minutes.

Status markers: **dev** = on the dev deployment now; **planned** = not built yet (the issue is named). The expected screens follow `app/DESIGN.md` section 3 (one thought per screen); where the dev build still differs, the step says so.

## Before you start
- **Where:** `https://sentti.jeremyxd.dev/demo.html?lang=en&persona=CUST00860` in Chrome or Safari, on a laptop (the phone is scaled to fit) or on a phone (1:1). The page is the demo frame: a neutral host app ("Bank app (demo)") around the module, with the persona, the language and **Start over** outside the phone, and the message log beside it.
- **Persona:** Sanna (`CUST00860`), the lead persona: a large Home & Tech purchase in late September that Sentti asks about.
- **Language:** EN for the stage; FI with `lang=fi` or the FI switch.
- **Fresh state:** press **Start over** before every run. Answers to "Sentti asks" are kept per viewer (a cookie), so after one run the question and the money flight are gone until you start over.
- **Recording:** a 375 × 812 window, or the frame on a laptop.

## The run

| # | Do | Expect on screen (Sanna, EN) | Say | Status |
|---|---|---|---|---|
| 1 | Tap "Money coach · Sentti" in the host app. | The module opens inside the host app, with a back chevron. | "Sentti lives inside the bank's app, as a module." | dev (#325) |
| 2 | Look at the first screen. | "Hi Sanna"; one big card, **€221.58**, safe to spend this week; the question "€1,080.42 at Home & Tech on 28 September 2026 — needed, or your choice?" with **Needed** and **My choice**; 2–3 chips; the composer. | "One number, one question. Every number opens the transactions behind it." | Thread opening: planned (#311–#317). The dev build still shows the overview with the hero, the review card and the baskets. |
| 3 | Tap the €221.58 (or any number chip). | The evidence sheet: how the number is made and its transactions. Back closes it. | "Nothing here is made up by the AI: each number has its receipts." | dev |
| 4 | Tap **Needed**. | Safe to spend counts **€221.58 → €180.26**; the purchase flies from "Waiting for your answer" into 🔧 Unexpected necessities (€341.08 → €521.15 a month); a toast with **Undo**: "Thanks. Sentti now keeps a bigger reserve for surprises like this, so your safe to spend is lower." | "Sentti asked one question, and the answer changed the plan at once." | dev (#157). In the thread layout the flight runs in a mini basket row under the question (planned, #311–#317). |
| 5 | Tap the chip **"Where did my money go?"**. **This is the AI step.** | A streamed answer: progress stages ("Reading your question → Checking your transactions → Writing"), then a bold takeaway, a card and one to three sentences with number chips. | "Now the AI writes the explanation, but every number in it comes from the tools and is checked before it is shown." | dev (#87) |
| 6 | Tap **"How could I save more?"**, then the card's action to the bank's own screen. | The safe-to-save card (€364.31 a month); the action sends `sentti.openHostScreen`; the host shows "Opens in the bank app: monthly_saving", and the message log lists it. | "Sentti never moves money. It hands over to the bank's own screens." | Card: dev (#88). The action on the card: planned (#324). The host sheet and the log: in review (#326). |
| 7 | Open "What if I spent 20% less on restaurants?" and move the slider. | The what-if sheet; at 20 % Sanna saves €45.91 a month; the number updates when the slider is released. | "What-ifs are calculated, not guessed, and marked as estimates." | dev (#154) |
| 8 | The bill step: "Show Sentti a bill", pick a sample bill. | The reading, the fields, the explanation (amount, due date, warning signs), then **Add to payments**: the host shows "Payment draft" with "Demo: nothing is paid". | "A bill becomes a payment draft in the bank's app; Sentti does not pay." | Planned in the thread (#332). The reading and the fields are on dev in `/cards` of a mock build (#247); Add to payments is planned (#331). |
| 9 | Tap back on the module's first screen. | `sentti.close` (in the log); the host app's home is back. | "And we are back in the bank's app." | dev (#175, #325) |

## When something differs
- **The AI note (`llm_unavailable`):** if an answer shows the short note that it was written without the language model, the model was not available and Sentti answered from its template. Say: "The language model is not available right now, so Sentti answers from its template. The numbers are exactly the same, because they never come from the model." Carry on. (The note follows the warning `llm_unavailable`, #282.)
- **The bill step's fallback:** if the reading of the sample bill is not available (`model_unavailable`), the flow asks "Type the bill's details": type the payee, the amount and the due date of the sample, then continue to the explanation and Add to payments. If the step is not reachable in the build you run, skip it and say: "The same flow reads a bill and turns it into a payment draft."
- **No "Sentti asks" card, or no flight:** this viewer has answered already. Press **Start over**.
- **A message "No connection" or "Something went wrong":** tap **Try again**; if it repeats, press Start over.
- **Safe to spend is missing:** the core could not compute it for a known reason and hides the card (contract 0.2.2); continue from step 3 with another number.

## Re-arm
- **Between runs: Start over** ("Aloita alusta"), outside the phone. It points the module at `/api/viewer/reset`, which gives this browser a new viewer cookie and redirects to `/`; the frame then reloads the module with the chosen persona and language and installs the host stub again. "Sentti asks" and the flight then run again for Sanna.
- **Inside a run: Undo** in the toast. It counts the numbers back and brings the question back (while the review is less than 7 days old), so step 4 can be shown again without a reload.

## Recording
- Record at 375 × 812 (or the frame on a laptop): two runs of step 4 with **Start over** between them.
- Keep the message log visible when the host steps (6, 8, 9) matter for the shot.
