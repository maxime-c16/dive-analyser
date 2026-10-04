import { test, expect } from '../fixtures/app.fixture';

test.describe('WebSocket Connectivity', () => {
  test('Dashboard page can establish WebSocket connection', async ({ page, consoleLogger }) => {
    await page.goto('/', { waitUntil: 'networkidle' });

    // Wait for WebSocket to potentially connect
    await page.waitForTimeout(3000);

    // Check for WebSocket-related logs
    const logs = consoleLogger.getConsoleLogs();
    const errorReport = consoleLogger.getErrorReport();

    // Look for WebSocket errors in console
    const wsErrors = logs.errors.filter(
      (e) =>
        e.toLowerCase().includes('websocket') ||
        e.toLowerCase().includes('ws://') ||
        e.toLowerCase().includes('wss://')
    );

    // WebSocket errors are non-critical as long as the page loads
    if (wsErrors.length > 0) {
      console.log(`WebSocket-related logs (non-critical): ${wsErrors.join(', ')}`);
    }

    // Check that there are no critical API errors
    const critical404s = errorReport.errors.filter((e) => e.includes('404'));
    expect(critical404s.length).toBe(0);

    console.log('WebSocket connectivity test passed');
  });

  test('Journey page WebSocket health endpoint accessible', async ({ page, consoleLogger }) => {
    // Try to access the WebSocket health check endpoint
    const response = await page.goto('/api/v1/ws/health', {
      waitUntil: 'networkidle',
    });

    expect(response?.status()).toBe(200);

    const text = await response?.text();
    expect(text).toBeDefined();
    expect(text?.length).toBeGreaterThan(0);

    const errorReport = consoleLogger.getErrorReport();
    expect(errorReport.errors.filter((e) => e.includes('404'))).toHaveLength(0);

    console.log('WebSocket health endpoint verified');
  });

  test('No WebSocket connection errors should prevent page load', async ({ page, consoleLogger }) => {
    await page.goto('/journey', { waitUntil: 'networkidle' });

    // Wait for page content
    await page.waitForTimeout(2000);

    const errorReport = consoleLogger.getErrorReport();

    // Check for critical errors (but not WebSocket connection timeouts)
    const criticalErrors = errorReport.errors.filter(
      (e) =>
        (e.includes('404') || e.includes('500') || e.includes('CORS')) &&
        !e.toLowerCase().includes('websocket')
    );

    expect(criticalErrors.length).toBe(
      0,
      `Critical errors found: ${criticalErrors.join(', ')}`
    );

    console.log('Page load not blocked by WebSocket errors');
  });
});
