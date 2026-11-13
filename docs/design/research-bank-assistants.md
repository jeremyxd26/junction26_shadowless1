# Research: how banks and fintechs build AI money assistants

Issue #3. Public sources only. Every factual claim points to a numbered source in [Sources](#sources), each with its URL and access date. Where a company has not published something, this document says **unknown** instead of guessing.

> **For #5 (agent core) and #6 (metrics):** the short version is [Rules we adopt](#rules-we-adopt). Rule IDs R1 to R15 are stable, and each rule names its basis in sections 1 to 5.

## 1. Examples

All metrics below are self-reported by the companies.

| Product | What it does | Scope and technology | Limits and hand-off | Published metric |
|---|---|---|---|---|
| Bank of America **Erica** | Proactive insights, account management, answers to questions [E1] | NLP, "not generative AI or large language models". It selects "from a pre-defined set of answers" [E1]. | "Erica does not provide investment advice." It can connect the user to a specialist by phone or chat [E1]. | Nearly 50 million users and over 3 billion interactions; "More than 98% of users find the information they need" (Aug 2025) [E2] |
| **Klarna** AI assistant | Customer service: refunds, returns, multilingual support [E3] | Announced as "powered by OpenAI". It shows the user's outstanding balances and payment schedule [E3]. | Customers "can still choose to interact with live agents" [E3]. In 2025 Klarna turned back to human agents (news) [E4]. | 2.3 million conversations, two thirds of service chats, in the first month; 25% fewer repeat inquiries [E3] |
| **Nubank** | A generative-AI virtual assistant for customer service, first around credit offers [E5]. Support agents in production across five domains (2026 paper) [E6]. | First version on GPT-4. It uses Nubank's "data models and proprietary structure and insights tools" [E5]. | The first phase went to "a restricted group" of users [E5]. Refusal behaviour: unknown. | +29 percentage points self-service rate. AI satisfaction "within a few percentage points of expert human agents". Separately, the framework uses an LLM judge "with measured inter-rater agreement" [E6]. |
| **Revolut** AIR (UK, April 2026) | Spending insights, investment tracking, subscriptions, card freeze [E7] | Revolut says AIR is "only accessing the data you already see", with "zero data retention" by third-party AI partners [E7] (news copy of the release; revolut.com returned 403) | Unknown | Unknown |
| **Cleo** | AI money app built around chat [E8] | An LLM agent calls tools "defined by a structured schema". "Cleo offloads calculations to structured, deterministic tools" [E8]. Specialist agents "query the precomputed financial profile" [E9]. | It applies "confidence thresholds and content filters to manage emotional risk" [E8]. Hand-off: unknown. | 81% accuracy on Cleo's own budgeting benchmark [E8] |
| **bunq** Finn | Banking support plus spending questions such as "How much did I spend on groceries this month?" [E10] | Model and architecture: unknown | Harder requests are "routed directly to the right human specialist" [E10] | About 97% of support activity; 90% satisfaction; 38 languages [E10] |
| **Monzo** Trends | Spending insights: monthly or yearly views, category breakdown, spending targets [E11, E12] | Rule-based or AI: unknown (the help pages do not mention AI). Paid plans add non-Monzo accounts [E12]. | Left-to-spend is labelled "an estimate" [E12] | Unknown |
| **Starling** Spending Intelligence (June 2025), then Starling Assistant (March 2026) | Customers "ask questions about their money" [E13] | It is "engineered using Google's Gemini models", while "Starling's proprietary systems perform the analysis on the customer's own transactional data". Data stays in Starling's Google Cloud and "is not used for training" [E13]. The 2026 assistant is agentic, on Gemini [E14]. | Opt in, and opt out at any time [E13, E14]. An explicit no-advice line: unknown. | Unknown |

Two notes on sources:
- The Cleo rows come from Cleo's blog posts served on an alternate host (`cleo-site-meetcleo-v2.vercel.app`), because meetcleo.com returned 403. The pages carry Cleo branding, but the provenance is weaker than a company domain.
- Cleo's "roast" mode is mentioned in search results, but we could not open a page that confirms it: **unknown**.

