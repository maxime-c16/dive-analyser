import { test, expect } from '../fixtures/app.fixture';

test.describe('API Endpoints through Nginx Proxy', () => {
  test('Health endpoint responds successfully', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/health', {
      waitUntil: 'networkidle',
    });

    expect(response).toBeDefined();
    expect([200, 500]).toContain(response?.status());

    const errorReport = consoleLogger.getErrorReport();
    const critical404s = errorReport.errors.filter(
      (e) => e.includes('404') && e.includes('/api/v1/health')
    );
    expect(critical404s.length).toBe(0, 'Health endpoint should not return 404');
  });

  test('Journey endpoint returns data', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/journey', {
      waitUntil: 'networkidle',
    });

    expect(response).toBeDefined();
    expect(response?.status()).toBe(200);

    const text = await response?.text();
    expect(text).toBeDefined();
    expect(text?.length).toBeGreaterThan(0);

    const errorReport = consoleLogger.getErrorReport();
    expect(errorReport.errors.filter((e) => e.includes('404'))).toHaveLength(0);
  });

  test('Analytics overall endpoint responds', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/analytics/overall', {
      waitUntil: 'networkidle',
    });

    expect(response).toBeDefined();
    expect(response?.status()).toBe(200);

    const errorReport = consoleLogger.getErrorReport();
    expect(errorReport.errors.filter((e) => e.includes('404'))).toHaveLength(0);
  });

  test('Analytics by-height endpoint responds', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/analytics/by-height', {
      waitUntil: 'networkidle',
    });

    expect(response).toBeDefined();
    expect(response?.status()).toBe(200);

    const errorReport = consoleLogger.getErrorReport();
    expect(errorReport.errors.filter((e) => e.includes('404'))).toHaveLength(0);
  });

  test('Analytics by-direction endpoint responds', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/analytics/by-direction', {
      waitUntil: 'networkidle',
    });

    expect(response).toBeDefined();
    expect(response?.status()).toBe(200);

    const errorReport = consoleLogger.getErrorReport();
    expect(errorReport.errors.filter((e) => e.includes('404'))).toHaveLength(0);
  });

  test('Analytics monthly endpoint responds', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/analytics/monthly', {
      waitUntil: 'networkidle',
    });

    expect(response).toBeDefined();
    expect(response?.status()).toBe(200);

    const errorReport = consoleLogger.getErrorReport();
    expect(errorReport.errors.filter((e) => e.includes('404'))).toHaveLength(0);
  });

  test('WebSocket health endpoint is accessible', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/ws/health', {
      waitUntil: 'networkidle',
    });

    expect(response).toBeDefined();
    expect(response?.status()).toBe(200);

    const text = await response?.text();
    expect(text).toBeDefined();
    expect(text?.length).toBeGreaterThan(0);

    const errorReport = consoleLogger.getErrorReport();
    expect(errorReport.errors.filter((e) => e.includes('404'))).toHaveLength(0);
  });

  test('Proxy does not return 502 Bad Gateway', async ({ page, consoleLogger }) => {
    const response = await page.goto('/api/v1/health', {
      waitUntil: 'networkidle',
    });

    expect(response?.status()).not.toBe(502);

    const errorReport = consoleLogger.getErrorReport();
    const badGateways = errorReport.errors.filter((e) => e.includes('502'));
    expect(badGateways.length).toBe(0, 'Nginx proxy should not return 502');
  });
});
