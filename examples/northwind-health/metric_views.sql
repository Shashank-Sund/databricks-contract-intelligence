-- =====================================================================
-- metric_views.sql
-- Unity Catalog views + a Lakehouse metric view for the contract-intelligence
-- revenue-cycle demo. Joins claims to the normalized contract_terms ground
-- truth so reimbursement-variance, denial-rate, and underpayment metrics are
-- computed consistently across SQL, AI/BI dashboards, and Genie.
--
-- Parameterized on {catalog}.{schema}. Replace the placeholders before running,
-- e.g.:   sed 's/{catalog}/northwind/g; s/{schema}/contract_intelligence/g'
-- The load_to_uc.py script substitutes these automatically.
--
-- Tables assumed present (created by load_to_uc.py):
--   {catalog}.{schema}.claims
--   {catalog}.{schema}.contract_terms
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. Enriched join view: every paid/denied claim line aligned to its
--    contracted rate. Inpatient lines join on DRG; outpatient on CPT.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW {catalog}.{schema}.claims_contract_enriched AS
WITH ip AS (
  SELECT
    c.*,
    t.contracted_rate        AS term_contracted_rate,
    t.reimbursement_method,
    t.timely_filing_days,
    t.appeal_window_days,
    t.prior_auth_required,
    t.renewal_date,
    t.term_date,
    t.carve_outs
  FROM {catalog}.{schema}.claims c
  JOIN {catalog}.{schema}.contract_terms t
    ON c.payer_name = t.payer_name
   AND c.drg_code   = t.drg_code
  WHERE c.claim_type = 'Inpatient'
),
op AS (
  SELECT
    c.*,
    t.contracted_rate        AS term_contracted_rate,
    t.reimbursement_method,
    t.timely_filing_days,
    t.appeal_window_days,
    t.prior_auth_required,
    t.renewal_date,
    t.term_date,
    t.carve_outs
  FROM {catalog}.{schema}.claims c
  JOIN {catalog}.{schema}.contract_terms t
    ON c.payer_name = t.payer_name
   AND c.cpt_code   = t.cpt_code
  WHERE c.claim_type = 'Outpatient'
)
SELECT * FROM ip
UNION ALL
SELECT * FROM op;

-- ---------------------------------------------------------------------
-- 1. reimbursement_variance: paid vs contracted ($ and %).
--    Positive variance_amount = underpayment (contracted owed but not collected).
--    "collected" = payer paid + patient responsibility (what the system received).
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW {catalog}.{schema}.reimbursement_variance AS
SELECT
  payer_name,
  service_quarter,
  claim_type,
  COALESCE(drg_code, cpt_code)                       AS code,
  COALESCE(drg_description, cpt_description)          AS code_description,
  COUNT(*)                                            AS claim_count,
  ROUND(SUM(term_contracted_rate), 2)                 AS contracted_total,
  ROUND(SUM(paid_amount + patient_responsibility), 2) AS collected_total,
  ROUND(SUM(term_contracted_rate)
        - SUM(paid_amount + patient_responsibility), 2) AS variance_amount,
  ROUND( (SUM(term_contracted_rate)
          - SUM(paid_amount + patient_responsibility))
         / NULLIF(SUM(term_contracted_rate), 0), 4)   AS variance_pct
FROM {catalog}.{schema}.claims_contract_enriched
WHERE claim_status <> 'denied'    -- variance is meaningful only on adjudicated/paid claims
GROUP BY payer_name, service_quarter, claim_type,
         COALESCE(drg_code, cpt_code),
         COALESCE(drg_description, cpt_description);

-- ---------------------------------------------------------------------
-- 2. denial_rate_by_payer: denial counts/rate + a timely-filing breakout.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW {catalog}.{schema}.denial_rate_by_payer AS
SELECT
  payer_name,
  service_quarter,
  COUNT(*)                                                          AS total_claims,
  SUM(CASE WHEN claim_status = 'denied' THEN 1 ELSE 0 END)          AS denied_claims,
  ROUND(AVG(CASE WHEN claim_status = 'denied' THEN 1 ELSE 0 END), 4) AS denial_rate,
  SUM(CASE WHEN denial_code = '29'  THEN 1 ELSE 0 END)             AS timely_filing_denials,   -- CARC 29
  SUM(CASE WHEN denial_code = '197' THEN 1 ELSE 0 END)             AS prior_auth_denials,      -- CARC 197
  ROUND(SUM(CASE WHEN claim_status = 'denied' THEN billed_amount ELSE 0 END), 2) AS denied_billed_amount
FROM {catalog}.{schema}.claims
GROUP BY payer_name, service_quarter;

