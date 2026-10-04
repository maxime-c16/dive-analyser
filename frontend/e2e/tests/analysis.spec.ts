import { test, expect } from '../fixtures/app.fixture';
import type { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * UI-U7 — Analysis progressive disclosure, authenticated against the app.
 * Read-only production validation; failure scenarios use route interception
 * only. Session identity comes from the shared storageState fixture
 * (no login performed here).
 */

const rows = (page: Page) => page.getByRole('button', { name: /Open .* attempt/ });
const viewer = (page: Page) => page.getByRole('dialog');
const backControl = (page: Page) => page.getByTestId('analysis-back');
const sectionToggle = (page: Page, name: RegExp) => page.getByRole('button', { name });

async function openFirstClip(page: Page, query = '103') {
  await page.goto('/dives?scope=all');
  await page.getByRole('textbox', { name: 'Search dives' }).fill(query);
  await rows(page).first().click();
  await expect(viewer(page)).toBeVisible();
}

/** Viewer → Analysis, landing on the calm first screen with attempt context. */
async function viewerToAnalysis(page: Page) {
  await openFirstClip(page);
  await viewer(page).getByRole('link', { name: 'Analysis' }).click();
  // First 103-family row drifts with ingestion (103B-first, now 103C-first); assert attempt-context preservation, not the code itself.
  await expect(page).toHaveURL(/\/dives\/analysis\/[^/]+\?attempt=\d+/);
  await expect(page.getByTestId('analysis-attempt-context')).toContainText('This attempt');
  await expect(backControl(page)).toHaveText('Back to clip');
}

const CRITICAL_SERIOUS = ['critical', 'serious'];

async function axeScan(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .disableRules('region')
    .analyze();
  const blocking = results.violations.filter((violation) =>
    CRITICAL_SERIOUS.includes(violation.impact ?? ''),
  );
  if (results.violations.length > 0) {
    console.log(
      `[axe:${label}]`,
      JSON.stringify(results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }))),
    );
  }
  expect(blocking, `${label}: critical/serious violations`).toEqual([]);
}

test.describe('Analysis review continuity', () => {
  test('A: Viewer → Analysis preserves the selected attempt context', async ({ page }) => {
    await viewerToAnalysis(page);
    await expect(page.getByTestId('analysis-key-summary')).toBeVisible();
    // First screen stays calm: secondary charts mount only on demand.
    await expect(sectionToggle(page, /^Progression/)).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('attempt-progression-chart')).toHaveCount(0);
  });

  test('B: Back to clip restores the exact Viewer attempt', async ({ page }) => {
    await viewerToAnalysis(page);
    const attemptId = new URL(page.url()).searchParams.get('attempt');
    expect(attemptId).toBeTruthy();
    await backControl(page).click();
    await expect(viewer(page)).toBeVisible();
    expect(new URL(page.url()).searchParams.get('clip')).toBe(attemptId);
  });

  test('C: browser Back returns to the exact Viewer', async ({ page }) => {
    await viewerToAnalysis(page);
    await page.goBack();
    await expect(viewer(page)).toBeVisible();
    expect(new URL(page.url()).searchParams.get('clip')).toBeTruthy();
  });

  test('D: direct code-only URL still works with a Library fallback', async ({ page }) => {
    await page.goto('/dives/analysis/103B');
    await expect(backControl(page)).toHaveText('Back to Library');
    await expect(page.getByTestId('analysis-key-summary')).toBeVisible();
    await backControl(page).click();
    await expect(page).toHaveURL(/\/dives\?q=103B/);
  });

  test('E: invalid attempt context fails safe and never claims a clip', async ({ page }) => {
    await page.goto('/dives/analysis/103B?attempt=999999');
    await expect(page.getByTestId('analysis-attempt-mismatch')).toBeVisible();
    await expect(backControl(page)).toHaveText('Back to Library');
    await expect(page.getByTestId('analysis-attempt-context')).toHaveCount(0);
  });
});

test.describe('Analysis availability states', () => {
  test('F: available analysis shows authoritative sections with explicit scope', async ({ page }) => {
    await page.goto('/dives/analysis/103B');
    await expect(page.getByTestId('analysis-scope')).toContainText('attempts in');
    await expect(page.getByTestId('analysis-key-summary')).toBeVisible();
    // Every section is offered; heavy content mounts on open.
    for (const name of [/^Filters/, /^Progression/, /^Comparison/, /^Phase analysis/, /^Attempts to review/]) {
      await expect(sectionToggle(page, name)).toBeVisible();
    }
    await sectionToggle(page, /^Progression/).click();
    await expect(page.getByTestId('attempt-progression-chart').first()).toBeVisible();
    // Partial phase data is labeled, not zero-filled.
    await sectionToggle(page, /^Phase analysis/).click();
    await expect(page.getByText(/scored · \d+ missing/).first()).toBeVisible();
  });

  test('G: empty filter results render an honest unavailable state', async ({ page }) => {
    await page.goto('/dives/analysis/103B?date_from=2099-01-01&date_to=2099-12-31');
    await expect(page.getByTestId('analysis-unavailable')).toContainText('No analysis for this view yet.');
    await expect(page.getByTestId('analysis-key-summary')).toHaveCount(0);
    await expect(sectionToggle(page, /^Progression/)).toHaveCount(0);
    // Filters stay reachable so the view can be widened.
    await expect(sectionToggle(page, /^Filters/)).toBeVisible();
  });

  test('H: transport failure offers Retry that only re-reads', async ({ page }) => {
    let first = true;
    await page.route(
      (url) => url.pathname === '/api/v1/dive-analysis/103B',
      async (route) => {
        if (first) {
          first = false;
          await route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' });
        } else {
          await route.continue();
        }
      },
    );
    await page.goto('/dives/analysis/103B');
    await expect(page.getByTestId('analysis-retry')).toBeVisible();
    await page.getByTestId('analysis-retry').click();
    await expect(page.getByTestId('analysis-key-summary')).toBeVisible();
  });
});

test.describe('Analysis narrow viewports', () => {
  test.use({ viewport: { width: 320, height: 700 }, isMobile: true, hasTouch: true });

  test('I: 320px analysis keeps the back control and sections usable', async ({ page }) => {
    await page.goto('/dives/analysis/103B?attempt=18');
    await expect(backControl(page)).toBeVisible();
    await expect(page.getByTestId('analysis-key-summary')).toBeVisible();
    await sectionToggle(page, /^Attempts to review/).click();
    await expect(page.getByText('Keyboard-accessible source list')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(overflow).toBeLessThanOrEqual(320);
  });

  test('J: landscape analysis keeps first-screen controls reachable', async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    await page.goto('/dives/analysis/103B');
    await expect(backControl(page)).toBeVisible();
    await expect(page.getByRole('heading', { name: '103B' })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(overflow).toBeLessThanOrEqual(844);
  });
});

test.describe('Analysis accessibility', () => {
  test('K: available, unavailable and retry states scan clean', async ({ page }) => {
    await page.goto('/dives/analysis/103B');
    await expect(page.getByTestId('analysis-key-summary')).toBeVisible();
    await axeScan(page, 'analysis-available');
    await sectionToggle(page, /^Progression/).click();
    await expect(page.getByTestId('attempt-progression-chart').first()).toBeVisible();
    await axeScan(page, 'analysis-progression-open');

    await page.goto('/dives/analysis/103B?date_from=2099-01-01&date_to=2099-12-31');
    await expect(page.getByTestId('analysis-unavailable')).toBeVisible();
    await axeScan(page, 'analysis-unavailable');
  });
});
