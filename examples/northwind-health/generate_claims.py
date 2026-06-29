"""
generate_claims.py
===================
Writes a 30,000-row synthetic claims dataset modeling the X12 837 (billed) +
835 (remittance/paid) lifecycle to ./data/claims.parquet
(plus a 1,000-row claims_sample.csv).

Every claim joins to contract_terms on (payer_name, drg_code) -- or
(payer_name, cpt_code) for outpatient -- so paid_amount vs contracted_rate
comparisons compute correctly and reproduce the seeded findings defined in
demo_config.py:

  * UnitedHealthcare underpays DRG 470 ~12% in 2024-Q2  (revenue leakage)
  * Anthem underpays DRG 247 ~7% in 2024-Q3             (secondary leakage)
  * Cigna timely-filing (CARC 29) cluster in 2024-Q3
  * Humana prior-auth (CARC 197) denials on PA-required CPTs
  * Overall denial rate ~8-15%, varying by payer
"""
import os
import random
from datetime import timedelta

import numpy as np
import pandas as pd
from faker import Faker

import demo_config as cfg

SEED = 20240623
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

N_CLAIMS = 30000
INPATIENT_FRACTION = 0.45   # rest are outpatient CPT claims

DRG_CODES = list(cfg.DRGS.keys())
CPT_CODES = list(cfg.CPTS.keys())

# Payer sampling weights from configured share
_payer_names = cfg.PAYER_LIST
_payer_weights = np.array([cfg.PAYERS[p]["share"] for p in _payer_names], dtype=float)
_payer_weights /= _payer_weights.sum()

# Pre-build a pool of members/patients per payer for referential realism
def _build_member_pool():
    pool = {}
    for payer in _payer_names:
        n = 1200
        members = [f"{payer[:3].upper()}{fake.random_number(digits=9, fix_len=True)}" for _ in range(n)]
        patients = [f"P{fake.random_number(digits=8, fix_len=True)}" for _ in range(n)]
        pool[payer] = list(zip(members, patients))
    return pool

MEMBER_POOL = _build_member_pool()


def _rand_date(start, end):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _organic_denial_code():
    codes = list(cfg.ORGANIC_DENIAL_MIX.keys())
    weights = list(cfg.ORGANIC_DENIAL_MIX.values())
    return random.choices(codes, weights=weights, k=1)[0]


def _eft(payer):
    return f"EFT{abs(hash(payer)) % 1000:03d}{fake.random_number(digits=7, fix_len=True)}"


def generate():
    rows = []
    n_ip = int(N_CLAIMS * INPATIENT_FRACTION)
    types = ["IP"] * n_ip + ["OP"] * (N_CLAIMS - n_ip)
    random.shuffle(types)

    payers = np.random.choice(_payer_names, size=N_CLAIMS, p=_payer_weights)

    for i in range(N_CLAIMS):
        payer = payers[i]
        p = cfg.PAYERS[payer]
        claim_type = types[i]
        facility = random.choice(cfg.FACILITIES)
        member, patient = random.choice(MEMBER_POOL[payer])

        service_date = _rand_date(cfg.CLAIMS_START, cfg.CLAIMS_END)
        qtr = cfg.quarter_of(service_date)

        # ---- code + billed/contracted -------------------------------------
        if claim_type == "IP":
            drg = random.choice(DRG_CODES)
            drg_desc = cfg.DRGS[drg]["desc"]
            cpt = None
            cpt_desc = None
            pos = facility["pos"] if facility["pos"] in ("21", "22") else "21"
            contracted = cfg.contracted_rate(payer, drg)
            # billed charges run well above contracted (charge master inflation)
            billed = round(contracted * random.uniform(1.8, 3.1), 2)
        else:
            cpt = random.choice(CPT_CODES)
            cpt_desc = cfg.CPTS[cpt]["desc"]
            drg = None
            drg_desc = None
            pos = facility["pos"]
            contracted = cfg.contracted_cpt_rate(payer, cpt)
            billed = round(contracted * random.uniform(2.0, 4.0), 2)

        # ---- submit date (837) --------------------------------------------
        # Normally filed within the filing window; some late.
        lag = max(1, int(np.random.gamma(2.2, 9)))   # ~ a few weeks typical
        submit_date = service_date + timedelta(days=lag)

        # ---- decide denial vs paid ----------------------------------------
        denied = False
        denial_code = None
        partial = False

        base_rate = p["denial_rate"]

        # Seeded: Cigna timely-filing cluster in a quarter
        tf = cfg.TIMELY_FILING_CLUSTER
        if payer == tf["payer"] and qtr == tf["quarter"] and random.random() < tf["extra_denial_rate"]:
            denied = True
            denial_code = "29"
            # make the submit lag actually exceed filing window for realism
            submit_date = service_date + timedelta(days=p["timely_filing_days"] + random.randint(5, 45))

        # Seeded: Humana prior-auth denials on PA-required CPTs
        pa = cfg.PRIOR_AUTH_CLUSTER
        if (not denied and payer == pa["payer"] and claim_type == "OP"
                and cpt in cfg.PRIOR_AUTH_CPTS and random.random() < pa["extra_denial_rate"]):
            denied = True
            denial_code = "197"

        # Organic denials
        if not denied and random.random() < base_rate:
            denied = True
            denial_code = _organic_denial_code()

        # ---- compute allowed / paid ---------------------------------------
        if denied:
            allowed = 0.0
            paid = 0.0
            patient_resp = 0.0
            adjustment = round(billed, 2)        # full contractual + denial writeoff
            status = "denied"
            paid_date = None
            eft = None
        else:
            allowed = float(contracted)

            # Seeded underpayments (paid below contracted) -------------------
            up = cfg.UNDERPAY
            up2 = cfg.UNDERPAY_2
            underpay_factor = 1.0
            if (payer == up["payer"] and drg == up["drg"] and qtr in up["quarters"]):
                underpay_factor = 1.0 - up["underpay_pct"]
            elif (payer == up2["payer"] and drg == up2["drg"] and qtr in up2["quarters"]):
                underpay_factor = 1.0 - up2["underpay_pct"]

            # Patient responsibility (copay/coinsurance/deductible)
            if claim_type == "IP":
                patient_resp = round(allowed * random.uniform(0.0, 0.08), 2)
            else:
                patient_resp = round(allowed * random.uniform(0.0, 0.20), 2)

            ideal_payer_paid = max(0.0, allowed - patient_resp)
            payer_paid = round(ideal_payer_paid * underpay_factor, 2)

            # small organic short-pays (partial) on a slice of clean claims
            if underpay_factor == 1.0 and random.random() < 0.04:
                payer_paid = round(payer_paid * random.uniform(0.85, 0.97), 2)

            paid = payer_paid
            # partial flag when payer paid materially less than (allowed - patient_resp)
            partial = paid < round(ideal_payer_paid - 0.5, 2)
            status = "partial" if partial else "paid"
            adjustment = round(billed - allowed, 2)   # contractual adjustment
            pay_lag = max(7, int(np.random.gamma(3.0, 8)))
            paid_date = submit_date + timedelta(days=pay_lag)
            eft = _eft(payer)
            denial_code = None

        rarc = cfg.DENIAL_CODES[denial_code]["rarc"] if denial_code else None
        denial_reason = cfg.DENIAL_CODES[denial_code]["reason"] if denial_code else None

        rows.append({
            "claim_id": f"CLM{i+100000:08d}",
            "payer_name": payer,
            "plan_type": p["plan_type"],
            "member_id": member,
            "patient_id": patient,
            "provider_npi": facility["npi"],
            "facility": facility["facility"],
            "service_date": service_date,
            "submit_date": submit_date,            # 837
            "service_quarter": qtr,
            "claim_type": "Inpatient" if claim_type == "IP" else "Outpatient",
            "drg_code": drg,
            "drg_description": drg_desc,
            "cpt_code": cpt,
            "cpt_description": cpt_desc,
            "place_of_service": pos,
            "billed_amount": billed,               # 837
            "contracted_rate": float(contracted),  # convenience copy of ground truth
            "allowed_amount": round(allowed, 2),   # 835
            "paid_amount": round(paid, 2),         # 835
            "patient_responsibility": round(patient_resp, 2),
            "adjustment_amount": round(adjustment, 2),
            "denial_code": denial_code,            # CARC
            "remark_code": rarc,                   # RARC
            "denial_reason": denial_reason,
            "claim_status": status,
            "paid_date": paid_date,                # 835
            "check_eft_number": eft,
        })

    df = pd.DataFrame(rows)
    for col in ["service_date", "submit_date", "paid_date"]:
        df[col] = pd.to_datetime(df[col])
    return df


