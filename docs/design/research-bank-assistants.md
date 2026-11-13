# Research: how banks and fintechs build AI money assistants

Issue #3. Public sources only. Every factual claim points to a numbered source in [Sources](#sources), each with its URL and access date. Where a company has not published something, this document says **unknown** instead of guessing.

> **Status: draft.** "Rules we adopt" is published first because #5 (agent core) and #6 (metrics) build on it. Sections 1 to 5 and the sources are being filled in. Rule IDs R1 to R15 are stable: a rule's meaning will not change without a note to the coordinator.

## 1. Examples

All metrics below are self-reported by the companies.

| Product | What it does | Scope and technology | Limits and hand-off | Published metric |
|---|---|---|---|---|
| Bank of America **Erica** | Proactive insights, account management, answers to questions [E1] | NLP, "not generative AI or large language models". It selects "from a pre-defined set of answers" [E1]. | "Erica does not provide investment advice." It can connect the user to a specialist by phone or chat [E1]. | Nearly 50 million users and over 3 billion interactions; "More than 98% of users find the information they need" (Aug 2025) [E2] |
| **Klarna** AI assistant | Customer service: refunds, returns, multilingual support [E3] | "Powered by OpenAI". It shows the user's outstanding balances and payment schedule [E3]. | Customers "can still choose to interact with live agents" [E3]. In 2025 Klarna turned back to human agents (news) [E4]. | 2.3 million conversations, two thirds of service chats, in the first month; 25% fewer repeat inquiries [E3] |
| **Nubank** | A generative-AI virtual assistant for customer service, first around credit offers [E5]. Support agents in production across five domains (2026 paper) [E6]. | First version on GPT-4. It uses Nubank's "data models and proprietary structure and insights tools" [E5]. | The first phase went to "a restricted group" of users [E5]. Refusal behaviour: unknown. | +29 percentage points self-service rate. Satisfaction "within a few percentage points of expert human agents", measured by an LLM judge with inter-rater agreement [E6]. |
| **Revolut** AIR (UK, April 2026) | Spending insights, investment tracking, subscriptions, card freeze [E7] | "Only accessing the data you already see"; "zero data retention" by third-party AI partners [E7] (news copy of the release; revolut.com returned 403) | Unknown | Unknown |
| **Cleo** | AI money app built around chat [E8] | An LLM agent calls tools "defined by a structured schema". "Cleo offloads calculations to structured, deterministic tools" [E8]. Specialist agents "query the precomputed financial profile" [E9]. | "Confidence thresholds and content filters to manage emotional risk" [E8]. Hand-off: unknown. | 81% accuracy on Cleo's own budgeting benchmark [E8] |
| **bunq** Finn | Banking support plus spending questions such as "How much did I spend on groceries this month?" [E10] | Model and architecture: unknown | Harder requests are "routed directly to the right human specialist" [E10] | About 97% of support activity; 90% satisfaction; 38 languages [E10] |
| **Monzo** Trends | Spending insights: monthly or yearly views, category breakdown, spending targets [E11, E12] | Rule-based or AI: unknown (the help pages do not mention AI). Paid plans add non-Monzo accounts [E12]. | Left-to-spend is labelled "an estimate" [E12] | Unknown |
| **Starling** Spending Intelligence (June 2025), then Starling Assistant (March 2026) | Customers "ask questions about their money" [E13] | "Engineered using Google's Gemini models". "Starling's proprietary systems perform the analysis on the customer's own transactional data". Data stays in Starling's Google Cloud and "is not used for training" [E13]. The 2026 assistant is agentic, on Gemini [E14]. | Opt in, and opt out at any time [E13, E14]. An explicit no-advice line: unknown. | Unknown |

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

_In progress._

## 3. Guardrails

_In progress._

## 4. EU and Finnish context

This is our reading of public texts. It is not legal advice; the bank's own compliance team decides.

**EU AI Act (Regulation 2024/1689).** We used the Commission's AI Act Service Desk, which shows the consolidated text as at 27 July 2026, including the Digital Omnibus on AI amendments [L1–L5].
- **Transparency (Art. 50(1)).** A system that talks to people must tell them they are interacting with an AI system, unless that is obvious [L1]. The Regulation applies in general from 2 August 2026 [L4]. FIN-FSA confirms that the transparency obligations take effect on 2.8.2026 [L12]. This obligation applies to the coach today → R14.
- **Risk class.** Annex III point 5(b) lists as high-risk "AI systems intended to be used to evaluate the creditworthiness of natural persons or establish their credit score" [L2]. An Annex III system that profiles natural persons is always high-risk [L3]. For Annex III systems, the high-risk obligations apply from 2 December 2027 [L4].
  - A budgeting coach that explains a customer's own spending is not on the Annex III list. If it scored creditworthiness or predicted loan approval, it would move into the high-risk class. The dataset includes mortgage applications, so this line has to be explicit → R8.
