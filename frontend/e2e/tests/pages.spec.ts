import { test, expect } from '../fixtures/app.fixture';

test.describe('Frontend Pages', () => {
  test('Home (/) lands in the Library without critical errors', async ({ page, consoleLogger }) => {
    await page.goto('/', { waitUntil: 'networkidle' });

    // Wait for main content to load
    await page.waitForTimeout(2000);

    const errorReport = consoleLogger.getErrorReport();

    // Check no critical 404 errors
    const api404s = errorReport.errors.filter((e) => e.includes('404'));
    expect(api404s.length).toBe(0, `Found 404 errors on home: ${api404s.join(', ')}`);

    // Check no 500 errors
    const api500s = errorReport.errors.filter((e) => e.includes('500'));
    expect(api500s.length).toBe(0, `Found 500 errors on dashboard: ${api500s.join(', ')}`);

    console.log('Home page loaded successfully');
  });

  test('Journey page loads and fetches data', async ({ page, consoleLogger }) => {
    await page.goto('/journey', { waitUntil: 'networkidle' });

    // Wait for journey content to load
    await page.waitForTimeout(2000);

    const errorReport = consoleLogger.getErrorReport();

    // Check no critical errors
    const api404s = errorReport.errors.filter((e) => e.includes('404'));
    expect(api404s.length).toBe(0, `Found 404 errors on journey: ${api404s.join(', ')}`);

    const journey404s = errorReport.errors.filter(
      (e) => e.includes('404') && e.includes('journey')
    );
    expect(journey404s.length).toBe(
      0,
      `Journey API returned 404: ${journey404s.join(', ')}`
    );

    console.log('Journey page loaded successfully');
  });

  test('Analytics page loads without errors', async ({ page, consoleLogger }) => {
    await page.goto('/analytics', { waitUntil: 'networkidle' });

    await page.waitForTimeout(2000);

    const errorReport = consoleLogger.getErrorReport();

    const api404s = errorReport.errors.filter((e) => e.includes('404'));
    expect(api404s.length).toBe(0, `Found 404 errors on analytics: ${api404s.join(', ')}`);

    console.log('Analytics page loaded successfully');
  });

  test('Dives page loads without errors', async ({ page, consoleLogger }) => {
    await page.goto('/dives', { waitUntil: 'networkidle' });

    await page.waitForTimeout(2000);

    const errorReport = consoleLogger.getErrorReport();

    const api404s = errorReport.errors.filter((e) => e.includes('404'));
    expect(api404s.length).toBe(0, `Found 404 errors on dives: ${api404s.join(', ')}`);

    console.log('Dives page loaded successfully');
  });

  test('Sessions page loads without errors', async ({ page, consoleLogger }) => {
    await page.goto('/sessions', { waitUntil: 'networkidle' });

    await page.waitForTimeout(2000);

    const errorReport = consoleLogger.getErrorReport();

    const api404s = errorReport.errors.filter((e) => e.includes('404'));
    expect(api404s.length).toBe(0, `Found 404 errors on sessions: ${api404s.join(', ')}`);

    console.log('Sessions page loaded successfully');
  });

  test('Navigation bar is visible on all pages', async ({ page }) => {
    const pages = ['/', '/journey', '/analytics', '/dives', '/sessions'];

    for (const pagePath of pages) {
      await page.goto(pagePath, { waitUntil: 'networkidle' });

      // Check that navigation links are visible
      const navLinks = await page.locator('nav a');
      const count = await navLinks.count();
      expect(count).toBeGreaterThan(0, `Navigation should be visible on ${pagePath}`);
    }

    console.log('Navigation bar verified on all pages');
  });

  test('Page title and logo are visible', async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle' });

    // Check for app title/logo (sidebar on desktop, top bar on mobile)
    await expect(
      page.locator('text=Dive Analyser').locator('visible=true').first(),
    ).toBeVisible();

    console.log('Page title and logo verified');
  });
});
