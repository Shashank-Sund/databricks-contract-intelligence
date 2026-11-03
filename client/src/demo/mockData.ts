// Synthetic data for the static demo build (VITE_DEMO=static). It mirrors the
// Northwind Health example story in examples/northwind-health/DATA.md. Every
// name, number and document here is fictional.
import { branding, home } from '../../../examples/northwind-health/config.json';

export const appConfig = { branding, home };

export const demoUser = { email: 'demo.user@example.com' };

export const genieSpaces = {
  default_space_id: 'rc',
  spaces: [
    { space_id: 'rc', title: 'Revenue Cycle and Claims', description: 'Claims, payments, denials and contracted rates' },
    { space_id: 'pc', title: 'Payer Contract Terms', description: 'Rates, filing windows, appeal windows, carve-outs' },
  ],
};

export interface ToolCall { name: string; question: string }
export interface Story {
  tool?: ToolCall;
  ui?: Record<string, unknown>;
  doc?: ToolCall;
  docUi?: Record<string, unknown>;
  text: string;
}

export const leakage: Story = {
  tool: { name: 'query_data', question: 'Underpayment versus contracted rate by payer and DRG, most recent quarters' },
  ui: {
    type: 'genie', ok: true, row_count: 4,
    columns: ['payer_name', 'drg_code', 'service_quarter', 'claims', 'collected_total', 'underpaid', 'pct_below_contract'],
    rows: [
      ['UnitedHealthcare', '470', '2024-Q2', 66, '$982,650', '$127,800', '11.5%'],
      ['Anthem Blue Cross Blue Shield', '247', '2024-Q3', 38, '$755,216', '$56,844', '7.0%'],
      ['Aetna', '470', '2024-Q2', 52, '$871,400', '$3,500', '0.4%'],
      ['Cigna', '329', '2024-Q2', 21, '$610,720', '$1,220', '0.2%'],
    ],
    sql: `SELECT payer_name, drg_code, drg_description, service_quarter,
       COUNT(*)                                   AS claims,
       SUM(contracted_rate)                       AS contracted_total,
       SUM(allowed_amount)                        AS collected_total,
       SUM(contracted_rate - allowed_amount)      AS underpaid,
       ROUND(100 * SUM(contracted_rate - allowed_amount) / SUM(contracted_rate), 1) AS pct_below_contract
FROM   northwind_health.revenue_cycle.underpayment_dollars_by_payer_drg
WHERE  claim_status <> 'denied'
GROUP  BY ALL
HAVING underpaid > 0
ORDER  BY underpaid DESC
LIMIT  10`,
  },
  doc: { name: 'search_documents', question: 'UnitedHealthcare contracted case rate for DRG 470 and payment terms' },
  docUi: { type: 'contract', ok: true, citations: [{ source_file: 'NWH-2024-001_UnitedHealthcare.pdf', page_id: 4 }, { source_file: 'NWH-2024-003_Anthem_Blue_Cross_Blue_Shield.pdf', page_id: 5 }] },
  text: `**UnitedHealthcare is the main source of revenue leakage.** In 2024-Q2 it paid about **11.5% below the contracted case rate on DRG 470** (major hip and knee replacement): roughly **$127,800 under-collected across 66 claims**. Every other quarter collected 99 to 100% of contract.

A smaller leak sits with **Anthem on DRG 247 in 2024-Q3** (about 7% below contract, $56,844).

**What the contracts say.** The UnitedHealthcare agreement sets DRG 470 at a **$16,825 case rate (118% of Medicare base)** with no volume tiering, so the shortfall is not explained by contract terms (NWH-2024-001, p4). Anthem's DRG 247 rate is also a fixed case rate (NWH-2024-003, p5).

**Suggested next step:** open an underpayment appeal with UnitedHealthcare for the 66 DRG 470 claims. The contract's 180-day appeal window still applies to the most recent claims.`,
};

export const cigna: Story = {
  tool: { name: 'query_data', question: 'Cigna timely-filing denials (CARC 29) by service quarter' },
  ui: {
    type: 'genie', ok: true, row_count: 6,
    columns: ['service_quarter', 'cigna_claims', 'timely_filing_denials', 'denial_rate'],
    rows: [['2024-Q1', 402, 1, '0.2%'], ['2024-Q2', 391, 1, '0.3%'], ['2024-Q3', 377, 135, '35.8%'], ['2024-Q4', 366, 0, '0.0%'], ['2025-Q1', 381, 0, '0.0%'], ['2025-Q2', 355, 2, '0.6%']],
    sql: `SELECT service_quarter,
       COUNT(*)                                        AS cigna_claims,
       COUNT_IF(denial_code = 'CARC 29')               AS timely_filing_denials,
       ROUND(100 * COUNT_IF(denial_code = 'CARC 29') / COUNT(*), 1) AS denial_rate
FROM   northwind_health.revenue_cycle.claims
WHERE  payer_name = 'Cigna'
GROUP  BY service_quarter
ORDER  BY service_quarter`,
  },
  doc: { name: 'search_documents', question: 'Cigna timely filing window in the agreement and Amendment A-2' },
  docUi: { type: 'contract', ok: true, citations: [{ source_file: 'NWH-2024-004_Cigna.pdf', page_id: 6 }, { source_file: 'AMENDMENT_A-2_Cigna.pdf', page_id: 1 }] },
  text: `**Cigna's timely-filing denials spiked in 2024-Q3:** 135 of the 139 CARC 29 denials in the data, a 35.8% denial rate that quarter versus under 1% in every other quarter.

**Why it happened.** The original Cigna agreement allowed only **90 days** from the date of service to file a claim, the shortest window of any payer (NWH-2024-004, p6). **Amendment A-2 extended it to 120 days** (AMENDMENT_A-2_Cigna, p1), and denials dropped back to near zero after it took effect.

**Suggested next step:** confirm the 2024-Q3 claims were filed inside 120 days and, where they were, appeal them under the amended terms.`,
};

// Off-script questions get this reply so the demo never looks broken.
export const generic: Story = {
  text: `This is a static demo with synthetic data, so it answers only a few scripted questions. There is no model or database behind it.

Try one of these:

- **Which payers underpaid us last quarter versus our contracted rates?**
- **Show Cigna's timely-filing denials by quarter. When did they spike?**

The full app, deployed as a Databricks App in your own workspace, answers any question over your own tables and documents.`,
};

export const genericGenieText =
  'This static demo answers a few scripted questions. Try "Which payers underpaid us versus contract?" or "Cigna timely-filing denials by quarter".';

const CIGNA_RE = /cigna|timely|denial|filing/i;
const LEAKAGE_RE = /underpa|leak|contract|unitedhealthcare|united|drg|amendment|payer|reimburs|revenue|appeal/i;

export function pickStory(message: string): Story {
  if (CIGNA_RE.test(message)) return cigna;
  if (LEAKAGE_RE.test(message)) return leakage;
  return generic;
}

export interface ConvSummary { conversation_id: string; title: string }

export function seedHistory(): ConvSummary[] {
  return [
    { conversation_id: 'c-leak', title: 'Which payers underpaid us last quarter?' },
    { conversation_id: 'c-cigna', title: 'Cigna timely-filing denials by quarter' },
    { conversation_id: 'c-appeal', title: 'Appeal windows across payer contracts' },
    { conversation_id: 'c-a1', title: 'What did Amendment A-1 change?' },
  ];
}