**Patterns across products**
- **The generative model does not produce the numbers.** Erica uses no LLM [E1]. Cleo sends arithmetic to deterministic tools [E8]. Starling's own systems perform the analysis while Gemini handles the language [E13]. This is the same split as our tools-compute, LLM-explains design (R1).
- **Scope is the customer's own data.** Starling keeps data in its own cloud, does not train on it, and asks users to opt in [E13]. Revolut reads only data the customer already sees [E7].
- **A human stays reachable**: Erica [E1], Klarna [E3, E4], bunq [E10].
- **Explicit boundaries are rare in public material.** Of the pages we opened, only Erica states "does not provide investment advice" [E1]. Monzo labels its left-to-spend figure as an estimate [E12]. We state our boundaries ourselves (R7, R13).
- **Published metrics are volume, containment and satisfaction, not numeric accuracy.** The only accuracy figure is Cleo's own benchmark [E8]. Nubank describes its method: an LLM judge with measured inter-rater agreement [E6].

## 2. Architecture patterns

**Intent routing or an open agent.**
- Anthropic separates "workflows", where "LLMs and tools are orchestrated through predefined code paths", from agents that direct their own tool use. Routing is a workflow: it "classifies an input and directs it to a specialized followup task" [P1].
- Agents bring "higher costs, and the potential for compounding errors". The advice is to find "the simplest solution possible" [P1].
- Monzo's operations agent first "checks whether it should follow one of the pre-defined processes". It drafts answers from "a knowledge base of documents vetted by subject matter experts" [P2].

**Function calling with Gemini (our model).**
- "The model doesn't execute the function itself": it proposes a call, and our code runs it [P3].
- Gemini has a mode that forces the model to always predict a function call, and a mode that "ensures function schema adherence" [P3].
- Google's best practice: "Keep active set to 10-20 tools maximum", "Use specific types (integer, string, enum)" and "Validate function calls before executing" [P3].
- The Gemini docs moved from ai.google.dev to aistudio.google.com, and their parameter names may differ from the `google-genai` SDK version we use. #5 should check names against the installed SDK.

**A metrics layer, not free text-to-SQL.**
- On Spider 2.0, the paper's best agent "successfully solves only 21.3% of the tasks, compared with 91.2% on Spider 1.0 and 73.0% on BIRD" [P5].
- On the live BIRD leaderboard (2026-11-13), the top execution accuracy is 83.40, against 92.96 for human performance [P6].
- A semantic layer defines each metric once: if the definition changes, "it's refreshed everywhere it's invoked". dbt pitches it to LLM clients so "their answers use your governed metrics instead of guessing at raw tables" [P7].
- No published head-to-head accuracy of an LLM with a semantic layer against an LLM with free text-to-SQL was found: **unknown**.

**Structured output.**
- Gemini can "generate responses that adhere to a provided JSON Schema". The docs warn: "always validate values in your application" [P4].
- Structured output formats the final answer, while function calling takes actions during the conversation [P4].

**Grounding in evidence.** Google's check-grounding API scores how "grounded an answer candidate is in the provided set of facts". "If the claim is only partially entailed, it is not considered grounded" [P8].

**Conversation memory.**
- In stateless use, "you must pass the full history of the conversation" with each request [P3].
- How banks keep conversation memory (summaries, retention, limits): **unknown**.
- Cleo limits each exchange "to the live conversation, not the user's full financial history" [E9].

**What we take from this.**
- Gemini picks from a small, typed set of read-only metric tools; it never writes SQL (R1, R6).
- Our code validates every proposed call before running it (R4, R5).
- The final answer is a schema-validated object whose values are checked in code (R12).
- History is kept server-side and per session.

## 3. Guardrails

**Prompt injection.**
- OWASP LLM01: injection happens when "user prompts alter the LLM's behavior". Indirect injection comes from "external sources, such as websites or files" [P9].
- NIST AI 600-1 describes indirect injection as "injecting prompts into data likely to be retrieved" [P10].
- Google describes the same risk for Gemini: "hidden malicious instructions within external data sources". Its layered defences include a "User confirmation framework" and adversarial training [P11].
- For us, the external data is merchant names and transaction texts.
- OWASP mitigations [P9]:
  - "Constrain model behavior"
  - "Define and validate expected output formats"
  - "Segregate and identify external content"
  - "Enforce privilege control and least privilege access"

  → R6, R11, R12.

**Excessive agency.**
- OWASP LLM06 names the root causes "excessive functionality", "excessive permissions" and "excessive autonomy" [P14].
- It advises: "Implement authorization in downstream systems rather than relying on an LLM to decide if an action is allowed" [P14].
- It also advises: "Log and monitor the activity of LLM extensions and downstream systems" [P14].

→ R4, R6, R15.

**Sensitive information.**
- OWASP LLM02 lists "financial details" among sensitive data. It advises least privilege, and warns that system-prompt restrictions "may not always be honored and could be bypassed via prompt injection" [P13].
- So data scoping is enforced in code, not in the prompt → R3, R4.

