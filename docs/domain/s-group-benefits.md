# S-Group stores, S-Bonus and the payment benefit

Issue #4. Official public sources only: s-etukortti.fi, s-ryhma.fi, s-pankki.fi and abcasemat.fi. Every rule cites a numbered source in [Sources](#sources), each with its URL and access date. Where no official page says something, this document says **unknown**. Our own readings and assumptions are labelled **our reading** or **assumption**.

The machine-readable version is [`core/config/s_group_benefits.yaml`](../../core/config/s_group_benefits.yaml).

**Product decision (owner, recorded on issue #4).** S-Bonus is used **only as a what-if estimate**: the customer's own grocery spending times the officially published Bonus scale, labelled as an estimate with its assumptions (R13). No specific merchant is named or treated as an S-Group store until the bank confirms the mapping.

## Summary for the coach
- **Bonus** is a monthly percentage of the household's purchases at S-Group, from 1 % to 5 % [G2, G5]. The level comes from the month's total Bonus purchases, and the percentage applies to all purchases other than fuel [G4].
- **Fuel** at ABC earns no percentage Bonus. It earns a Refuelling Bonus of up to 5 cents per litre instead [G4, G6], and it still counts towards the monthly level: "fuel purchases still count towards your monthly Bonus purchases" [G5].
- **The payment benefit** (maksutapaetu) is a further 0.5 % when paying with an S-Etukortti Visa or S-Etukortti Debit card at S-Group's Finnish outlets [G4, G7]. Together with Bonus that is "jopa 5,5 %" [G7].
- Both are paid as money to the household's S-Pankki account by the 10th of the following month [G4, G5, G7].
- **Our dataset does not say which merchants belong to S-Group, and the coach treats none as one.** It shows Bonus only as a what-if on the customer's own spending (section 4).

## 1. S-Group chains by business type
From S-Group's own "Business operations" page [G1]:

| Business type | Chains named by S-Group |
|---|---|
| Grocery and non-food retail | Prisma, S-market, Sale, Alepa, ABC-Market (at some ABC stations) |
| Specialty and department stores | Sokos, Emotion (cosmetics) |
| Fuel and service stations | ABC service station stores, unstaffed ABC stations, ABC Carwash, ABC-lataus (electric car charging) |
| Hotels and restaurants | Sokos Hotels, Radisson Blu, Radisson RED; restaurant chains Rosso, Amarillo, Frans & les Femmes, Coffee House, and others |
| Banking | S-Bank (S-Pankki) |

- The page says "Alepa stores serve customers in the Helsinki metropolitan area, while Sale stores offer easy and convenient shopping in other parts of Finland" and "Unstaffed ABC stations are typically found in connection with Prisma, S-market and Sale stores" [G1].
- The complete list of chains, restaurants and partners where Bonus accumulates is published "in S-mobiili and on our website at S-Etukortti.fi" [G4]. A full outlet list was not collected here.

## 2. Bonus

**What it is.** "Bonus is a percentage-based cashback on all purchases made by your household during the month" [G5]. It goes up to "5% cashback on all your monthly purchases" [G5].

**Bonus tables.** On both table pages [G2, G3], each table's caption comes **after** the table in the same tab:
- The default table is captioned: this table "applies in all cooperatives except Osuuskauppa KPO and Koillismaan Osuuskauppa" [G2].
- The second table is captioned "KPO cooperative Bonus table". The third is captioned "Koilismaan Osuuskauppa Bonus table", the page's own spelling [G2].

The Finnish page shows the same three tables under "Talouden ostot / kk", "Bonusprosentti" and "Bonus kuukaudessa" [G3]. The rows from 200 € up are the same in all three tables, and only the lowest row differs:

| Household purchases / month | Bonus percent | Bonus / month | Tables |
|---|---|---|---|
| 900 € | 5.0 % | 45.00 € | all three |
| 800 € | 4.5 % | 36.00 € | all three |
| 700 € | 4.0 % | 28.00 € | all three |
| 600 € | 3.5 % | 21.00 € | all three |
| 500 € | 3.0 % | 15.00 € | all three |
| 400 € | 2.5 % | 10.00 € | all three |
| 300 € | 2.0 % | 6.00 € | all three |
| 200 € | 1.5 % | 3.00 € | all three |
| 100 € | 1.0 % | 1.00 € | KPO only (lowest row) |
| 50 € | 1.0 % | 0.50 € | default only (lowest row) |
| 1 € | 1.0 % | 0.01 € | Koillismaan Osuuskauppa only (lowest row) |

- **How the level is set.** "Purchases made by the co-op member household during the calendar month that accumulate Bonus and Refuelling Bonus are added together. The amount of Bonus purchases determines the level of the Bonus table according to which Bonus is paid as a percentage of purchases other than fuel purchases" [G4]. The table's own numbers confirm that the percentage applies to the whole month's purchases, not only the part above a threshold: 900 € × 5 % = 45 € [G2].
- **Purchases between two rows.** **Our reading:** a household gets the highest row whose amount is not above its monthly purchases, so 650 € gives 3.5 %. Below the lowest row there is no Bonus. The pages do not say this in words: **unknown**, and open question 1.
- **Which purchases count.** "Bonus accumulates only on the private purchases of the co-op member household" [G4]. The rules exclude [G4]:
  - "tobacco products, tobacco substitutes, smoking equipment, imitation tobacco products, e-cigarettes, nicotine liquids and nicotine preparations";
  - "beverages containing more than 1.2% by volume of ethyl alcohol and food products containing more than 2.8% by volume of ethyl alcohol";
  - "Most commission-based products, such as gambling and lottery products";
  - the buyer's purchases of S Group gift cards;
  - tax-free purchases;
  - purchases with a corporate card.

  The Bonus page adds two more under "these purchases do not earn Bonus": "Medicines reimbursed by Kela" and "Bottle returns" [G5].
- **Fuel and charging.** "Fuel purchased at ABC service stations and ABC unmanned stations does not accumulate Bonus. Fuel purchases accumulate Refuelling Bonus ... Other ABC purchases accumulate Bonus." Also, "Charging electric cars at ABC charging points accumulates Bonus" [G4]. Fuel still raises the level: "fuel purchases still count towards your monthly Bonus purchases" [G5].
- **Refuelling Bonus.** It is "paid in cents per litre for fuel purchases" at the household's monthly level [G4]. The Bonus page gives one example: "if all your purchases in a month qualify for 3% Bonus, you get 3 cents Refuelling Bonus for every litre you fill up that month" [G5]. ABC says "Tankkausbonusta voi saada jopa 5 senttiä/litra" [G6].
  - **Our reading:** the cents per litre equal the Bonus percent (3 % → 3 c/l, 5 % → 5 c/l). Only the 3 % case and the 5 c/l maximum are published; the other levels are open question 2.
- **Household.** "A co-op member household consists of persons whose purchases contribute to the household's joint Bonus accumulation". Bonus "is paid to the main member" [G4].
- **Payment.** "Bonus is paid to your S-Pankki account on the 10th of each month" [G5]. The rules say "benefits payable in cash can only be paid to an account at S-Bank" [G4].
- **Partners and abroad.** Bonus also accumulates at "S Group's current national and local Bonus partners" and "in separately specified S Group outlets abroad" [G4]. Partner rates: **unknown** (out of scope here).

## 3. The payment benefit (maksutapaetu)

- **What it is.** The rules: "The payment method benefit is a co-op member benefit of 0.5% granted on the total amount of purchases covered by the payment method benefit and paid for with an S-Etukortti Visa or S-Etukortti Debit card at S Group's Finnish outlets" [G4].
- **On top of Bonus.** S-Pankki: "saat Bonuksen lisäksi 0,5 % maksutapaetua", "yhteensä jopa 5,5 %" [G7].
- **Where.** "Voit kerryttää etua S-ryhmän Suomen toimipaikoissa ja verkkokaupoissa" [G7].
- **Which payments.** "Maksutapaetua kertyy sekä debit- että credit-puolen maksuista", and "Koko talouden S-Etukortti Visalla tekemät ostot kerryttävät maksutapaetua" [G7].
- **Base amount.** "Maksutapaetu lasketaan pääsääntöisesti koko oston loppusummasta" [G8].
- **Exclusions** (rules section 3.3.3 [G4]):
  - "The payment method benefit does not accumulate on withdrawals, deposits or debt repayments";
  - "Most commission-based products, such as gambling and lottery products, are not subject to the payment method benefit";
  - "No payment method benefit accumulates on purchases of tobacco products, tobacco substitutes, smoking equipment, imitation tobacco products, e-cigarettes, nicotine liquids and nicotine preparations, beverages containing more than 1.2% by volume" of ethyl alcohol;
  - at car dealerships it "accumulates on maintenance, spare parts and accessories, but not on car purchases" (also "Auton ostamisesta ei anneta maksutapaetua" [G8]).

  So, like Bonus, it does not cover tobacco, alcohol or most lottery products.
- **Payment.** It is paid "to the payment account of the main member of the co-op member household at S-Bank by the tenth day of the month following the month of accumulation" [G4].

## 4. How the coach can estimate S-Bonus: a what-if only
This section gives deterministic formulas for #5's `bonus_estimate`. The result is a what-if estimate (R13): it does not say where the customer shops, and it names no store. The card shows the assumptions next to the number.

**Inputs.**
- `G` = the customer's own spending in the category Groceries in a month. #6 metrics, for example the month average over the last 6 complete months.
- `s` = the what-if share of that spending that would go to S-Group grocery stores. The default is 100 %; it is a scenario, not the customer's behaviour.

**Formula.**
1. `level_base = s × G`.
   - Only purchase kinds that count towards the level enter it (section 5).
   - In v1 that is groceries only; fuel would also count if a future scenario included it.
2. `bonus_percent` is the highest row of the default table with `min_monthly_purchases_eur ≤ level_base`, and 0 below its lowest row (our reading, section 2).
3. `bonus = bonus_percent × s × G`. Kinds with `earns_percent_bonus: false` (fuel, bars) are never in this base.
4. `payment_benefit = 0.5 % × s × G`, assuming payment with an S-Etukortti Visa.
5. The coach states:
   - the level reached;
   - both amounts, labelled *estimate*;
   - these assumptions: this customer is the whole co-op household; the default Bonus table (not KPO or Koillismaa); paid with an S-Etukortti Visa; no excluded goods (alcohol, tobacco, lottery); `s` is a what-if share.

**Sentence template** (`{{…}}` are number tokens):

> If {{share}} of your grocery spending ({{G}} a month) went to S-Group stores, the Bonus would be about {{bonus}} a month at the {{level}} level, plus about {{payment_benefit}} payment benefit with an S-Etukortti Visa. This is an estimate: it assumes you are the only shopper in your co-op household, you pay with an S-Etukortti Visa and none of it is alcohol, tobacco or lottery.

**Worked examples (illustrative numbers, default table, S-Etukortti Visa, no excluded goods).**

| Grocery spending `G` | What-if share `s` | Level base | Level | Bonus / month | Payment benefit / month |
|---|---|---|---|---|---|
| 400 € | 100 % | 400 € | 2.5 % | 10.00 € | 2.00 € |
| 400 € | 50 % | 200 € | 1.5 % | 3.00 € | 1.00 € |
| 750 € | 100 % | 750 € | 4.0 % | 30.00 € | 3.75 € |

**The effect of 100 € more at S-Group.** This depends on where the household starts, because a level jump also raises the Bonus on what it already spends. Each row assumes that the household already spends the starting amount a month at S-Group, pays with an S-Etukortti Visa and buys no excluded goods:

| Already at S-Group / month | Then | Bonus on the extra 100 € | Level jump on the existing spending | Payment benefit on the 100 € | Total gain |
|---|---|---|---|---|---|
| 150 € (1.0 %) | 250 € (1.5 %) | 1.50 € | 0.75 € | 0.50 € | 2.75 € |
| 450 € (2.5 %) | 550 € (3.0 %) | 3.00 € | 2.25 € | 0.50 € | 5.75 € |
| 650 € (3.5 %) | 750 € (4.0 %) | 4.00 € | 3.25 € | 0.50 € | 7.75 € |

From 650 €, the gain is 7.75 € on 100 €, which is more than S-Pankki's own headline of "jopa 5,5 %" (up to 5.5 %) [G7]. That is because 3.25 € of it is the level jump: 0.5 % more on the 650 € already spent. The coach must show the breakdown, not just the 7.75 €.

**What the estimate cannot see in our data.**
- Item-level exclusions (alcohol, tobacco, lottery): the estimate overstates both the Bonus and the payment benefit.
- Other household members' purchases: the estimate understates the level.
- Bonus partners: not counted.
- The card product and the cooperative's table: assumed.

## 5. Which kinds of purchases the scale would apply to (MCC mapping)
Our dataset has 36 MCC codes; this count is from the 99-customer sample, `customer_id < 'CUST00100'`. The mapping below is **our reading** of which kinds of purchases correspond to S-Group business types (section 1). **An MCC never makes a merchant an S-Group store, and no merchant is treated as one.** v1 uses only the grocery row, through the category Groceries (section 4).

| MCC | Category in our data | Business type | Counts towards the level | Earns percentage Bonus |
|---|---|---|---|---|
| 5411 | Groceries | Grocery (S-Group examples: Prisma, S-market, Sale, Alepa) | yes | yes |
| 5499 | Groceries | Grocery (smaller food stores) | yes | yes |
| 5541 | Transportation | Fuel and service stations (ABC) | yes | no: Refuelling Bonus |
| 5542 | Transportation | Unstaffed fuel stations (ABC) | yes | no: Refuelling Bonus |
| 5812 | Restaurants | Restaurants | yes | yes (alcohol excluded; not visible in our data) |
| 5814 | Restaurants | Fast food and cafés | yes | yes |
| 5813 | Restaurants | Bars | no (**assumption**: mostly alcohol, which is not a Bonus purchase) | no (**assumption**) |
| 7011 | Travel | Hotels (S-Group examples: Sokos Hotels, Radisson) | yes | yes |

All other MCCs in the data are kinds the scale is not applied to. These include specialty food 5422/5451, pharmacy and health 5912/8011/8021/8099, parking 7523, and taxi and public transport 4121/4111. Department stores (5311) and cosmetics (5977) would map to Sokos and Emotion, but these codes are not in our data.

Health MCCs are never part of a Bonus estimate, which also keeps them out of Bonus prompts (R9).

## 6. Assumptions behind every estimate

> **Assumptions, for the demo.** They are shown next to the number.
> - No merchant in the dataset is treated as an S-Group store. `is_s_group` is `null` for every merchant until the bank confirms the mapping.
> - The estimate uses the customer's own spending and a what-if share `s`.
> - Payment with an S-Etukortti Visa (for the payment benefit).
> - One customer in our data is the whole co-op member household.
> - The default Bonus table applies (not KPO or Koillismaa).
> - No excluded goods in the base.

The YAML holds them under `what_if_assumptions`, labelled `is_assumption: true`.

## 7. Open questions for the S-Pankki mentors
1. For purchases between two table rows, is the level the highest row at or below the month's total, for example 650 € → 3.5 %? Is there any Bonus below the lowest row (50 € in the default table)?
2. The Bonus page's example is 3 % Bonus → 3 cents per litre. Is the Refuelling Bonus always the same number of cents as the Bonus percent, including the half levels (1.5 %, 2.5 %, …)?
3. Does Bonus accrue on the food part of a restaurant bill when the same bill includes alcohol?
4. In S-Pankki's own data, which fields identify an S-Group outlet (merchant id, chain, cooperative) and the card product (S-Etukortti Visa or Debit)? This would let the coach use real S-Group spending instead of a what-if share.
5. Can the coach show a household's Bonus level and accrued Bonus from S-Group data, or only estimate them from S-Pankki transactions?
6. Which partners count as Bonus partners, at what rates, and are they visible in transaction data?
7. Is it acceptable for the coach to show a what-if Bonus estimate, *if this share of your grocery spending went to S-Group stores …*, or does that count as marketing that needs separate approval?

## Sources
All accessed on 2026-11-13.
- [G1] S Group, "Business operations". https://s-ryhma.fi/en/about-us/business-operations, accessed 2026-11-13.
- [G2] S-Etukortti, "Bonus tables". https://s-etukortti.fi/en/bonus/bonus-tables, accessed 2026-11-13.
- [G3] S-Etukortti, "Bonustaulukot". https://s-etukortti.fi/bonus/bonustaulukot, accessed 2026-11-13.
- [G4] S-Etukortti, "Rules of the co-op membership system", valid as of 10 July 2026. https://s-etukortti.fi/en/rules-of-the-co-op-membership-system, accessed 2026-11-13.
- [G5] S-Etukortti, "Bonus". https://s-etukortti.fi/en/bonus, accessed 2026-11-13.
- [G6] ABC, "Polttoaineet". https://www.abcasemat.fi/polttoaineet, accessed 2026-11-13.
- [G7] S-Pankki, "Bonus ja maksutapaetu hyötykäyttöön". https://www.s-pankki.fi/fi/kortit/maksutapaetu/, accessed 2026-11-13.
- [G8] S-Pankki FAQ, "Miten saan maksutapaetua?". https://www.s-pankki.fi/fi/asiakaspalvelu/ukk/kysymykset/kortit/miten-saan-maksutapaetua/, accessed 2026-11-13.