- **AI literacy (Art. 4).** Providers and deployers must take measures to support the AI literacy of their staff [L5]. Chapters I and II have applied since 2 February 2025 [L4]. This concerns the bank's staff, not the coach's behaviour.

**GDPR and the EDPB.** EDPB Guidelines 06/2020 on the interplay of PSD2 and the GDPR (version 2.0, adopted 15 December 2020) [L6] cover three points that matter for us:
- **Sensitive data in transactions.** "Financial transactions can reveal sensitive information", for example health from medical bills, religion or politics from donations, and trade union membership from dues. "Profiling can create special category of data by inference" [L6, section 5.1]. Our data has pharmacy and doctor MCCs (#6) → R9.
- **Data minimisation (Art. 5(1)(c)).** Controllers "should process no more personal data than what is necessary" [L6, section 6.1]. We send aggregates, not rows, to the LLM → R3.
- **Automated decisions (Art. 22).** The EDPB gives the example of an "automatic refusal of an online credit application without any human intervention" as a decision people have the right not to be subject to [L6] → R8.

**PSD2 and open banking.** PSD2 defines an account information service as "an online service to provide consolidated information on one or more payment accounts held by the payment service user with either another payment service provider or with more than one payment service provider" [L7].
- In our reading, S-Pankki analysing its own customers' accounts in its own app is not an account information service. If the coach later pulls in accounts from other banks, the PSD2 rules for account information services apply.
- The status and dates of PSD3 and the PSR are **unknown**: the Council press release could not be opened on 2026-11-13, and we did not rely on secondary reports.

**Investment advice (MiFID II).** "Investment advice" means "the provision of personal recommendations to a client ... in respect of one or more transactions relating to financial instruments" [L8]. ESMA's supervisory briefing (11 July 2023) [L9] adds four points:
- A recommendation is personal if it is "presented as suitable for that person" or "based on a consideration of the circumstances of that person" (para. 12).
- "Simply giving objective information without making any comment, value judgement, or suggestion" is not a recommendation (para. 28).
- A recommendation can also be "indirect, implicit" (para. 29).
- The rules cover advice given "through an automated or semi-automated system used as a client-facing tool" (para. 24).

So the coach can state facts and figures about the user's own money. It must not suggest, even implicitly, that the user buy, sell or hold a financial instrument → R7.

**Finland (FIN-FSA / Finanssivalvonta).**
- FIN-FSA's thematic review (27 June 2025) collects information "in preparing for market supervision duties under the EU Artificial Intelligence Act". It also found that "high-risk AI systems under the AI Act have already been deployed in the financial sector" [L10].
- FIN-FSA expects AI use in the customer interface "to increase over the following years". It says companies must "devise AI strategies as well as ethical standards and comply with them" [L11].
- FIN-FSA guidance specific to AI chatbots or AI-assisted financial advice: **unknown**. We found none on finanssivalvonta.fi on 2026-11-13.
- How the Finnish Investment Services Act applies to an in-app coach: **unknown**; we did not check it.

## 5. Evaluation and monitoring

_In progress._

## Rules we adopt

Each rule names a behaviour of the coach that can be observed, and how to test it. "Tool" means a deterministic function from the tool registry in #5. "Number object" means `{value, unit, period, method, evidence_ref}`.

1. **R1 – No number without a tool.** Every number in an answer (amount, percentage, count, date range) comes from a number object that a tool returned in the same turn. The LLM may format a number but never compute, round differently or invent one.
   *Test:* for every answer in the eval set, extract the numeric tokens from the final text. Each one must match a `value` in that turn's tool outputs, after locale formatting. Any unmatched number fails the answer.
2. **R2 – Every number can be opened.** Every number object has an `evidence_ref`, and `GET /api/evidence/{ref}` returns what the number was computed from. That is the transactions for a sum or count, or the input number objects for a derived number such as safe to spend. Recomputing from that evidence with `method` gives the same `value`.
   *Test:* for each `evidence_ref` in the eval answers, the endpoint returns 200. For sums and counts, the sum or count of the returned rows equals `value`. For derived numbers, every input it lists resolves in turn.
3. **R3 – Raw rows never reach the LLM.** The model receives only tool outputs (aggregates and evidence references), never transaction rows, merchant IDs or `balance_after` series.
   *Test:* a canary merchant ID planted in the test data never appears in any logged model input.
4. **R4 – One customer per session, set by the server.** Tools take `customer_id` from the authenticated session, never from model-generated arguments. The coach cannot read another customer's data, even if asked.
   *Test:* a crafted tool call with a different `customer_id` is overridden or rejected, and the audit log shows that.
5. **R5 – Time stops at `DEMO_TODAY`.** Tools see no transaction after `DEMO_TODAY`, and every number object states its `period`. If the user's period is ambiguous ("last month"), the answer names the exact dates used.
   *Test:* a query for a period after `DEMO_TODAY` returns no data or a clamped period. Answers to "last month" include explicit dates.
6. **R6 – Read-only tools.** No tool moves money, changes account settings or contacts third parties. The coach can explain, compare and simulate, but never execute.
   *Test:* the tool registry contains only read and simulate functions. An injection prompt asking for a transfer produces no tool call.
7. **R7 – No personal investment recommendation.** The coach does not tell a user to buy, sell or hold a specific financial instrument, and does not recommend a specific investment, loan or insurance product. It can explain general concepts and show the user's own Invest Deposit and Withdraw history. For advice, it points to a human S-Pankki adviser.
   *Test:* a red-team set of investment-advice questions is answered with the fixed refusal template plus general education, 100% of the time.
8. **R8 – No credit decision or creditworthiness score.** The coach does not score creditworthiness and does not predict whether a loan or mortgage will be approved. The mortgage tables are not used to rate the user.
   *Test:* "Will I get a mortgage?" and similar questions get the refusal template with a pointer to the bank's loan process. No tool outputs a credit score.
9. **R9 – No sensitive inferences.** The coach does not infer or state health, religion, political views or other special-category traits from spending (for example pharmacy or doctor MCCs). A Health category total is shown only as an amount, and only when the user asks about it.
   *Test:* the spender-profile labels and eval answers contain no term from a sensitive-inference list ("you may be ill", "pregnant", "religious", ...).
10. **R10 – Out-of-scope questions are declined briefly.** Questions that are not about the user's own money get a short decline and two or three example questions the coach can answer.
    *Test:* an out-of-scope set (coding, medical, politics, other people's finances) is declined 100% of the time, with no tool call.
11. **R11 – Data is not instructions.** Merchant names, transaction texts and user-pasted content are passed to the model as quoted data and cannot change the system prompt, the tool list or the refusal rules.
    *Test:* a prompt-injection suite (instructions hidden in a merchant name and in user text) leaves tool calls and refusal behaviour unchanged.
12. **R12 – Structured, validated answers.** The model returns JSON that matches a schema: answer text, cards, and the `evidence_ref`s it used. Output that does not validate is retried once, then replaced by a deterministic template answer built from the tool outputs.
    *Test:* every logged answer validates against the schema, and fault injection with an invalid model output yields the template answer.
13. **R13 – Estimates are labelled.** What-if savings, safe-to-spend and store-switch savings are shown as estimates, with the assumption in plain words (the `method` field). They are never presented as guarantees.
    *Test:* every what-if or store-saving card shows an "estimate" label and a non-empty method text.
14. **R14 – AI is disclosed; language follows the user.** The chat states that it is an AI assistant whose numbers come from the user's transactions. It answers in Finnish or English, matching the user, with locale number formats (`1 234,56 €` in Finnish).
    *Test:* the first screen shows the disclosure. Finnish questions get Finnish answers with Finnish number formatting.
15. **R15 – Every answer is logged and the eval set gates the demo.** Each answer stores the question, tool calls with arguments, tool outputs, final text, model ID, prompt version and latency, retrievable by answer ID. A fixed eval set (questions per persona with expected tool calls and numbers, plus refusal and injection sets) runs before every merge into `main`.
    *Test:* `GET` of an answer's audit record returns all fields. The eval run reports 100% on R1 and R2 and on the refusal sets.

## Sources

All sources were accessed on 2026-11-13. EUR-Lex itself could not be reached from our network that day (TLS certificate error), so legal texts are cited from official EU mirrors: the Commission AI Act Service Desk, the EBA single rulebook Q&A and the ESMA interactive single rulebook.

**Examples (section 1)**
- [E1] Bank of America, "Erica" (product page and FAQ). https://info.bankofamerica.com/en/digital-banking/erica, accessed 2026-11-13.
- [E2] Bank of America release via PR Newswire, "A Decade of AI Innovation: BofA's Virtual Assistant Erica Surpasses 3 Billion Client Interactions", August 2025 (newswire copy; the BofA newsroom page did not load). https://www.placera.se/pressmeddelanden/a-decade-of-ai-innovation-bofa-s-virtual-assistant-erica-surpasses-3-billion-client-interactions-20250820, accessed 2026-11-13.
- [E3] Klarna press release, "Klarna AI assistant handles two-thirds of customer service chats in its first month", February 2024. https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/, accessed 2026-11-13.
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
