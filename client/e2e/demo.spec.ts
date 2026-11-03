// End-to-end checks for the static demo build (VITE_DEMO=static).
// BASE_URL=https://<distribution>.cloudfront.net npx playwright test
import { test, expect, type Page, type Locator } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import path from 'node:path';

const SHOTS = process.env.SCREENSHOT_DIR || path.join('test-results', 'screens');
const ALLOWED_OFF_ORIGIN = ['fonts.googleapis.com', 'fonts.gstatic.com'];

// Fail the test on console errors, failed or error responses, any network call to
// /api (the demo must answer those in the browser) and unexpected third parties.
function guard(page: Page) {
  const problems: string[] = [];
  const origin = () => new URL(page.url() === 'about:blank' ? test.info().project.use.baseURL! : page.url()).origin;
  page.on('console', (m) => { if (m.type() === 'error') problems.push(`console error: ${m.text()}`); });
  page.on('pageerror', (e) => problems.push(`page error: ${e.message}`));
  page.on('requestfailed', (r) => problems.push(`request failed: ${r.url()} ${r.failure()?.errorText}`));
  page.on('response', (r) => { if (r.status() >= 400) problems.push(`HTTP ${r.status()}: ${r.url()}`); });
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.protocol === 'data:') return;
    if (u.pathname.startsWith('/api')) problems.push(`network request to /api: ${r.url()}`);
    if (u.origin !== origin() && !ALLOWED_OFF_ORIGIN.includes(u.hostname)) problems.push(`off-origin request: ${r.url()}`);
  });
  return problems;
}

async function axe(page: Page, label: string) {
  const res = await new AxeBuilder({ page }).analyze();
  const bad = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  const summary = bad.map((v) => `${v.impact} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 5).join(' | ')}`);
  // Soft, so one run reports every page's violations; the test still fails.
  expect.soft(summary, `axe serious/critical violations on ${label}`).toEqual([]);
}

function intersects(a: { x: number; y: number; width: number; height: number }, b: typeof a) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

