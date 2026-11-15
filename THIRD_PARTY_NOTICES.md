# Third-party notices

Sentti's own code, texts and drawings are under the MIT licence in [`LICENSE`](LICENSE), copyright (c) 2026 team shadowless1. This file lists what comes from others, where it is used and under which terms. Partner data and partner APIs stay under their owners' terms; the MIT licence does not cover them.

## 1. Code and assets in this repository

| What | Where | Licence |
|---|---|---|
| Lucide icon paths: house, wrench, coffee | `app/src/components/BasketIcons.tsx` | ISC License, full text in [section 6](#6-isc-license-lucide). Portions from Feather (MIT). |
| Figtree typeface, weights 400 to 700 | not committed; installed from npm `@fontsource/figtree` 5.3.0 and bundled into the built app | SIL Open Font License 1.1. The licence text ships inside the package. |

Everything else is our own work under MIT: the Sentti cat mascot, the other line icons and chevrons, the four synthetic sample bills in `core/bills/samples/` (invented payees and details) and the screenshots in `app/docs/screenshots/`. The repository holds no S-Bank or S-Group logo, pictogram, typeface or image.

## 2. Software dependencies (installed by the package managers, not committed)

**The app's runtime bundle** (`app/package-lock.json`): `react` 19.3.1, `react-dom` 19.3.1 and `scheduler` 0.28.0 (MIT); `@fontsource/figtree` 5.3.0 (OFL-1.1).

**The app's build and test tools** (234 packages, not shipped to users): 180 MIT, 17 Apache-2.0, 12 MPL-2.0 (`lightningcss`, used by Tailwind CSS at build time), 10 ISC, 6 BSD-2-Clause, 4 BlueOak-1.0.0, 2 0BSD, 2 BSD-3-Clause, 1 CC-BY-4.0 (`caniuse-lite`, browser support data). Counted from the `license` fields of `app/package-lock.json`.

**The core service** (`core/requirements.txt`, Python 3.11, every version pinned), licences from the installed packages' metadata:

| Licence | Packages |
|---|---|
| MIT | fastapi, pydantic, pydantic_core, pydantic-settings, PyYAML, pytest, annotated-doc, annotated-types, anyio, charset-normalizer, h11, iniconfig, pluggy, truststore, typing-inspection, urllib3 |
| MIT-0 | cffi |
| BSD-2-Clause / BSD-3-Clause / BSD | uvicorn, starlette, httpx2, httpcore2, click, idna, pyasn1, pyasn1_modules, pycparser, Pygments, python-dotenv, websockets, colorama (Windows only) |
| Apache-2.0 | google-genai, google-auth, opentelemetry-api, requests, tenacity, distro, tzdata |
| Dual | cryptography (Apache-2.0 OR BSD-3-Clause), packaging (Apache-2.0 OR BSD-2-Clause), sniffio (MIT OR Apache-2.0) |
| PSF-2.0 | typing_extensions |
| MPL-2.0 | certifi (the CA bundle, used unmodified) |
| LGPL-3.0-only | psycopg, psycopg-binary, psycopg-pool (the PostgreSQL driver, installed unmodified as a separate library; we ship no modified copy) |

Development tool (`requirements-dev.txt`): ruff (MIT).

## 3. Data

### The S-Pankki synthetic dataset (Junction 2026)
- Published by S-Pankki for the Junction 2026 challenge "Personal Economic Trainer": <https://github.com/hackjunction/Junction-2026-S-pankki>. The customers and transactions are synthetic; there is no real person's data.
- **The dataset is not in this repository and is not under MIT.** It is used under the challenge's terms. The repository holds the code that loads it, the ids of four demo personas, and derived aggregates (the eval set's expected values, test fixtures, a few figures in the Learn texts), each labelled as coming from the synthetic dataset.

