"""
demo_config.py
==============
Single source of truth shared by all generators in this package so that the
contract PDFs, the structured ``contract_terms`` table, and the ``claims``
dataset are mutually consistent.

Everything here is SYNTHETIC. The provider organization ("Northwind Health") is
fictional. Payer names are real organizations used only to make the demo feel
realistic; all rates, dates, member IDs, NPIs, and dollars are fabricated.

The seeded findings the demo is designed to surface live in this file:

  * UnitedHealthcare systematically underpays DRG 470 (~12% under contract)
    across Q2 of the contract year  -> revenue leakage.
  * Cigna has a timely-filing denial cluster (CARC 29) spiking in one quarter.
  * Humana has elevated prior-auth denials (CARC 197) on imaging / surgical CPTs.
  * Overall denial rate ~8-15%, varying by payer.

If you change a number here, every downstream artifact stays in sync the next
time you re-run the generators.
"""

from datetime import date

# --------------------------------------------------------------------------
# Provider / facility identity (the fictional health system in the demo)
# --------------------------------------------------------------------------
HEALTH_SYSTEM = "Northwind Health"
HEALTH_SYSTEM_TIN = "35-1899042"

FACILITIES = [
    {"facility": "Northwind Regional Medical Center", "npi": "1487654320", "pos": "21"},  # inpatient
    {"facility": "Northwind North Hospital",          "npi": "1598765431", "pos": "21"},
    {"facility": "Northwind Surgical & Specialty Ctr","npi": "1609876542", "pos": "22"},  # outpatient/HOPD
    {"facility": "Northwind Cardiology Associates",   "npi": "1710987653", "pos": "11"},  # office
    {"facility": "Northwind Imaging Center",          "npi": "1821098764", "pos": "11"},
]

# --------------------------------------------------------------------------
# The contract year the demo revolves around
# --------------------------------------------------------------------------
CONTRACT_YEAR_START = date(2024, 1, 1)
CONTRACT_YEAR_END = date(2024, 12, 31)
# Claims span a bit beyond the contract year so timely-filing math is interesting
CLAIMS_START = date(2024, 1, 1)
CLAIMS_END = date(2025, 5, 31)   # ~17 months

