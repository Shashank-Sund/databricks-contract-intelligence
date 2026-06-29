"""
generate_contract_terms.py
===========================
Writes ./data/contract_terms.parquet (+ .csv) -- the normalized
clause-level table that an ``ai_extract`` over the contract PDFs would produce.

One row per (payer, drg_code). Outpatient CPT rates are emitted as additional
rows with drg_code = NULL and a cpt_code set, so the same table covers both
inpatient DRG case rates and outpatient fee-schedule lines.

This table is the GROUND TRUTH that the claims paid-amount logic compares
against, so reimbursement-variance and underpayment queries reproduce exactly.
"""
import os
import pandas as pd

import demo_config as cfg

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)


def _amendment_overrides():
    """Map (payer, drg) -> overridden contracted_rate from rate-change amendments,
    and (payer) -> overridden timely_filing_days from TF amendments."""
    rate_over = {}
    tf_over = {}
    for am in cfg.AMENDMENTS:
        if am["type"] == "rate_change":
            rate_over[(am["payer"], am["drg"])] = am["new_rate_override"]
        elif am["type"] == "timely_filing_change":
            tf_over[am["payer"]] = am["new_timely_filing_days"]
    return rate_over, tf_over


def build():
    rate_over, tf_over = _amendment_overrides()
    rows = []
    for payer, p in cfg.PAYERS.items():
        tf_days = p["timely_filing_days"]
        amended_tf = tf_over.get(payer)
        # Inpatient DRG rows
        for drg, d in cfg.DRGS.items():
            rate = cfg.contracted_rate(payer, drg)
            if (payer, drg) in rate_over:
                rate = rate_over[(payer, drg)]
            rows.append({
                "payer_name": payer,
                "plan_type": p["plan_type"],
                "effective_date": p["effective"],
                "term_date": p["term"],
                "reimbursement_method": p["method"],
                "drg_code": drg,
                "drg_description": d["desc"],
                "cpt_code": None,
                "cpt_description": None,
                "service_category": "Inpatient",
                "contracted_rate": float(rate),
                "rate_basis": f"{int(p['factor']*100)}% of Medicare base"
                              if p["method"].startswith("Percent")
                              else "Negotiated case rate",
                "timely_filing_days": tf_days,
                "timely_filing_days_amended": amended_tf,
                "appeal_window_days": p["appeal_window_days"],
                "prior_auth_required": p["prior_auth_required"],
                "carve_outs": p["carve_outs"],
                "renewal_date": p["renewal"],
                "amended": (payer, drg) in rate_over,
            })
        # Outpatient CPT rows
        for cpt, c in cfg.CPTS.items():
            rate = cfg.contracted_cpt_rate(payer, cpt)
            rows.append({
                "payer_name": payer,
                "plan_type": p["plan_type"],
                "effective_date": p["effective"],
                "term_date": p["term"],
                "reimbursement_method": p["method"],
                "drg_code": None,
                "drg_description": None,
                "cpt_code": cpt,
                "cpt_description": c["desc"],
                "service_category": "Outpatient",
                "contracted_rate": float(rate),
                "rate_basis": "Outpatient fee schedule",
                "timely_filing_days": tf_days,
                "timely_filing_days_amended": amended_tf,
                "appeal_window_days": p["appeal_window_days"],
                "prior_auth_required": cpt in cfg.PRIOR_AUTH_CPTS and p["prior_auth_required"],
                "carve_outs": p["carve_outs"],
                "renewal_date": p["renewal"],
                "amended": False,
            })

    df = pd.DataFrame(rows)
    # normalize date columns to datetime64
    for col in ["effective_date", "term_date", "renewal_date"]:
        df[col] = pd.to_datetime(df[col])
    return df


def main():
    df = build()
    pq = os.path.join(DATA, "contract_terms.parquet")
    csv = os.path.join(DATA, "contract_terms.csv")
    df.to_parquet(pq, index=False)
    df.to_csv(csv, index=False)
    print(f"contract_terms rows: {len(df)}")
    print(f"  payers: {df['payer_name'].nunique()}  drg lines: {df['drg_code'].notna().sum()}  cpt lines: {df['cpt_code'].notna().sum()}")
    print(f"  wrote {pq}")
    print(f"  wrote {csv}")


if __name__ == "__main__":
    main()