### Statistics Finland
- **Source: Statistics Finland (Tilastokeskus)**, open data under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) ([terms of use](https://stat.fi/en/about-us/get-to-know-statistics-finland/legislation/terms-of-use)).
- `core/config/national_context.yaml`: households' consumption by age of the reference person, table 14q4 (2022), with the query and the retrieval date. Shown in the app as "national context", never as a target.
- `app/src/components/learn/finlitLearn.json`: one sentence per age band in the Learn lessons, from tables 14q4 and 13iu, with the source line under it.
- `core/knowledge/finlit/facts.jsonl`: 489 figures from tables 14q4, 14q9, 12eb, 151s, 15j6, 158a, 15fc, 132d, 13iu, 12g9, 122p, 11vq, 11q7, 11hu and 13ud, each with the exact PxWeb query that re-fetches it.
- We changed nothing in the figures; age groups were mapped to the app's age bands as described in `core/knowledge/finlit/README.md`.

### The financial-literacy corpus (`core/knowledge/finlit/`)
- 231 sources. Each has a "source card": our own templated description (name, publisher, type, ages, topics, link). A card holds no text copied from the source.
- Text is stored only from sources whose licence allows reuse with attribution, split into sections. There are four, with these attributions, as stored with every chunk:
  - *Cost of living in Finland (InfoFinland) / Hintataso Suomessa.* InfoFinland.fi (© KEHA Centre). <https://infofinland.fi/en/settling-in-finland/cost-of-living-in-finland>. Licence: CC BY 4.0, <https://creativecommons.org/licenses/by/4.0/>. Text split into sections.
  - *Financial problems (InfoFinland) / Taloudelliset ongelmat.* InfoFinland.fi (© KEHA Centre; content reviewed with authorities). <https://infofinland.fi/en/settling-in-finland/cost-of-living-in-finland/financial-problems>. Licence: CC BY 4.0, <https://creativecommons.org/licenses/by/4.0/>. Text split into sections.
  - *Edunvalvonta, edunvalvontavaltuutus ja edunvalvontavaltakirja – opas edunvalvonnasta (Suomi.fi).* Digi- ja väestötietovirasto (DVV) on Suomi.fi; text written with EKL, FINE, Muistiliitto, Vanhustyön keskusliitto, Kehitysvammaliitto, Omaishoitajaliitto and others. <https://www.suomi.fi/oppaat/edunvalvonta>. Licence: CC BY 4.0, <https://creativecommons.org/licenses/by/4.0/>. Text split into sections.
  - *Kesätyöntekijän veroasiat (Vero.fi).* Verohallinto (Finnish Tax Administration). <https://vero.fi/henkiloasiakkaat/verokortti-ja-veroilmoitus/verokortti/palkansaaja/kesatyot/>. Licence: free reuse under the publisher's terms, <https://www.vero.fi/tietoa-verohallinnosta/yhteystiedot-ja-asiointi/asioi-verkossa/vero.fi-sisaltokuvaus-ja-sisaltojen-hyodyntaminen>. Text split into sections. Use of this text implies no endorsement by Verohallinto.
- Figures come only from the Statistics Finland tables above.
- When Sentti answers a money-literacy question from the corpus, it names the publisher and links the page under the answer ("Sources" / "Lähteet").
- Sources under share-alike, non-commercial, all-rights-reserved or unstated terms appear as cards and links only; to use one in a lesson we paraphrase and link.

The 40 sources whose licence class is `open_attribution` (from `sources.jsonl`; the verbatim licence text the verifier copied is in each record's `licence` field):

| Publisher | Source | Licence |
|---|---|---|
| Digi- ja väestötietovirasto (DVV) on Suomi.fi | [Suomi.fi guide to guardianship and continuing power of attorney](https://www.suomi.fi/oppaat/edunvalvonta) | [CC BY 4.0](https://www.suomi.fi/ohjeet-ja-tuki/yleista-suomifista/oppaat) |
| Eläketurvakeskus (Finnish Centre for Pensions) | [Average pension by 5-year age group](https://tilastot.etk.fi/pxweb/en/ETK/ETK__110kaikki_elakkeensaajat__20elakkeensaajien_elake/elsael_1k01_laji.px/) | [CC BY 4.0](https://www.etk.fi/en/research-statistics-and-projections/statistics/statistical-database/) |
| European Commission | [Flash Eurobarometer 525 financial literacy, Finland country tables](https://data.europa.eu/data/datasets/s2953_fl525_eng) | [European Commission reuse notice (Decision 2011/833/EU)](http://data.europa.eu/eli/dec/2011/833/oj) |
| Eurostat | [Eurostat Household Budget Survey tables by age of reference person (Finland included)](https://ec.europa.eu/eurostat/databrowser/product/page/HBS_EXP_T135) | [Eurostat copyright notice: reuse allowed with the source acknowledged (editorial content CC BY 4.0)](https://ec.europa.eu/eurostat/web/main/help/copyright-notice) |
| Helsingin yliopisto, Kriminologian ja oikeuspolitiikan instituutti (Krimo) | [Finnish National Crime Victim Survey 2025 – victimisation by purchase fraud, payment-instrument fraud, identity misuse and online crime by age](https://helda.helsinki.fi/server/api/core/bitstreams/4a978bac-3715-40a2-8661-fbc634bdaa65/content) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| InfoFinland.fi | [Cost of living in Finland](https://infofinland.fi/en/settling-in-finland/cost-of-living-in-finland) | [CC BY 4.0](https://infofinland.fi/en/open-data) |
| InfoFinland.fi | [Financial problems](https://infofinland.fi/en/settling-in-finland/cost-of-living-in-finland/financial-problems) | [CC BY 4.0](https://infofinland.fi/en/open-data) |
| Kansantaloudellinen yhdistys (KAK journal) | [Finnish adults' financial literacy 2023: national OECD/INFE survey (University of Vaasa + PTT, funded by the Ministry of Justice)](https://helda.helsinki.fi/server/api/core/bitstreams/14bd4ce6-12ee-46c4-afd3-a07b3a090863/content) | [CC BY 4.0](https://helda.helsinki.fi/server/api/core/bundles/c017770a-c6d6-4cfa-96f4-d2334f5c9334/item) |
| Kela (Kansaneläkelaitos) | [General housing allowance paid (Kela open data)](https://avoindata.suomi.fi/data/api/3/action/package_show?id=maksetut-yleiset-asumistuet1) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Kela (Kansaneläkelaitos) | [Pension recipients in Finland and average pensions (Kela open data)](https://avoindata.suomi.fi:443/data/fi/dataset/suomen-elakkeensaajat-ja-keskimaaraiset-elakkeet) | [CC BY 4.0](https://www.avoindata.fi/data/fi/dataset/suomen-elakkeensaajat-ja-keskimaaraiset-elakkeet) |
| Kela (Kansaneläkelaitos) | [Student financial aid recipients and payments (Kela open data)](https://avoindata.suomi.fi:443/data/fi/dataset/opintotuen-saajat-ja-maksetut-tuet) | [CC BY 4.0](https://www.avoindata.fi/data/fi/dataset/opintotuen-saajat-ja-maksetut-tuet) |
| Kela (open data CSV) | [Recipients of basic social assistance, by municipality and age group (Kela) + share of 18-24-year-olds receiving social assistance (THL Sotkanet 294)](https://avoindata.suomi.fi/data/fi/dataset/perustoimeentulotuen-saajat) | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) |
| Opiskelun ja koulutuksen tutkimussäätiö Otus & Suomen Ammattiin Opiskelevien Liitto SAKKI ry (funded via OKM and TEM) | [Vocational students' barometer 2019](https://services.fsd.tuni.fi/catalogue/FSD3484?tab=download&lang=fi&study_language=fi) | [CC BY 4.0 (FSD class A datasets)](https://services.fsd.tuni.fi/catalogue/FSD3484?tab=download&lang=fi&study_language=fi) |
| Pörssisäätiö | [Young investors: number of equity/fund investors by age 2015 vs 2025 (Pörssisäätiö, from Statistics Finland table StatFin/vtutk/15j6)](https://www.porssisaatio.fi/perehdy-tutkimuksiin/porssisaation-tilastot/nuoret-sijoittajina/) | [Data: Statistics Finland, CC BY 4.0 (the Pörssisäätiö page itself states no licence; only the Statistics Finland data is used)](https://stat.fi/en/about-us/get-to-know-statistics-finland/legislation/terms-of-use) |
| Suomen Pankki ja Finanssivalvonta | [Bank of Finland and FIN-FSA Open Data Service (Timeseries API v4)](https://www.suomenpankki.fi/en/statistics/open-data/) | [Free reuse with acknowledgement of the source (Open Data Service terms; no named licence)](https://www.suomenpankki.fi/en/bank-of-finland/contacts/open-data-service/) |
| THL, Sotkanet.fi | [Adult gambling indicators (THL population gambling survey and Healthy Finland survey)](https://sotkanet.fi/rest/1.1/indicators/3759) | [CC BY 4.0](https://sotkanet.fi/sotkanet/fi/ohje/296) |
| Terveyden ja hyvinvoinnin laitos (THL) | [School Health Promotion Study: weekly gambling and perceived family economic situation (Sotkanet indicators)](https://thl.fi/data-ja-tilastot/lapset-ja-nuoret/nuorten-hyvinvointi) | [CC BY 4.0](https://thl.fi/tutkimus/avoin-data) |
| Tilastokeskus (Statistics Finland) | [Assets, liabilities and income of households by age of reference person, 1987-2023](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/vtutk/151s.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Background information by age of reference person, 2012-2022](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/ktutk/14q9.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Consumer confidence by age group (incl. possibilities to save)](https://pxdata.stat.fi/PxWeb/pxweb/en/StatFin/StatFin__kbar/11vq.px/) | [CC BY 4.0](https://stat.fi/en/about-us/get-to-know-statistics-finland/legislation/terms-of-use) |
| Tilastokeskus (Statistics Finland) | [Consumer price index: annual change, CPI (2025=100) by commodity, CPI/HICP weights 2026](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/khi/122p.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Debtors in enforcement (Ulosottovelalliset) by age, gender and main type of activity](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/uloa/11q7.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Disposable monetary income by age of person and sex, 1995-2024](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/tjt/11py.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Household consumption expenditure by age of reference person, 2012-2022](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/ktutk/14q4.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Households' income by age of reference person, 1966-2024](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/tjt/12eb.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Indebted persons and debt indicators by age](https://pxdata.stat.fi/PxWeb/pxweb/en/StatFin/StatFin__velk/158a.px/) | [CC BY 4.0](https://stat.fi/en/about-us/get-to-know-statistics-finland/legislation/terms-of-use) |
| Tilastokeskus (Statistics Finland) | [Monthly earnings of full-time employees by sector, education, field, age group and sex, 2024 (Structure of Earnings)](https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/pra/15av.px) | [CC BY 4.0](https://www.stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Persons who applied for restructuring of debts (velkajärjestely)](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/velj/11hu.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Rents of dwellings: distributions of total rents (15fc) and rent index / EUR per m2 (15fa), 2025Q1-2026Q3](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/asvu/15fc.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland) | [Share of persons with housing loans / other debts / debt-free by age](https://pxdata.stat.fi/PxWeb/pxweb/en/StatFin/StatFin__velk/157z.px/) | [CC BY 4.0](https://stat.fi/en/about-us/get-to-know-statistics-finland/legislation/terms-of-use) |
| Tilastokeskus (Statistics Finland) | [Use of information and communications technology by individuals by gender and age group, 2013-2025](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/sutivi/13ud.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Asuntokunnat ja asuinolot | [Household-dwelling units by tenure, size and age of the oldest member, 2005-2025](https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/asku/15gp.px) | [CC BY 4.0](https://www.stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Income distribution statistics | [Households' housing costs and housing expenditure indicators](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/tjt/12g9.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Kokeelliset tilastot | [Inflation by age of household reference person (experimental statistics), quarterly, 2025=100](https://stat.fi/tup/kokeelliset-tilastot/vaestoryhmittainen-inflaatio-kuukausittain/2026-10-23/index.html) | [CC BY 4.0](https://www.stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Kokeelliset tilastot | [Inflation by household type and by housing tenure (experimental statistics), quarterly, 2025=100](https://pxdata.stat.fi/PXWeb/api/v1/fi/Kokeelliset_tilastot/vri/15g5.px) | [CC BY 4.0](https://www.stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Rikos- ja pakkokeinotilasto | [Complainants of offences reported to the police by age, sex and wellbeing services county, 2000-2025 (fraud, payment-instrument fraud)](https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/rpk/13jm.px) | [CC BY 4.0](https://www.stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Statistics on living conditions | [Households' ability to save money and to afford to pay for an unexpected expense by life-cycle](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/eot/132d.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Statistics on living conditions (EU-SILC) | [Prevalence of some dimensions of material deprivation by person's age](https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/eot/13iu.px) | [CC BY 4.0](https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Tilastokeskus (Statistics Finland), Tulonjakotilasto | [At-risk-of-poverty (low-income) rate and persistent low income by age and sex, 2010-2024; plus low-income thresholds by household type](https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/tjt/128j.px) | [CC BY 4.0](https://www.stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot) |
| Verohallinto (Finnish Tax Administration) | [Tax matters for summer workers (tax card)](https://vero.fi/henkiloasiakkaat/verokortti-ja-veroilmoitus/verokortti/palkansaaja/kesatyot/) | [Free reuse under the vero.fi content terms (no endorsement implied)](https://www.vero.fi/tietoa-verohallinnosta/yhteystiedot-ja-asiointi/asioi-verkossa/vero.fi-sisaltokuvaus-ja-sisaltojen-hyodyntaminen) |

### S-Bank help pages (`core/knowledge/sbank_faq.yaml`)
- Short answers about S-Bank and S-mobiili, **written in our own words** from S-Bank's public customer help pages on s-pankki.fi. Each entry has its source URL and retrieval date. No text is copied, and the fetched pages are not in the repository.
- An answer says what the help page says and points to the bank for anything more. Sentti never speaks as the bank and gives no product advice.

### S-Group benefits (`docs/domain/s-group-benefits.md`, `core/config/s_group_benefits.yaml`)
- Summarised from S-Group's public pages (s-etukortti.fi, s-ryhma.fi, s-pankki.fi, abcasemat.fi), with short quotes, each rule citing its source URL and access date.

### Trademarks
S-Pankki, S-Bank, S-mobiili, S-Group and S-Etukortti are trademarks of their owners. Sentti is a hackathon concept by team shadowless1 for the S-Pankki challenge at Junction 2026. It is not an S-Bank product and is not endorsed by S-Bank or S-Group.

## 4. AI models and cloud services (called at run time, not part of the repository)

| Service | What Sentti uses it for | Terms |
|---|---|---|
| Google Gemini API | Language models that plan tool calls and write answers from tool results, speech to text, text to speech, and text embeddings for the corpus search. They receive the tools' results, never raw transactions. | Google's Gemini API terms |
| NVIDIA Nemotron 3.5 Super VL (`nvidia/nemotron-3.5-super-vl-120b-a12b`) on Verda's inference endpoint | Reads the fields of the four synthetic sample bills; code checks the IBAN and reference check digits. | NVIDIA's model licence and Verda's terms |
| Aiven for PostgreSQL (with pgvector) | Stores the synthetic dataset, the metric tables and the corpus vectors. | Aiven's terms |
| Verda | The CPU instance in Finland that serves the dev environment. | Verda's terms |

Model outputs are checked by code before anyone sees them: every number in an answer must come from a tool's result.

## 5. Where this list comes from
- npm: the `license` field of every package in `app/package-lock.json`.
- Python: the installed metadata (`License-Expression`, `License` or the classifiers) of every pin in `core/requirements.txt` and `requirements-dev.txt`.
- Corpus: the `licence`, `licence_url` and `licence_class` fields of `core/knowledge/finlit/sources.jsonl`, set from the licence text copied from each publisher's site.

If you find something missing or wrong here, please open an issue.

## 6. ISC License (Lucide)

```
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT).
All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any purpose with or without
fee is hereby granted, provided that the above copyright notice and this permission notice appear
in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS
SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE
AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
OF THIS SOFTWARE.
```