// The banner must not sit on top of any visible button, link, input or textarea.
async function expectBannerClear(page: Page) {
  const banner = await page.getByTestId('demo-banner').boundingBox();
  expect(banner).not.toBeNull();
  const controls = await page.locator('button, a, input, textarea, select').evaluateAll((els) =>
    els
      .filter((e) => e.getAttribute('data-testid') !== 'demo-banner' && !e.closest('[data-testid="demo-banner"]'))
      .map((e) => {
        const r = e.getBoundingClientRect();
        const s = getComputedStyle(e);
        return { x: r.x, y: r.y, width: r.width, height: r.height, visible: r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none', label: (e.textContent || e.getAttribute('title') || e.tagName).trim().slice(0, 40) };
      })
      .filter((c) => c.visible),
  );
  const covered = controls.filter((c) => intersects(banner!, c)).map((c) => c.label);
  expect(covered, 'controls covered by the demo banner').toEqual([]);
}

function lastAssistantText(page: Page): Locator {
  return page.locator('main .prose').last();
}

async function idle(page: Page) {
  await expect(page.locator('main .animate-spin')).toHaveCount(0, { timeout: 15_000 });
}

test.describe('static demo', () => {
  let problems: string[];
  test.beforeEach(async ({ page }) => { problems = guard(page); });
  test.afterEach(() => { expect(problems, 'console, network or origin problems').toEqual([]); });

  test('home loads with the demo banner and passes axe', async ({ page }) => {
    await page.goto('/');
    const banner = page.getByTestId('demo-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveText('Demo with synthetic data. View source on GitHub');
    await expect(banner).toHaveAttribute('href', 'https://github.com/Shashank-Sund/databricks-contract-intelligence');
    await expect(page.getByRole('heading', { name: 'Contract Intelligence' })).toBeVisible();
    await expect(page.getByText('demo.user@example.com')).toHaveCount(1);
    await expectBannerClear(page);
    await page.screenshot({ path: path.join(SHOTS, 'desktop-home.png') });
    await axe(page, 'home');
  });

  test('suggestion streams a tool step, a table, then growing text', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      const w = window as unknown as { __samples: number[] };
      w.__samples = [];
      setInterval(() => {
        const all = document.querySelectorAll('main .prose');
        const el = all[all.length - 1];
        const n = el ? (el.textContent || '').trim().length : 0;
        if (n && n !== w.__samples[w.__samples.length - 1]) w.__samples.push(n);
      }, 20);
    });
    await page.locator('main').getByRole('button', { name: /Which payers underpaid us/ }).click();
    await expect(page.getByText('Genie · querying your data').first()).toBeVisible();
    await expect(page.locator('main table')).toBeVisible();
    await expect(page.locator('main table')).toContainText('UnitedHealthcare');
    await expect(lastAssistantText(page)).toContainText('180-day appeal window', { timeout: 15_000 });
    await idle(page);
    const samples = await page.evaluate(() => (window as unknown as { __samples: number[] }).__samples);
    expect(samples.length, `text length samples ${JSON.stringify(samples)}`).toBeGreaterThanOrEqual(3);
    for (let i = 1; i < samples.length; i++) expect(samples[i]).toBeGreaterThan(samples[i - 1]);
    await expect(page.locator('aside').getByRole('button', { name: /Which payers underpaid us last quarter versus/ })).toBeVisible(); // new chat in history
    await expectBannerClear(page);
    await page.screenshot({ path: path.join(SHOTS, 'desktop-chat.png') });
    await axe(page, 'chat answer');
  });

  test('off-script question gets the generic scripted reply', async ({ page }) => {
    await page.goto('/');
    const box = page.getByPlaceholder(/Ask about your data/);
    await box.fill('What is the weather in Lisbon?');
    await box.press('Enter');
    await expect(lastAssistantText(page)).toContainText('answers only a few scripted questions', { timeout: 15_000 });
    await expect(lastAssistantText(page)).toContainText("Show Cigna's timely-filing denials by quarter");
    await idle(page);
    await expect(page.locator('main table')).toHaveCount(0);
  });

  test('history item loads a stored conversation', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Cigna timely-filing denials by quarter' }).click();
    await expect(page.locator('main table')).toContainText('timely_filing_denials');
    await expect(lastAssistantText(page)).toContainText('Amendment A-2 extended it to 120 days');
    await expect(page.getByText('AMENDMENT_A-2_Cigna.pdf')).toBeVisible();
  });

  test('Genie panel query renders a table', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Revenue Cycle and Claims' }).click();
    const box = page.getByPlaceholder('Ask Revenue Cycle and Claims…');
    await box.fill('Cigna timely-filing denials by quarter');
    await box.press('Enter');
    await expect(page.locator('main table')).toContainText('2024-Q3');
    await expect(page.getByText('Genie chat · multi-turn')).toBeVisible();
    await expectBannerClear(page);
    await page.screenshot({ path: path.join(SHOTS, 'desktop-genie.png') });
    await axe(page, 'genie panel');
  });

  test('deep link reload lands on /', async ({ page }) => {
    const resp = await page.goto('/x');
    expect(resp?.status()).toBe(200);
    await expect(page).toHaveURL(/\/$/);
    await page.goto('/some/deep/path');
    await page.reload();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId('demo-banner')).toBeVisible();
  });
});

test.describe('phone 390x844', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  let problems: string[];
  test.beforeEach(async ({ page }) => { problems = guard(page); });
  test.afterEach(() => { expect(problems, 'console, network or origin problems').toEqual([]); });

  test('no horizontal scroll and banner clear of controls', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('demo-banner')).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, 'phone-home.png') });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect.soft(overflow, 'horizontal overflow in px').toBeLessThanOrEqual(0);
    await expectBannerClear(page);
    await page.locator('main').getByRole('button', { name: /Which payers underpaid us/ }).click();
    await expect(lastAssistantText(page)).toContainText('180-day appeal window', { timeout: 15_000 });
    await idle(page);
    await page.screenshot({ path: path.join(SHOTS, 'phone-chat.png') });
    const overflow2 = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect.soft(overflow2, 'horizontal overflow after chat in px').toBeLessThanOrEqual(0);
    await expectBannerClear(page);
    await axe(page, 'phone chat');
  });
});