def _print_findings(df):
    print("\n=== sanity / seeded-finding checks ===")
    tot = len(df)
    den = (df["claim_status"] == "denied").sum()
    print(f"total claims: {tot}")
    print(f"overall denial rate: {den/tot:.1%}")

    print("\ndenial rate by payer:")
    g = df.groupby("payer_name").apply(
        lambda x: pd.Series({"claims": len(x), "denial_rate": (x.claim_status == 'denied').mean()}),
        include_groups=False,
    )
    print(g.to_string())

    # UnitedHealthcare DRG 470 Q2 underpayment
    sub = df[(df.payer_name == "UnitedHealthcare") & (df.drg_code == "470")
             & (df.claim_status != "denied")]
    if len(sub):
        q2 = sub[sub.service_quarter == "2024-Q2"]
        other = sub[sub.service_quarter != "2024-Q2"]
        def collect_ratio(x):
            return (x.paid_amount + x.patient_responsibility).sum() / x.contracted_rate.sum()
        print(f"\nUHC DRG470 collected/contracted  Q2-2024: {collect_ratio(q2):.3f} "
              f"({len(q2)} claims) | other qtrs: {collect_ratio(other):.3f} ({len(other)} claims)")

    # Cigna timely filing CARC 29
    cig = df[(df.payer_name == "Cigna")]
    c29 = cig[(cig.denial_code == "29")]
    print(f"\nCigna CARC-29 denials: {len(c29)} total; by quarter:")
    print(c29.groupby("service_quarter").size().to_string())

    # Humana prior auth CARC 197
    hum = df[(df.payer_name == "Humana") & (df.denial_code == "197")]
    print(f"\nHumana CARC-197 (prior auth) denials: {len(hum)} "
          f"(of {len(df[df.payer_name=='Humana'])} Humana claims)")

    print(f"\nbilled_amount range: ${df.billed_amount.min():,.0f} - ${df.billed_amount.max():,.0f}")
    ip = df[df.claim_type == 'Inpatient']
    print(f"inpatient allowed range: ${ip.allowed_amount[ip.allowed_amount>0].min():,.0f} - "
          f"${ip.allowed_amount.max():,.0f}")


def main():
    df = generate()
    pq = os.path.join(DATA, "claims.parquet")
    df.to_parquet(pq, index=False)
    sample = df.sample(1000, random_state=SEED).sort_values("claim_id")
    sample.to_csv(os.path.join(DATA, "claims_sample.csv"), index=False)
    print(f"claims rows: {len(df)}")
    print(f"  wrote {pq}")
    print(f"  wrote {os.path.join(DATA, 'claims_sample.csv')} (1000-row sample)")
    _print_findings(df)


if __name__ == "__main__":
    main()