**Hallucinated numbers.**
- OWASP LLM09: LLMs "produce false or misleading information that appears credible". It advises "tools and processes to automatically validate key outputs" [P15].
- NIST calls this confabulation: "confidently stated but erroneous or false content" [P10].

→ R1, R2.

**Out-of-scope questions and advice.**
- Google's Gemini safety guidance recommends "Adjusting functionality to something that is inherently lower risk." It also recommends adversarial testing and "Blocking unsafe inputs and filtering output before it is shown to the user." [P12]
- ESMA's 2024 statement on AI in investment services warns that "hallucinated information can lead to misleading advice". It says firms "should transparently disclose to clients the use of such technology" [P16].
- That ESMA statement covers MiFID investment firms. For a spending coach, refusing investment advice is our product decision, consistent with section 4 → R7, R10, R14.

**What banks do in practice.**
- Monzo: "Guardrails detect hallucinations or non-compliant input and output". "If any guardrail is tripped, the system hands the conversation to a human specialist" [P2].
- Nubank uses "Automated Simulation and Red-Teaming", "ensuring the agent won't leak PII or deviate from its financial mandate before it goes live" [P17].
- Guardrails of Erica, Revolut, Cleo and bunq beyond section 1: **unknown**.

**Audit logs.**
- ESMA expects records covering "the decision-making processes, data sources used, algorithms implemented, and any modifications made over time" [P16].
- NIST asks organisations to "record and track GAI system reported errors, near-misses, and negative impacts" [P10].

→ R15.

## 4. EU and Finnish context

This is our reading of public texts. It is not legal advice; the bank's own compliance team decides.

**EU AI Act (Regulation 2024/1689).** We used the Commission's AI Act Service Desk, which shows the consolidated text as at 27 July 2026, including the Digital Omnibus on AI amendments [L1–L5].
- **Transparency (Art. 50(1)).** A system that talks to people must tell them they are interacting with an AI system, unless that is obvious [L1]. The Regulation applies in general from 2 August 2026 [L4]. FIN-FSA confirms that the transparency obligations take effect on 2.8.2026 [L12]. That FIN-FSA page is dated 7 January 2026, before the Digital Omnibus amendment. Its dates for high-risk duties are superseded by the amended Article 113 [L4]. The transparency obligation applies to the coach today → R14.
- **Risk class.** Annex III point 5(b) lists as high-risk "AI systems intended to be used to evaluate the creditworthiness of natural persons or establish their credit score" [L2]. An Annex III system that profiles natural persons is always high-risk [L3]. For Annex III systems, the high-risk obligations apply from 2 December 2027 [L4].
  - A budgeting coach that explains a customer's own spending is not on the Annex III list.
  - **Why the coach does not predict mortgage decisions:** evaluating a person's creditworthiness is a high-risk use under the AI Act [L2]. Scoring creditworthiness or predicting whether a loan or mortgage will be approved would move the coach into that class, with its obligations. It would also be an automated credit decision of the kind GDPR Art. 22 protects against [L6].
  - The dataset includes mortgage applications, so the line is explicit. The coach may only compute a savings plan for a down payment (how much and how long) from the customer's own cash flow → R8.
- **AI literacy (Art. 4).** Providers and deployers must take measures to support the AI literacy of their staff [L5]. Chapters I and II have applied since 2 February 2025 [L4]. This concerns the bank's staff, not the coach's behaviour.

