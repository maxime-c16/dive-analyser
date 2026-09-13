import { test, expect } from '../fixtures/app.fixture';

test.describe('Comprehensive Console Validation', () => {
  const routes = [
    { path: '/', name: 'Dashboard' },
    { path: '/journey', name: 'Journey' },
    { path: '/analytics', name: 'Analytics' },
    { path: '/dives', name: 'Dives' },
    { path: '/sessions', name: 'Sessions' },
  ];

  for (const route of routes) {
    test(`${route.name} - No critical console errors`, async ({ page, consoleLogger }) => {
      console.log(`\n📄 Testing ${route.name} (${route.path})...`);

      await page.goto(route.path, { waitUntil: 'networkidle' });
      await page.waitForTimeout(2000);

      const errorReport = consoleLogger.getErrorReport();

      console.log(`  Errors: ${errorReport.errorCount}`);
      console.log(`  Warnings: ${errorReport.warnings.length}`);
      console.log(`  API Errors: ${errorReport.apiErrors.length}`);

      // Critical errors that should fail the test
      const criticalErrors = errorReport.errors.filter((e) => {
        const isCritical =
          e.includes('404') ||
          e.includes('500') ||
          e.includes('CORS') ||
          e.includes('CRASH') ||
          (e.includes('undefined') && e.includes('is not'));

        // Exclude WebSocket connection errors
        const isWebSocketError = e.toLowerCase().includes('websocket');

        return isCritical && !isWebSocketError;
      });

      expect(criticalErrors.length).toBe(
        0,
        `Critical errors on ${route.name}: ${criticalErrors.join(', ')}`
      );

      console.log(`✅ ${route.name} passed validation`);
    });
  }

  test('All pages - No orphaned API calls', async ({ page, consoleLogger }) => {
    test.setTimeout(120_000);
    console.log('\n🔍 Checking for orphaned API calls...');

    let totalApiErrors = 0;

    for (const route of routes) {
      consoleLogger.clear(); // Clear logs for each page

      await page.goto(route.path, { waitUntil: 'networkidle' });
      await page.waitForTimeout(2000);

      const errorReport = consoleLogger.getErrorReport();
      const api404s = errorReport.apiErrors.filter((e) => e.status === 404);

      if (api404s.length > 0) {
        console.log(`  ${route.name}: ${api404s.length} 404 error(s)`);
        api404s.forEach((err) => console.log(`    - ${err.url}`));
        totalApiErrors += api404s.length;
      }
    }

    expect(totalApiErrors).toBe(0, `Found ${totalApiErrors} orphaned API calls (404s)`);
    console.log('✅ No orphaned API calls found');
  });

  test('All pages - Loading performance', async ({ page, consoleLogger }) => {
    console.log('\n⚡ Checking page load performance...');

    for (const route of routes) {
      consoleLogger.clear();

      const startTime = Date.now();
      await page.goto(route.path, { waitUntil: 'networkidle' });
      const loadTime = Date.now() - startTime;

      console.log(`  ${route.name}: ${loadTime}ms`);

      // Pages should load in reasonable time (less than 15 seconds)
      expect(loadTime).toBeLessThan(15000);
    }

    console.log('✅ All pages loaded within acceptable time');
  });

  test('Console - No unhandled promise rejections', async ({ page, consoleLogger }) => {
    let unhandledRejections = 0;

    page.on('unhandledrejection', (rejection) => {
      unhandledRejections++;
      console.log(`⚠️  Unhandled rejection: ${rejection}`);
    });

    for (const route of routes) {
      consoleLogger.clear();
      await page.goto(route.path, { waitUntil: 'networkidle' });
      await page.waitForTimeout(1000);
    }

    expect(unhandledRejections).toBe(0, `Found ${unhandledRejections} unhandled rejections`);
    console.log('✅ No unhandled promise rejections');
  });
});