def quarter_of(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"

# --------------------------------------------------------------------------
# Medicare base rates used to derive "% of Medicare" payers (synthetic)
# --------------------------------------------------------------------------
DRGS = {
    "470": {"desc": "Major hip and knee joint replacement w/o MCC",          "medicare": 14250.0, "type": "IP"},
    "247": {"desc": "Percutaneous cardiovascular proc w/ drug-eluting stent","medicare": 18900.0, "type": "IP"},
    "291": {"desc": "Heart failure and shock w/ MCC",                          "medicare": 9200.0,  "type": "IP"},
    "871": {"desc": "Septicemia or severe sepsis w/o MV >96h w/ MCC",         "medicare": 13100.0, "type": "IP"},
    "190": {"desc": "Chronic obstructive pulmonary disease w/ MCC",           "medicare": 7400.0,  "type": "IP"},
    "194": {"desc": "Simple pneumonia and pleurisy w/ CC",                    "medicare": 6100.0,  "type": "IP"},
    "765": {"desc": "Cesarean section w/ CC/MCC",                              "medicare": 8300.0,  "type": "IP"},
    "853": {"desc": "Infectious & parasitic dis w/ OR proc w/ MCC",           "medicare": 31500.0, "type": "IP"},
    "329": {"desc": "Major small & large bowel procedures w/ MCC",            "medicare": 38900.0, "type": "IP"},
    "064": {"desc": "Intracranial hemorrhage or cerebral infarction w/ MCC",  "medicare": 12700.0, "type": "IP"},
}

# Outpatient CPT procedures (lower dollar) used in fee-schedule contracts/claims
CPTS = {
    "27447": {"desc": "Total knee arthroplasty",                 "medicare": 1610.0, "type": "OP"},
    "70553": {"desc": "MRI brain w/ & w/o contrast",             "medicare": 480.0,  "type": "OP"},
    "45378": {"desc": "Colonoscopy, diagnostic",                 "medicare": 365.0,  "type": "OP"},
    "93452": {"desc": "Left heart catheterization",             "medicare": 2950.0, "type": "OP"},
    "99285": {"desc": "Emergency dept visit, high complexity",   "medicare": 410.0,  "type": "OP"},
    "29881": {"desc": "Knee arthroscopy w/ meniscectomy",       "medicare": 1340.0, "type": "OP"},
}

# CPTs that commonly require prior authorization (used for Humana PA denials)
PRIOR_AUTH_CPTS = ["70553", "27447", "93452", "29881"]

# --------------------------------------------------------------------------
# Payers. ``factor`` is the multiplier applied to the Medicare base to derive
# the contracted rate for "% of Medicare" payers. ``method`` describes the
# reimbursement methodology for the PDF/terms. ``denial_rate`` is the baseline
# fraction of that payer's claims that deny (before seeded clusters).
# --------------------------------------------------------------------------
PAYERS = {
    "UnitedHealthcare": {
        "plan_type": "Commercial PPO",
        "method": "Percent of Medicare",
        "factor": 1.18,                 # 118% of Medicare baseline
        "timely_filing_days": 90,
        "appeal_window_days": 180,
        "denial_rate": 0.09,
        "prior_auth_required": True,
        "effective": date(2024, 1, 1),
        "term": date(2026, 12, 31),
        "renewal": date(2026, 10, 1),
        "carve_outs": "Transplants, investigational services, and Part B drugs reimbursed under separate addendum.",
        "share": 0.26,
    },
    "Aetna": {
        "plan_type": "Commercial HMO/PPO",
        "method": "Per-DRG case rate",
        "factor": 1.12,
        "timely_filing_days": 120,
        "appeal_window_days": 180,
        "denial_rate": 0.08,
        "prior_auth_required": True,
        "effective": date(2024, 1, 1),
        "term": date(2025, 12, 31),
        "renewal": date(2025, 9, 30),
        "carve_outs": "Behavioral health carved out to Aetna Behavioral Health network.",
        "share": 0.18,
    },
    "Anthem Blue Cross Blue Shield": {
        "plan_type": "Commercial PPO",
        "method": "Percent of Medicare",
        "factor": 1.22,
        "timely_filing_days": 90,
        "appeal_window_days": 90,
        "denial_rate": 0.11,
        "prior_auth_required": True,
        "effective": date(2024, 1, 1),
        "term": date(2026, 6, 30),
        "renewal": date(2026, 4, 1),
        "carve_outs": "Durable medical equipment and home health excluded; billed to ancillary vendor.",
        "share": 0.17,
    },
    "Cigna": {
        "plan_type": "Commercial PPO",
        "method": "Hybrid: DRG case rate (IP) + fee schedule (OP)",
        "factor": 1.10,
        "timely_filing_days": 90,       # tight window -> drives the timely-filing cluster
        "appeal_window_days": 120,
        "denial_rate": 0.10,
        "prior_auth_required": True,
        "effective": date(2024, 1, 1),
        "term": date(2025, 12, 31),
        "renewal": date(2025, 10, 15),
        "carve_outs": "None.",
        "share": 0.12,
    },
    "Humana": {
        "plan_type": "Commercial PPO",
        "method": "Percent of Medicare",
        "factor": 1.08,
        "timely_filing_days": 180,
        "appeal_window_days": 180,
        "denial_rate": 0.10,            # elevated PA denials layered on top
        "prior_auth_required": True,
        "effective": date(2024, 1, 1),
        "term": date(2026, 12, 31),
        "renewal": date(2026, 9, 1),
        "carve_outs": "Imaging requires prior authorization through Cohere Health.",
        "share": 0.10,
    },
    "Medicare Advantage (Wellcare)": {
        "plan_type": "Medicare Advantage",
        "method": "Percent of Medicare",
        "factor": 1.00,                 # MA pays ~ Medicare
        "timely_filing_days": 365,
        "appeal_window_days": 60,
        "denial_rate": 0.13,
        "prior_auth_required": True,
        "effective": date(2024, 1, 1),
        "term": date(2025, 12, 31),
        "renewal": date(2025, 9, 1),
        "carve_outs": "Follows CMS NCD/LCD coverage determinations.",
        "share": 0.10,
    },
    "Sagebrush Regional Health Plan": {
        "plan_type": "Regional Commercial HMO",
        "method": "Per-DRG case rate",
        "factor": 1.05,
        "timely_filing_days": 60,       # tightest commercial window
        "appeal_window_days": 90,
        "denial_rate": 0.12,
        "prior_auth_required": False,
        "effective": date(2024, 1, 1),
        "term": date(2025, 12, 31),
        "renewal": date(2025, 8, 1),
        "carve_outs": "Out-of-area emergency services reimbursed at billed charges up to 150% of Medicare.",
        "share": 0.04,
    },
    "Pioneer Valley Medicaid MCO": {
        "plan_type": "Medicaid Managed Care",
        "method": "Percent of Medicaid fee schedule",
        "factor": 0.78,                 # Medicaid pays well below Medicare
        "timely_filing_days": 95,
        "appeal_window_days": 60,
        "denial_rate": 0.14,
        "prior_auth_required": True,
        "effective": date(2024, 1, 1),
        "term": date(2025, 12, 31),
        "renewal": date(2025, 9, 1),
        "carve_outs": "Non-emergency transportation and dental carved out to state vendor.",
        "share": 0.03,
    },
}

PAYER_LIST = list(PAYERS.keys())

# --------------------------------------------------------------------------
# Contracted rate helper. This is the SINGLE definition of "contracted rate"
# used by the PDF, the contract_terms table, and the claims paid logic.
# --------------------------------------------------------------------------
def contracted_rate(payer: str, drg_code: str) -> float:
    """Contracted allowed amount for a payer + DRG (rounded to nearest $25)."""
    base = DRGS[drg_code]["medicare"]
    factor = PAYERS[payer]["factor"]
    rate = base * factor
    return round(rate / 25.0) * 25.0

def contracted_cpt_rate(payer: str, cpt_code: str) -> float:
    base = CPTS[cpt_code]["medicare"]
    factor = PAYERS[payer]["factor"]
    rate = base * factor
    return round(rate / 5.0) * 5.0

# --------------------------------------------------------------------------
# SEEDED FINDINGS configuration
# --------------------------------------------------------------------------

# 1) Revenue leakage: UnitedHealthcare underpays DRG 470 by ~12% in Q2-2024.
UNDERPAY = {
    "payer": "UnitedHealthcare",
    "drg": "470",
    "quarters": {"2024-Q2"},      # only Q2 of the contract year
    "underpay_pct": 0.12,         # pays 12% below contracted rate
}

# A second, smaller leakage so cross-contract comparison shows more than one:
# Anthem underpays DRG 247 by ~7% in Q3-2024.
UNDERPAY_2 = {
    "payer": "Anthem Blue Cross Blue Shield",
    "drg": "247",
    "quarters": {"2024-Q3"},
    "underpay_pct": 0.07,
}

# 2) Timely-filing denial cluster: Cigna CARC 29 spikes in 2024-Q3.
TIMELY_FILING_CLUSTER = {
    "payer": "Cigna",
    "quarter": "2024-Q3",
    "extra_denial_rate": 0.22,    # +22 pts of claims in that quarter deny as CARC 29
}

# 3) Prior-auth denials: Humana CARC 197 elevated on prior-auth CPTs.
PRIOR_AUTH_CLUSTER = {
    "payer": "Humana",
    "extra_denial_rate": 0.30,    # 30% of PA-required CPT claims deny CARC 197
}

# --------------------------------------------------------------------------
# CARC/RARC denial code reference used in the claims data
# --------------------------------------------------------------------------
DENIAL_CODES = {
    "16":  {"rarc": "N290", "reason": "Claim/service lacks information or has submission error"},
    "29":  {"rarc": "N211", "reason": "The time limit for filing has expired (timely filing)"},
    "197": {"rarc": "N702", "reason": "Precertification/authorization absent (prior auth required)"},
    "50":  {"rarc": "N115", "reason": "Non-covered: not deemed a medical necessity"},
    "97":  {"rarc": "N19",  "reason": "Service included in payment for another service (bundling)"},
    "18":  {"rarc": "N522", "reason": "Exact duplicate claim/service"},
    "B7":  {"rarc": "N570", "reason": "Provider not certified/eligible for this service on date"},
    "109": {"rarc": "N418", "reason": "Claim not covered by this payer; misrouted"},
}

# Default non-seeded denial-code mix (weights) for "organic" denials
ORGANIC_DENIAL_MIX = {
    "16": 0.30,
    "50": 0.20,
    "97": 0.18,
    "18": 0.12,
    "B7": 0.08,
    "109": 0.07,
    "197": 0.03,
    "29": 0.02,
}

# --------------------------------------------------------------------------
# Amendments (drive the AMENDMENT PDFs and an override in contract_terms)
# --------------------------------------------------------------------------
AMENDMENTS = [
    {
        "payer": "UnitedHealthcare",
        "amendment_no": "A-1",
        "effective": date(2024, 7, 1),
        "type": "rate_change",
        "drg": "329",
        "old_factor_note": "118% of Medicare",
        "new_rate_override": 47500.0,   # bumped above the 1.18x base for DRG 329
        "summary": "Increases the contracted case rate for DRG 329 (Major bowel procedures w/ MCC).",
    },
    {
        "payer": "Cigna",
        "amendment_no": "A-2",
        "effective": date(2025, 1, 1),
        "type": "timely_filing_change",
        "old_timely_filing_days": 90,
        "new_timely_filing_days": 120,
        "summary": "Extends the timely-filing submission window from 90 to 120 days.",
    },
]