**GDPR and the EDPB.** EDPB Guidelines 06/2020 on the interplay of PSD2 and the GDPR (version 2.0, adopted 15 December 2020) [L6] cover three points that matter for us:
- **Sensitive data in transactions.** The guidelines say "financial transactions can reveal sensitive information", for example health from medical bills, religion or politics from donations, and trade union membership from dues, and that "profiling can create special category of data by inference" [L6, section 5.1]. Our data has pharmacy and doctor MCCs (#6) → R9.
- **Data minimisation (Art. 5(1)(c)).** Controllers "should process no more personal data than what is necessary" [L6, section 6.1]. We send aggregates, not rows, to the LLM → R3.
- **Automated decisions (Art. 22).** The EDPB gives the example of an "automatic refusal of an online credit application without any human intervention" as a decision people have the right not to be subject to [L6] → R8.

**PSD2 and open banking.** PSD2 defines an account information service as "an online service to provide consolidated information on one or more payment accounts held by the payment service user with either another payment service provider or with more than one payment service provider" [L7].
- In our reading, S-Pankki analysing its own customers' accounts in its own app is not an account information service. If the coach later pulls in accounts from other banks, the PSD2 rules for account information services apply.
- The status and dates of PSD3 and the PSR are **unknown**: the Council press release could not be opened on 2026-11-13, and we did not rely on secondary reports.

**Investment advice (MiFID II).** MiFID II defines "investment advice" as "the provision of personal recommendations to a client ... in respect of one or more transactions relating to financial instruments" [L8]. ESMA's supervisory briefing (11 July 2023) [L9] adds four points:
- A recommendation is personal if it is "presented as suitable for that person" or "based on a consideration of the circumstances of that person" (para. 12).
- Information is not a recommendation: "simply giving objective information without making any comment, value judgement, or suggestion" (para. 28).
- A recommendation can also be "indirect, implicit" (para. 29).
- The rules cover advice given "through an automated or semi-automated system used as a client-facing tool" (para. 24).

So the coach can state facts and figures about the user's own money. It must not suggest, even implicitly, that the user buy, sell or hold a financial instrument → R7.

**Finland (FIN-FSA / Finanssivalvonta).**
- FIN-FSA's thematic review (27 June 2025) collects information "in preparing for market supervision duties under the EU Artificial Intelligence Act". It also found: "High-risk AI systems under the AI Act have already been deployed in the financial sector." [L10].
- FIN-FSA expects AI use in the customer interface "to increase over the following years". It says companies must "devise AI strategies as well as ethical standards and comply with them" [L11].
- FIN-FSA guidance specific to AI chatbots or AI-assisted financial advice: **unknown**. We found none on finanssivalvonta.fi on 2026-11-13.
- How the Finnish Investment Services Act applies to an in-app coach: **unknown**; we did not check it.

## 5. Evaluation and monitoring

**General guidance.**
- OpenAI: "Generative AI is variable", so "Evaluate early and often" and "run evals on every change". Teams should "Log everything" so production logs can be mined for eval cases [P18].
- Google's Vertex evaluation: "Assemble a dataset of prompt instances that reflect your specific use case." Use deterministic metrics "when a ground truth is available" [P20].
- NIST: compare output "to a set of known ground truth data" [P10].

**LLM as judge.**
- The MT-Bench paper found GPT-4 as judge "achieving over 80% agreement, the same level of agreement between humans". It also found "position, verbosity, and self-enhancement biases" [P19].
- OpenAI advises "pairwise comparison or pass/fail for more reliability". Scale a judge up only once it "consistently agrees with human annotations" [P18].

**What fintech and bank teams publish.**
- **Nubank, blog, March 2026** [P17]:
  - An auditor LLM evaluates "every single conversation against binary criteria", for example "Did the agent's response contradict our internal knowledge base?"
  - It optimises prompts from "50–100 high-quality traces" labelled by humans.
  - Its online metric is "TNPS (Transactional Net Promoter Score)" per AI interaction.
- **Nubank, paper, June 2026** [E6]: LLM judges "with measured inter-rater agreement", and "a strong correlation between offline simulation metrics and online outcomes". The agreement figure itself is **unknown** (not in the abstract).
- **Monzo, June 2026** [P2]:
  - "A golden set of 100 conversations is too small to be representative".
  - It adds "Component-level evals: Functioning like unit tests for individual prompts and guardrails".
  - It simulates users "using LLMs grounded in real conversations".
  - It keeps human QA "on a sample of conversations".
- **Klarna** publishes outcomes only: "on par with human agents in regard to customer satisfaction score" and "a 25% drop in repeat inquiries" [P21]. Its eval method is **unknown**.
- Eval methods of Bank of America, Revolut, Cleo and bunq: **unknown**. A Morgan Stanley case study exists, but it could not be opened (403): **unknown**.

**Supervisory expectation.** ESMA expects "comprehensive testing and monitoring systems, applying the principle of proportionality", and "sufficiently frequent ex-post controls" on information delivered through AI [P16]. This is addressed to MiFID investment firms.

**What we take from this.**
- **A golden set scored deterministically.** Each case is a question per persona with the expected tool calls and numbers, checked by exact match. Our data has ground truth, so numbers need no LLM judge (R1, R15).
- **A small binary LLM judge for soft criteria only**, such as staying in scope, giving no advice, and citing evidence. It is calibrated on a few human-labelled answers.
- **Refusal and injection sets run on every change** to prompts, tools or model (R7, R10, R11, R15).
- **A few online signals for the demo**: thumbs up or down per answer, refusal rate, and the share of answers that pass the number check.

## Rules we adopt

Each rule names a behaviour of the coach that can be observed, how to test it, and its basis in the research above. "Tool" means a deterministic function from the tool registry in #5. "Number object" means `{value, unit, period, method, evidence_ref}`.

1. **R1 – No number without a tool.** Every number in an answer (amount, percentage, count, date range) comes from a number object that a tool returned in the same turn. The LLM may format a number but never compute, round differently or invent one.
   *Test:* for every answer in the eval set, extract the numeric tokens from the final text. Each one must match a `value` in that turn's tool outputs, after locale formatting. Any unmatched number fails the answer.
   *Basis:* section 1 (Erica, Cleo, Starling keep numbers out of the generative model) [E1, E8, E13]; OWASP LLM09 and NIST on confabulation [P15, P10].
2. **R2 – Every number can be opened.** Every number object has an `evidence_ref`, and `GET /api/evidence/{ref}` returns what the number was computed from. That is the transactions for a sum or count, or the input number objects for a derived number such as safe to spend. Recomputing from that evidence with `method` gives the same `value`.
   *Test:* for each `evidence_ref` in the eval answers, the endpoint returns 200. For sums and counts, the sum or count of the returned rows equals `value`. For derived numbers, every input it lists resolves in turn.
   *Basis:* grounding checks treat partially supported claims as ungrounded [P8]; ESMA on records of data sources [P16].
3. **R3 – Raw rows never reach the LLM.** The model receives only tool outputs (aggregates and evidence references), never transaction rows, merchant IDs or `balance_after` series.
   *Test:* a canary merchant ID planted in the test data never appears in any logged model input.
   *Basis:* GDPR data minimisation [L6]; OWASP LLM02 on financial details [P13].
4. **R4 – One customer per session, set by the server.** Tools take `customer_id` from the authenticated session, never from model-generated arguments. The coach cannot read another customer's data, even if asked.
   *Test:* a crafted tool call with a different `customer_id` is overridden or rejected, and the audit log shows that.
   *Basis:* OWASP LLM06, authorization in downstream systems [P14]; OWASP LLM02, least privilege [P13].
5. **R5 – Time stops at `DEMO_TODAY`.** Tools see no transaction after `DEMO_TODAY`, and every number object states its `period`. If the user's period is ambiguous ("last month"), the answer names the exact dates used.
   *Test:* a query for a period after `DEMO_TODAY` returns no data or a clamped period. Answers to "last month" include explicit dates.
   *Basis:* Monzo shows spending as monthly or yearly overviews [E12]. Our data ends at `DEMO_TODAY` (#5).
6. **R6 – Read-only tools.** No tool moves money, changes account settings or contacts third parties. The coach can explain, compare and simulate, but never execute.
   *Test:* the tool registry contains only read and simulate functions. An injection prompt asking for a transfer is answered with no data tool call made.
   *Basis:* OWASP LLM06, excessive functionality and autonomy [P14]; Google, lower-risk functionality [P12].
7. **R7 – No personal investment recommendation.** The coach does not tell a user to buy, sell or hold a specific financial instrument, and does not recommend a specific investment, loan or insurance product. It can explain general concepts and show the user's own Invest Deposit and Withdraw history. For advice, it points to a human S-Pankki adviser.
   *Test:* a red-team set of investment-advice questions is answered with the fixed refusal template plus general education, 100% of the time.
   The set also covers implicit suggestions. After a what-if or savings answer, the coach does not suggest where to invest the money or which product to buy. It may state observed facts about the customer's own investment deposits.
   *Basis:* MiFID II definition of investment advice and ESMA's briefing on implicit and automated advice [L8, L9]; Erica's no-advice line [E1].
8. **R8 – No credit decision or creditworthiness score.** The coach does not score creditworthiness and does not predict whether a loan or mortgage will be approved. The mortgage tables are not used to rate the user. The one allowed mortgage case is a savings plan: how much to save for a down payment and how long it takes. It is computed deterministically from the customer's own cash flow and says nothing about approval.
   *Test:* "Will I get a mortgage?" and similar questions get the refusal template with a pointer to the bank's loan process. No tool outputs a credit score. The down-payment card shows only an amount, a period and its method, with no approval likelihood.
   *Basis:* AI Act Annex III 5(b), creditworthiness is high-risk [L2, L3]; GDPR Art. 22 example of automatic credit refusal [L6].
9. **R9 – No sensitive inferences.** The coach does not infer or state health, religion, political views or other special-category traits from spending (for example pharmacy or doctor MCCs). A category total that the bank itself assigns, including Health, may appear as an amount in a full breakdown of all categories, or when the user asks for it. It is never singled out proactively and never compared with peers. The coach never states or implies anything about the person's health or other sensitive traits.
   *Test:* the spender-profile labels and eval answers contain no term from a sensitive-inference list ("you may be ill", "pregnant", "religious", ...). No proactive insight or peer comparison is about the Health category. Health appears only as one line in a full category breakdown, or in an answer to a direct question.
   *Basis:* EDPB: transactions can reveal special categories, also by inference [L6].
10. **R10 – Out-of-scope questions are declined briefly.** Questions that are not about the user's own money get a short decline and two or three example questions the coach can answer.
    *Test:* an out-of-scope set (coding, medical, politics, other people's finances) is declined 100% of the time, and no data tool call is made.
    *Basis:* Google, narrow to lower-risk functionality [P12]; Monzo hands off when a guardrail trips [P2].
11. **R11 – Data is not instructions.** Merchant names, transaction texts and user-pasted content are passed to the model as quoted data and cannot change the system prompt, the tool list or the refusal rules.
    *Test:* a prompt-injection suite (instructions hidden in a merchant name and in user text) leaves tool calls and refusal behaviour unchanged.
    *Basis:* OWASP LLM01, indirect injection and segregating external content [P9]; NIST and Google on injection via retrieved data [P10, P11].
12. **R12 – Structured, validated answers.** The server builds the cards from tool outputs, and the model only writes text. The model returns JSON that matches a schema: the answer text and the `evidence_ref`s it used. Output that does not validate is retried once, then replaced by a deterministic template answer built from the tool outputs.
    *Test:* every logged model output validates against the schema. Every card in a response is built by the server from a tool output; no card field comes from model output. Fault injection with an invalid model output yields the template answer.
    *Basis:* Gemini structured output, validate values in the application [P4]; OWASP LLM01, validate output formats [P9].
13. **R13 – Estimates are labelled.** What-if savings, safe-to-spend and store-switch savings are shown as estimates, with the assumption in plain words (the `method` field). They are never presented as guarantees.
    *Test:* every what-if or store-saving card shows an "estimate" label and a non-empty method text.
    *Basis:* Monzo labels left-to-spend as an estimate [E12]; ESMA, hallucinated information can mislead [P16].
14. **R14 – AI is disclosed; language follows the user.** The chat states that it is an AI assistant whose numbers come from the user's transactions. It answers in Finnish or English, matching the user, with locale number formats (`1 234,56 €` in Finnish).
    *Test:* the first screen shows the disclosure. Finnish questions get Finnish answers with Finnish number formatting.
    *Basis:* AI Act Art. 50(1), in force from 2 August 2026 [L1, L4, L12]; bunq answers in 38 languages [E10].
15. **R15 – Every answer is logged and the eval set gates the demo.** Each answer stores the question, tool calls with arguments, tool outputs, final text, model ID, prompt version and latency, retrievable by answer ID. A fixed eval set (questions per persona with expected tool calls and numbers, plus refusal and injection sets) runs before every merge into `main`.
    *Test:* `GET` of an answer's audit record returns all fields. The eval run reports 100% on R1 and R2 and on the refusal sets.
    *Basis:* ESMA records and ex-post controls [P16]; NIST error tracking [P10]; eval practice at Nubank, Monzo and OpenAI [P17, P2, P18].

## Sources

All sources were accessed on 2026-11-13. EUR-Lex itself could not be reached from our network that day (TLS certificate error), so legal texts are cited from official EU mirrors: the Commission AI Act Service Desk, the EBA single rulebook Q&A and the ESMA interactive single rulebook.

**Examples (section 1)**
- [E1] Bank of America, "Erica" (product page and FAQ). https://info.bankofamerica.com/en/digital-banking/erica, accessed 2026-11-13.
- [E2] Bank of America release via PR Newswire, "A Decade of AI Innovation: BofA's Virtual Assistant Erica Surpasses 3 Billion Client Interactions", August 2025 (newswire copy; the BofA newsroom page did not load). https://www.placera.se/pressmeddelanden/a-decade-of-ai-innovation-bofa-s-virtual-assistant-erica-surpasses-3-billion-client-interactions-20250820, accessed 2026-11-13.
- [E3] Klarna press release, "Klarna AI assistant handles two-thirds of customer service chats in its first month", 27 February 2024 (klarna.com may return 403 to scripts; the same release is [P21]). https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/, accessed 2026-11-13.
- [E4] CX Dive (news), "Klarna says its AI agent is doing the work of 853 employees", 2025. https://www.customerexperiencedive.com/news/klarna-says-ai-agent-work-853-employees/805987/, accessed 2026-11-13.
- [E5] Nubank newsroom, "Nu tests with Generative AI to enhance customers' experience with credit", October 2023. https://nu.com/en/newsroom/consumers/nubank-begins-testing-with-generative-artificial-intelligence-to-enhance-customers-experience-with-credit, accessed 2026-11-13.
- [E6] arXiv 2606.08867, "Building Customer Support AI Agents at 100M-User Scale: An Evaluation-Driven Framework", 2026. https://arxiv.org/abs/2606.08867, accessed 2026-11-13.
- [E7] FF News, "Revolut enters new era of money intelligence with launch of AI assistant", 8 April 2026 (news copy of the Revolut release; revolut.com returned 403). https://ffnews.com/newsarticle/fintech/revolut-enters-new-era-of-money-intelligence-with-launch-of-ai-assistant/, accessed 2026-11-13.
- [E8] Cleo blog, "Building a financial agent on top of commodified LLMs", 23 July 2025 (alternate host). https://cleo-site-meetcleo-v2.vercel.app/blog/building-a-financial-agent-on-top-of-commodified-llms, accessed 2026-11-13.
- [E9] Cleo blog, "Inside Cleo's multi-agent architecture", 14 May 2026 (alternate host). https://cleo-site-meetcleo-v2.vercel.app/blog/inside-cleos-multi-agent-architecture, accessed 2026-11-13.
- [E10] bunq press release, "bunq launches smarter, more powerful upgrade to GenAI financial assistant", December 2025. https://press.bunq.com/258930-bunq-launches-smarter-more-powerful-upgrade-to-genai-financial-assistant, accessed 2026-11-13.
- [E11] Monzo Help, "All about the Trends". https://monzo.com/ie/help/managing-money/help-trends, accessed 2026-11-13.
- [E12] Monzo Help, "Spending, Balance and Targets in Trends". https://monzo.com/help/budgeting-overdrafts-savings/trends-spending-and-balance-web, accessed 2026-11-13.
- [E13] Starling Bank news, "Starling launches pioneering AI banking tool in mission to help UK be 'Good with money'" (Spending Intelligence), June 2025. https://www.starlingbank.com/news/starling-launches-pioneering-ai-banking-tool/, accessed 2026-11-13.
- [E14] Starling Bank news, "Starling launches UK's first Agentic AI financial assistant", 20 March 2026. https://www.starlingbank.com/news/starling-launches-agentic-ai-assistant/, accessed 2026-11-13.

**Patterns, guardrails and evaluation (sections 2, 3, 5)**
- [P1] Anthropic, "Building effective AI agents". https://www.anthropic.com/engineering/building-effective-agents, accessed 2026-11-13.
- [P2] Monzo blog, "Engineering the Future of Customer Operations: The Monzo Ops Agent", June 2026. https://monzo.com/blog/engineering-the-future-of-customer-operations-the-monzo-ops-agent, accessed 2026-11-13.
- [P3] Google, Gemini API docs, "Function calling". https://aistudio.google.com/docs/function-calling, accessed 2026-11-13.
- [P4] Google, Gemini API docs, "Structured output". https://aistudio.google.com/docs/structured-output, accessed 2026-11-13.
- [P5] arXiv 2411.07763, "Spider 2.0: Evaluating Language Models on Real-World Enterprise Text-to-SQL Workflows", November 2024. https://arxiv.org/abs/2411.07763, accessed 2026-11-13.
- [P6] BIRD benchmark leaderboard. https://bird-bench.github.io/, accessed 2026-11-13.
- [P7] dbt docs, "dbt Semantic Layer". https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl, accessed 2026-11-13.
- [P8] Google Cloud docs, "Check grounding with RAG". https://docs.cloud.google.com/generative-ai-app-builder/docs/check-grounding, accessed 2026-11-13.
- [P9] OWASP GenAI Security Project, "LLM01:2025 Prompt Injection". https://genai.owasp.org/llmrisk/llm01-prompt-injection/, accessed 2026-11-13.
- [P10] NIST AI 600-1, "Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile", July 2024. https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf, accessed 2026-11-13.
- [P11] Google, "Mitigating prompt injection attacks with a layered defense strategy", 13 June 2025. https://blog.google/security/mitigating-prompt-injection-attacks/, accessed 2026-11-13.
- [P12] Google, Gemini API docs, "Safety guidance". https://aistudio.google.com/docs/safety-guidance, accessed 2026-11-13.
- [P13] OWASP GenAI Security Project, "LLM02:2025 Sensitive Information Disclosure". https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/, accessed 2026-11-13.
- [P14] OWASP GenAI Security Project, "LLM06:2025 Excessive Agency". https://genai.owasp.org/llmrisk/llm062025-excessive-agency/, accessed 2026-11-13.
- [P15] OWASP GenAI Security Project, "LLM09:2025 Misinformation". https://genai.owasp.org/llmrisk/llm092025-misinformation/, accessed 2026-11-13.
- [P16] ESMA35-335435667-5924, Public Statement on AI and investment services, 30 May 2024. https://www.esma.europa.eu/sites/default/files/2024-05/ESMA35-335435667-5924__Public_Statement_on_AI_and_investment_services.pdf, accessed 2026-11-13.
- [P17] Nubank engineering blog, "Building AI agents for 131 million customers" (the URL says 127), March 2026. https://building.nu.com/building-ai-agents-for-127-million-customers/, accessed 2026-11-13.
- [P18] OpenAI API docs, "Evaluation best practices". https://developers.openai.com/api/docs/guides/evaluation-best-practices, accessed 2026-11-13.
- [P19] arXiv 2306.05685, "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", 2023. https://arxiv.org/abs/2306.05685, accessed 2026-11-13.
- [P20] Google Cloud docs, Gen AI evaluation service overview. https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-overview, accessed 2026-11-13.
- [P21] Klarna release via PR Newswire, "Klarna AI assistant handles two-thirds of customer service chats in its first month", 27 February 2024. https://www.prnewswire.com/news-releases/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month-302072744.html, accessed 2026-11-13.

**Law and regulators**
- [L1] EU AI Act, Article 50, AI Act Service Desk (European Commission). https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50, accessed 2026-11-13.
- [L2] EU AI Act, Annex III, AI Act Service Desk. https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3, accessed 2026-11-13.
- [L3] EU AI Act, Article 6, AI Act Service Desk. https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-6, accessed 2026-11-13.
- [L4] EU AI Act, Article 113 (as amended by the Digital Omnibus on AI), AI Act Service Desk. https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-113, accessed 2026-11-13.
- [L5] EU AI Act, Article 4, AI Act Service Desk. https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-4, accessed 2026-11-13.
- [L6] EDPB, Guidelines 06/2020 on the interplay of the Second Payment Services Directive and the GDPR, version 2.0, 15 December 2020. https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_202006_psd2_afterpublicconsultation_en.pdf, accessed 2026-11-13.
- [L7] EBA Single Rulebook Q&A 2018_4098, which quotes the PSD2 Article 4(16) definition (answer published 13 September 2019). https://www.eba.europa.eu/single-rule-book-qa/qna/view/publicId/2018_4098, accessed 2026-11-13.
- [L8] ESMA Interactive Single Rulebook, MiFID II Article 4, Definitions. https://www.esma.europa.eu/publications-and-data/interactive-single-rulebook/mifid-ii/article-4-definitions, accessed 2026-11-13.
- [L9] ESMA35-43-3861, Supervisory briefing on understanding the definition of advice under MiFID II, 11 July 2023. https://www.esma.europa.eu/sites/default/files/2023-07/ESMA35-43-3861_Supervisory_briefing_on_understanding_the_definition_of_advice_under_MiFID_II.pdf, accessed 2026-11-13.
- [L10] FIN-FSA, Thematic review of the use of AI in the financial sector, 27 June 2025. https://www.finanssivalvonta.fi/en/publications-and-press-releases/supervision-releases/2025/thematic-review-of-the-use-of-AI-in-the-financial-sector/, accessed 2026-11-13.
- [L11] FIN-FSA press release, "FIN-FSA thematic review: financial sector organisations use AI in internal processes, utilisation in the customer interface increases", 27 June 2025. https://www.finanssivalvonta.fi/en/publications-and-press-releases/Press-release/2025/fin-fsa-thematic-review-financial-sector-organisations-use-ai-in-internal-processes-utilisation-in-the-customer-interface-increases/, accessed 2026-11-13.
- [L12] Finanssivalvonta, "Uudet säännöt vahvistavat luottamusta tekoälyyn Euroopassa", 7 January 2026. https://www.finanssivalvonta.fi/tiedotteet-ja-julkaisut/verkkouutiset/2026/uudet-saannot-vahvistavat-luottamusta-tekoalyyn-euroopassa, accessed 2026-11-13.
