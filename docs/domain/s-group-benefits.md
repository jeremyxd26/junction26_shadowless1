# S-Group stores, S-Bonus and the payment benefit

Issue #4. Official public sources only: s-etukortti.fi, s-ryhma.fi, s-pankki.fi and abcasemat.fi. Every rule cites a numbered source in [Sources](#sources), each with its URL and access date. Where no official page says something, this document says **unknown**. Our own readings and demo choices are labelled **our reading** or **assumption**.

The machine-readable version is [`core/config/s_group_benefits.yaml`](../../core/config/s_group_benefits.yaml). It is what the agent core (#5) needs for `is_s_group` and `bonus_estimate` in the store tools.

## Summary for the coach
- **Bonus** is a monthly percentage of the household's purchases at S-Group, from 1% to 5% [G2, G5]. The level comes from the month's total Bonus purchases, and the percentage applies to all purchases other than fuel [G4].
- **Fuel** at ABC earns no percentage Bonus. It earns a Refuelling Bonus of up to 5 cents per litre instead [G4, G6], and it still counts towards the monthly level: "fuel purchases still count towards your monthly Bonus purchases" [G5].
- **The payment benefit** (maksutapaetu) is a further 0.5% when paying with an S-Etukortti Visa or S-Etukortti Debit card at S-Group's Finnish outlets [G4, G7]. Together with Bonus that is "jopa 5,5 %" [G7].
- Both are paid as money to the household's S-Pankki account by the 10th of the following month [G4, G5, G7].
- **Our dataset does not say which merchants belong to S-Group.** Section 6 defines a labelled demo assumption for that.

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

**Bonus table.** This table "applies in all cooperatives except Osuuskauppa KPO and Koillismaan Osuuskauppa" [G2]. The Finnish page shows the same rows under "Talouden ostot / kk", "Bonusprosentti" and "Bonus kuukaudessa" [G3].

| Household purchases / month | Bonus percent | Bonus / month |
|---|---|---|
| 900 € | 5.0 % | 45.00 € |
| 800 € | 4.5 % | 36.00 € |
| 700 € | 4.0 % | 28.00 € |
| 600 € | 3.5 % | 21.00 € |
| 500 € | 3.0 % | 15.00 € |
| 400 € | 2.5 % | 10.00 € |
| 300 € | 2.0 % | 6.00 € |
| 200 € | 1.5 % | 3.00 € |
| 50 € | 1.0 % | 0.50 € |

- **KPO** has its own table with the same rows, except that the lowest row is 1 € at 1.0 % [G2]. The rows of the **Koillismaan Osuuskauppa** table are not shown on the page: **unknown**.
- **How the level is set.** "Purchases made by the co-op member household during the calendar month that accumulate Bonus and Refuelling Bonus are added together. The amount of Bonus purchases determines the level of the Bonus table according to which Bonus is paid as a percentage of purchases other than fuel purchases" [G4]. The table's own numbers confirm that the percentage applies to the whole month's purchases, not only the part above a threshold: 900 € × 5 % = 45 € [G2].
- **Purchases between two rows.** **Our reading:** a household gets the highest row whose amount is not above its monthly purchases, so 650 € gives 3.5 %. Below 50 € there is no Bonus. The pages do not say this in words: **unknown**, and on the list of open questions.
- **Which purchases count.** "Bonus accumulates only on the private purchases of the co-op member household" [G4]. The rules exclude [G4]:
  - "tobacco products, tobacco substitutes, smoking equipment, imitation tobacco products, e-cigarettes, nicotine liquids and nicotine preparations";
  - "beverages containing more than 1.2% by volume of ethyl alcohol and food products containing more than 2.8% by volume of ethyl alcohol";
  - "Most commission-based products, such as gambling and lottery products";
  - the buyer's purchases of S Group gift cards;
  - tax-free purchases;
  - purchases with a corporate card.
- **Fuel and charging.** "Fuel purchased at ABC service stations and ABC unmanned stations does not accumulate Bonus. Fuel purchases accumulate Refuelling Bonus ... Other ABC purchases accumulate Bonus." Also, "Charging electric cars at ABC charging points accumulates Bonus" [G4]. Fuel still raises the level: "fuel purchases still count towards your monthly Bonus purchases" [G5].
- **Refuelling Bonus.** It is "paid in cents per litre for fuel purchases" at the household's monthly level [G4]. ABC says "Tankkausbonusta voi saada jopa 5 senttiä/litra" [G6]. The cents per litre at each level below the top: **unknown**, not published on the pages we opened.
- **Household.** "A co-op member household consists of persons whose purchases contribute to the household's joint Bonus accumulation". Bonus "is paid to the main member" [G4].
- **Payment.** "Bonus is paid to your S-Pankki account on the 10th of each month" [G5]. The rules say "benefits payable in cash can only be paid to an account at S-Bank" [G4].
- **Partners and abroad.** Bonus also accumulates at "S Group's current national and local Bonus partners" and "in separately specified S Group outlets abroad" [G4]. Partner rates: **unknown** (out of scope here).

## 3. The payment benefit (maksutapaetu)

- **What it is.** The rules: "The payment method benefit is a co-op member benefit of 0.5% granted on the total amount of purchases covered by the payment method benefit and paid for with an S-Etukortti Visa or S-Etukortti Debit card at S Group's Finnish outlets" [G4].
- **On top of Bonus.** S-Pankki: "saat Bonuksen lisäksi 0,5 % maksutapaetua", "yhteensä jopa 5,5 %" [G7].
- **Where.** "Voit kerryttää etua S-ryhmän Suomen toimipaikoissa ja verkkokaupoissa" [G7].
- **Which payments.** "Maksutapaetua kertyy sekä debit- että credit-puolen maksuista", and "Koko talouden S-Etukortti Visalla tekemät ostot kerryttävät maksutapaetua" [G7].
- **Base amount.** "Maksutapaetu lasketaan pääsääntöisesti koko oston loppusummasta" [G8].
  - **Our reading:** unlike Bonus, it is calculated on the receipt total. Whether it also covers items excluded from Bonus, such as alcohol: **unknown**, and on the list of open questions.
- **Exclusion.** "Auton ostamisesta ei anneta maksutapaetua" [G8].
- **Payment.** It is paid "to the payment account of the main member of the co-op member household at S-Bank by the tenth day of the month following the month of accumulation" [G4].

## 4. How the coach can estimate S-Bonus (proposal)
These are deterministic formulas for #5 and #6. They are estimates (rule R13 in `docs/design/research-bank-assistants.md`), and each card shows its method.

1. **Monthly level.** `level_base` is the household's S-Group purchases in the calendar month, including fuel.
   - `bonus_percent` is taken from the table: the highest row with `min_monthly_purchases_eur ≤ level_base`; 0 below the lowest row.
2. **Bonus.** `bonus = bonus_percent × (S-Group purchases in the month excluding fuel)`.
3. **Refuelling Bonus.** Not estimated, because the cents per litre per level are unknown and our data has no litres. The coach says that fuel earns a separate Refuelling Bonus of up to 5 cents per litre [G6].
4. **Payment benefit.** `payment_benefit = 0.5 % × S-Group card purchases in the month`, assuming the card is an S-Etukortti Visa (section 6).
5. ***What if I had bought this at S-Group?*** Recompute steps 1, 2 and 4 with the purchase moved to S-Group. The difference is the bonus the user would have gained: the purchase's own bonus, plus any level jump on the whole month.

**Worked example (illustrative numbers).**

| Scenario | S-Group purchases | Level | Bonus | Payment benefit |
|---|---|---|---|---|
| A household's month | 650 € (no fuel) | 3.5 % | 22.75 € | 3.25 € |
| The same month, with a 100 € grocery shop moved from a non-S-Group store | 750 € | 4.0 % | 30.00 € | 3.75 € |

Moving the shop would have earned 7.25 € more Bonus and 0.50 € more payment benefit. In the app this is *about 7.75 €*, shown as an estimate.

**What the estimate cannot see in our data.** For each limit, the estimate is too high or too low as stated, and the card's method text says so.
- Item-level exclusions such as alcohol, tobacco and lottery: the estimate overstates Bonus.
- Other household members' purchases: the estimate understates the level.
- Bonus partners: not counted.
- The card product: assumed.

## 5. MCC mapping
Our dataset has 36 MCC codes; this count is from the 99-customer sample, `customer_id < 'CUST00100'`. The mapping below is **our reading** of which codes correspond to S-Group-type businesses (section 1). An MCC alone never proves that a merchant belongs to S-Group.

| MCC | Category in our data | S-Group business type | Earns percentage Bonus |
|---|---|---|---|
| 5411 | Groceries | Grocery (Prisma, S-market, Sale, Alepa) | yes |
| 5499 | Groceries | Grocery (smaller food stores) | yes |
| 5541 | Transportation | Fuel and service stations (ABC) | no: Refuelling Bonus; counts towards the level |
| 5542 | Transportation | Unstaffed fuel stations (ABC) | no: Refuelling Bonus; counts towards the level |
| 5812 | Restaurants | Restaurants | yes (alcohol excluded; not visible in our data) |
| 5814 | Restaurants | Fast food and cafés | yes |
| 5813 | Restaurants | Bars | treated as no: mostly alcohol, which earns no Bonus (**assumption**) |
| 7011 | Travel | Hotels (Sokos Hotels, Radisson) | yes |

All other MCCs in the data are mapped to `not S-Group`. These include specialty food 5422/5451, pharmacy and health 5912/8011/8021/8099, parking 7523, and taxi and public transport 4121/4111. Department stores (5311) and cosmetics (5977) would map to Sokos and Emotion, but these codes are not in our data.

Health MCCs are never mapped to S-Group here, which also keeps them out of Bonus prompts (R9).

## 6. Demo assumption: which merchants are S-Group

> **Assumption, for the demo only.** Merchants in the dataset are anonymised (`MRC-GRO-0035`), so the data does not say which merchants belong to S-Group. In production the bank knows its own merchants.

- A merchant counts as S-Group if its MCC is one of the S-Group codes in section 5 **and** `int(sha256(merchant_id)[:8], 16) / 2^32 < 0.5`. This is a deterministic coin flip that marks about half of those merchants.
- The share 0.5 is a demo parameter, **not** S-Group's market share.
- All other merchants are not S-Group. A transaction without a merchant gets `is_s_group = null`.
- Every card purchase at an S-Group merchant is assumed to be paid with an S-Etukortti Visa, so it earns the payment benefit.
- One customer in our data is one co-op member household, and the default Bonus table applies (not KPO or Koillismaa).

The same assumption, with these parameters, is in the YAML under `demo_assumption`. It is labelled `is_assumption: true`.

## 7. Open questions for the S-Pankki mentors
1. For purchases between two table rows, is the level the highest row at or below the month's total, for example 650 € → 3.5 %? Is there any Bonus below 50 €?
2. How many cents per litre does the Refuelling Bonus pay at each Bonus level?
3. Is the payment benefit (0.5 %) calculated on items that earn no Bonus, such as alcohol, tobacco and lottery, given that it is "pääsääntöisesti koko oston loppusummasta"?
4. Does Bonus accrue on the food part of a restaurant bill when the same bill includes alcohol?
5. In S-Pankki's own data, which fields identify an S-Group outlet (merchant id, chain, cooperative) and the card product (S-Etukortti Visa or Debit)? This would replace the demo assumption.
6. Can the coach show a household's Bonus level and accrued Bonus from S-Group data, or only estimate them from S-Pankki transactions?
7. Which partners count as Bonus partners, at what rates, and are they visible in transaction data?
8. Is it acceptable for the coach to say *at S-Group this would have earned about X € Bonus* as an estimate, or does that count as marketing that needs separate approval?

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
