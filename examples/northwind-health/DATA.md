# Synthetic Payer-Contract + Claims Demo Data

Newly generated, fully synthetic healthcare revenue-cycle dataset for the
contract-intelligence Databricks demo. Nothing here is real PHI: payer names are
real organizations used only for realism, but every rate, date, member ID, NPI,
claim, and dollar figure is fabricated by the generators in this folder.

The provider org in the data is a fictional **Northwind Health**.

---

## What's in here

```
examples/northwind-health/
├── demo_config.py              # SINGLE SOURCE OF TRUTH: payers, DRGs, CPTs, rates,
│                               #   seeded-finding parameters, denial-code reference
├── generate_contracts.py       # -> contracts/*.pdf   (8 agreements + 2 amendments)
├── generate_contract_terms.py  # -> data/contract_terms.parquet  (ground-truth clauses)
├── generate_claims.py          # -> data/claims.parquet  (30,000 X12 837/835 rows)
├── metric_views.sql            # UC views + a metric view (paramized {catalog}.{schema})
├── load_to_uc.py               # Databricks notebook-style loader (run later)
├── requirements.txt
├── README.md
├── contracts/                  # 10 contract/amendment PDFs
└── data/
    ├── contract_terms.parquet  (+ .csv)
    ├── claims.parquet
    └── claims_sample.csv        (1,000-row preview)
```

### The three datasets line up on purpose
* **Contract PDFs** — multi-page managed-care agreements with a fee-schedule
  table by DRG + a CPT fee schedule, timely-filing / appeal windows, prior-auth
  rules, carve-outs, and renewal terms. Two amendments change a rate (UHC DRG
  329) and a timely-filing window (Cigna 90 -> 120 days).
* **`contract_terms`** — the normalized clause table that an `ai_extract` over
  those PDFs would produce. This is the **ground truth** the claims compare against.
* **`claims`** — 30,000 claim rows modeling the 837 (billed) + 835 (remit) flow,
  spanning **2024-01-01 to 2025-05-31 (~17 months)**. Every claim joins to
  `contract_terms` (100% coverage): inpatient on `(payer_name, drg_code)`,
  outpatient on `(payer_name, cpt_code)`, so `paid_amount` vs `contracted_rate`
  computes exactly.

### Payers (8)
UnitedHealthcare, Aetna, Anthem Blue Cross Blue Shield, Cigna, Humana,
Medicare Advantage (Wellcare), Sagebrush Regional Health Plan (regional),
Pioneer Valley Medicaid MCO. Reimbursement methodologies vary across payers
(% of Medicare, per-DRG case rate, hybrid, Medicaid fee schedule) so
cross-contract comparison is interesting.

---

## How to regenerate

Two Python toolchains are used because `reportlab` and the data libraries were
available in different interpreters on the build machine. Any single env with
all of `requirements.txt` works too.

```bash
# data tables (pandas / pyarrow / faker)
python generate_contract_terms.py      # writes data/contract_terms.parquet (+csv)
python generate_claims.py              # writes data/claims.parquet (+ sample csv)

# contract PDFs (reportlab)
python generate_contracts.py           # writes contracts/*.pdf
```

The generators are deterministic (seeded), so re-running reproduces identical
output. Change any number in `demo_config.py` and every downstream artifact
stays consistent on the next run.

Load into Unity Catalog later (needs workspace auth):
```bash
# as a Databricks notebook, or via Databricks Connect
DEMO_CATALOG=northwind DEMO_SCHEMA=contract_intelligence python load_to_uc.py
```

---

## DEMO STORY — seeded findings and the questions that surface them

The data is engineered so a Genie / AI/BI / SQL demo lands four specific
"aha" moments. The numbers below are the actual values in this build.

### 1. Revenue leakage: UnitedHealthcare underpaid DRG 470 last quarter
UHC systematically paid **~11.5% below the contracted case rate on DRG 470
(major hip/knee replacement) across 2024-Q2** — about **$127,800** of
under-collection on 66 claims, while every other quarter collects ~99-100% of
contracted. This is the headline leakage line in
`underpayment_dollars_by_payer_drg`.

> *"Which payers underpaid us last quarter versus our contracted rates?"*
> *"Show UnitedHealthcare's contracted rate for DRG 470 versus what we actually collected, by quarter."*
> *"What's our total revenue leakage by payer and DRG?"*

(A smaller secondary leakage — Anthem on DRG 247 in 2024-Q3, ~7% — is present
so the comparison shows more than one offender.)

### 2. Timely-filing denial cluster: Cigna, 2024-Q3
Cigna timely-filing denials (**CARC 29**) spike in **2024-Q3 (135 of 139
total)** versus a handful in any other quarter. Ties to Cigna's tight 90-day
filing window — and Amendment A-2 later extends it to 120 days.

> *"What's our denial rate by payer, and which denials are timely-filing (CARC 29)?"*
> *"Show Cigna's timely-filing denials by quarter — when did they spike?"*
> *"Which payer has the shortest timely-filing window, and did it cause denials?"*

### 3. Prior-authorization denials: Humana
Humana has elevated prior-auth denials (**CARC 197**, 333 claims) concentrated
on prior-auth-required procedures (MRI brain 70553, total knee 27447, left heart
cath 93452, knee scope 29881). Humana's overall denial rate (**19.2%**) is the
highest of any payer.

> *"Which payer has the most prior-authorization denials (CARC 197), and on what procedures?"*
> *"What share of Humana's outpatient claims deny for missing prior auth?"*

### 4. Denial rate varies by payer (overall ~11.3%)
| Payer | Claims | Denial rate |
|---|---|---|
| Humana | 3,013 | 19.2% |
| Pioneer Valley Medicaid MCO | 875 | 15.4% |
| Cigna | 3,591 | 13.2% |
| Medicare Advantage (Wellcare) | 3,025 | 12.2% |
| Sagebrush Regional Health Plan | 1,160 | 12.0% |
| Anthem BCBS | 4,997 | 11.7% |
| UnitedHealthcare | 7,867 | 8.9% |
| Aetna | 5,472 | 7.8% |

> *"What's our overall denial rate, and how does it break down by payer?"*
> *"Rank payers by denial rate and show the dollar value of denied claims."*

### Contract-comparison questions (PDF / contract_terms side)
> *"Compare timely-filing and appeal windows across all our payer contracts."*
> *"Which contracts are up for renewal in the next 6 months?"*
> *"What did Amendment A-1 change about the UnitedHealthcare fee schedule?"*
> *"Which payers require prior authorization for advanced imaging?"*

---

## Key tables / views (after `load_to_uc.py`)

* `claims`, `contract_terms` — base Delta tables
* `claims_contract_enriched` — claims joined to contracted rates
* `reimbursement_variance` — paid vs contracted, `$` and `%`, by payer/quarter/code
* `denial_rate_by_payer` — denial counts/rate + CARC-29 and CARC-197 breakouts
* `underpayment_dollars_by_payer_drg` — the revenue-leakage view (finding #1)
* `revenue_cycle_metrics` — Unity Catalog metric view (governed semantics)

## Field reference (claims)
`claim_id, payer_name, plan_type, member_id, patient_id, provider_npi, facility,
service_date, submit_date (837), service_quarter, claim_type, drg_code,
drg_description, cpt_code, cpt_description, place_of_service, billed_amount (837),
contracted_rate, allowed_amount (835), paid_amount (835), patient_responsibility,
adjustment_amount, denial_code (CARC), remark_code (RARC), denial_reason,
claim_status (paid/partial/denied), paid_date (835), check_eft_number`