-- ---------------------------------------------------------------------
-- 3. underpayment_dollars_by_payer_drg: the revenue-leakage view.
--    Surfaces payer+DRG combinations where we collected less than contracted.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW {catalog}.{schema}.underpayment_dollars_by_payer_drg AS
SELECT
  payer_name,
  drg_code,
  drg_description,
  service_quarter,
  COUNT(*)                                            AS paid_claim_count,
  ROUND(AVG(term_contracted_rate), 2)                 AS avg_contracted_rate,
  ROUND(AVG(paid_amount + patient_responsibility), 2) AS avg_collected,
  ROUND(SUM(term_contracted_rate
            - (paid_amount + patient_responsibility)), 2) AS underpayment_dollars,
  ROUND( SUM(term_contracted_rate - (paid_amount + patient_responsibility))
         / NULLIF(SUM(term_contracted_rate), 0), 4)   AS underpayment_pct
FROM {catalog}.{schema}.claims_contract_enriched
WHERE claim_status <> 'denied'
  AND claim_type = 'Inpatient'
GROUP BY payer_name, drg_code, drg_description, service_quarter
HAVING SUM(term_contracted_rate - (paid_amount + patient_responsibility)) > 0
ORDER BY underpayment_dollars DESC;

-- =====================================================================
-- 4. Unity Catalog METRIC VIEW (governed, reusable semantics).
--    Requires Databricks Runtime / DBSQL with metric views enabled.
--    Defined over the enriched join so dimensions + measures are reusable
--    in AI/BI dashboards and Genie. If your workspace does not yet support
--    CREATE VIEW ... WITH METRICS LANGUAGE YAML, the plain views above are
--    sufficient for the demo.
-- =====================================================================
CREATE OR REPLACE VIEW {catalog}.{schema}.revenue_cycle_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: {catalog}.{schema}.claims_contract_enriched
filter: claim_status <> 'denied'
dimensions:
  - name: Payer
    expr: payer_name
  - name: Plan Type
    expr: plan_type
  - name: Service Quarter
    expr: service_quarter
  - name: Claim Type
    expr: claim_type
  - name: DRG
    expr: drg_code
  - name: Reimbursement Method
    expr: reimbursement_method
measures:
  - name: Claim Count
    expr: COUNT(1)
  - name: Contracted Dollars
    expr: SUM(term_contracted_rate)
  - name: Collected Dollars
    expr: SUM(paid_amount + patient_responsibility)
  - name: Underpayment Dollars
    expr: SUM(term_contracted_rate - (paid_amount + patient_responsibility))
  - name: Reimbursement Variance Pct
    expr: SUM(term_contracted_rate - (paid_amount + patient_responsibility)) / NULLIF(SUM(term_contracted_rate), 0)
$$;

-- ---------------------------------------------------------------------------
-- renewal_risk: per-payer contract renewal timing crossed with financial
-- leverage (total underpayment + denial rate), so you can prioritize which
-- renewals to negotiate. days_to_renewal is computed against the current date,
-- so "renews in the next N days" stays correct over time.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW {catalog}.{schema}.renewal_risk AS
WITH terms AS (
  SELECT payer_name, MIN(effective_date) AS effective_date, MAX(term_date) AS term_date
  FROM {catalog}.{schema}.contract_terms GROUP BY payer_name
),
underpay AS (
  SELECT payer_name, SUM(underpayment_dollars) AS total_underpayment
  FROM {catalog}.{schema}.underpayment_dollars_by_payer_drg GROUP BY payer_name
),
denials AS (
  SELECT payer_name, ROUND(SUM(denied_claims) / SUM(total_claims), 4) AS denial_rate
  FROM {catalog}.{schema}.denial_rate_by_payer GROUP BY payer_name
)
SELECT
  t.payer_name,
  t.effective_date,
  t.term_date,
  datediff(t.term_date, current_date()) AS days_to_renewal,
  CASE
    WHEN datediff(t.term_date, current_date()) < 0   THEN 'Expired / evergreen'
    WHEN datediff(t.term_date, current_date()) <= 30  THEN 'Critical (<=30 days)'
    WHEN datediff(t.term_date, current_date()) <= 90  THEN 'High (<=90 days)'
    WHEN datediff(t.term_date, current_date()) <= 180 THEN 'Medium (<=180 days)'
    ELSE 'Low (>180 days)'
  END AS renewal_window,
  ROUND(COALESCE(u.total_underpayment, 0), 2) AS total_underpayment,
  COALESCE(d.denial_rate, 0) AS denial_rate
FROM terms t
LEFT JOIN underpay u ON t.payer_name = u.payer_name
LEFT JOIN denials d ON t.payer_name = d.payer_name;
