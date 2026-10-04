import { test, expect } from '../fixtures/app.fixture';
import type { Page } from '@playwright/test';

/**
 * UI-U1/U2 — Library core contract, authenticated against the live app.
 * Credentials come from the global auth fixture (runtime env only).
 */

const rows = (page: Page) => page.getByRole('button', { name: /Open .* attempt/ });

test.describe('Library home (desktop)', () => {
  test('A: / lands in the Library', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/dives/);
    await expect(page.getByRole('heading', { name: 'Library', level: 1 })).toBeVisible();
  });

  test('navigation is Library-first and hides operational harnesses', async ({ page }) => {
    test.skip((page.viewportSize()?.width ?? 0) < 1024, 'desktop sidebar assertions');
    await page.goto('/dives');
    // Library is present as the primary destination
    await expect(page.getByRole('link', { name: 'Library' }).first()).toBeVisible();
    // P5 canary harness and the Competitions alias are not normal navigation
    await expect(page.getByRole('link', { name: 'Player canary' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Competitions' })).toHaveCount(0);
    // Operational destinations live behind the Operations disclosure
    await expect(page.getByRole('link', { name: 'Media recall' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Operations' }).click();
    await expect(page.getByRole('link', { name: 'Media recall' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'System' })).toBeVisible();
  });

  test('B: search opens a playable clip reader', async ({ page }) => {
    await page.goto('/dives?scope=all');
    await page.getByRole('textbox', { name: 'Search dives' }).fill('103');
    const firstCard = rows(page).first();
    await expect(firstCard).toBeVisible();
    await firstCard.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('video').first()).toBeVisible();
  });

  test('C: Back after the review loop restores the exact Library context', async ({ page }) => {
    await page.goto('/dives?scope=all&view=list');
    await expect(rows(page).first()).toBeVisible();
    const showMore = page.getByRole('button', { name: 'Show 48 more attempts' });
    await showMore.click();
    await showMore.click();
    await expect(rows(page).first()).toBeVisible();
    const rowsBefore = await rows(page).count();
    expect(rowsBefore).toBeGreaterThanOrEqual(96);

    await page.evaluate(() => window.scrollTo(0, 4000));
    await page.waitForTimeout(300);
    const scrollBefore = await page.evaluate(() => window.scrollY);
    expect(scrollBefore).toBeGreaterThan(1000);

    // Click the row under the viewport center: a locator click would trigger
    // Playwright's scroll-into-view, moving the scroll anchor before the
    // reader even opens.
    const point = await page.evaluate(() => {
      const el = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
      const btn = el && el.closest('button[aria-label*="attempt"]');
      if (!btn) return null;
      const r = btn.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    expect(point).not.toBeNull();
    await page.mouse.click(point!.x, point!.y);
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    expect(page.url()).toContain('clip=');
    const historyAfterOpen = await page.evaluate(() => window.history.length);

    await dialog.getByRole('button', { name: 'Next' }).click();
    await expect(dialog).toBeVisible();
    const urlAfterNext = page.url();
    await dialog.getByRole('button', { name: 'Next' }).click();
    const urlAfterNext2 = page.url();
    await dialog.getByRole('button', { name: 'Previous' }).click();
    await expect(dialog).toBeVisible();
    expect(page.url()).toBe(urlAfterNext);
    const historyAfterMoves = await page.evaluate(() => window.history.length);
    expect(historyAfterMoves).toBe(historyAfterOpen);

    await page.goBack();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const search = new URL(page.url()).search;
    expect(search).toContain('scope=all');
    expect(search).toContain('view=list');
    expect(search).not.toContain('clip=');
    await page.waitForTimeout(400);
    const rowsAfter = await rows(page).count();
    expect(rowsAfter).toBe(rowsBefore);
    const scrollAfter = await page.evaluate(() => window.scrollY);
    console.log('SCROLL before=', scrollBefore, 'after=', scrollAfter);
    expect(Math.abs(scrollAfter - scrollBefore)).toBeLessThanOrEqual(80);
  });

  test('D: reloading a clip URL reopens the reader', async ({ page }) => {
    await page.goto('/dives?scope=all');
    await rows(page).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const clipUrl = page.url();
    await page.reload();
    await expect(page.getByRole('dialog')).toBeVisible();
    expect(page.url()).toBe(clipUrl);
  });

  test('E: secondary and operational routes remain reachable', async ({ page }) => {
    for (const route of [
      '/dashboard',
      '/journey',
      '/analytics',
      '/sessions',
      '/media/representatives',
      '/media/recall',
      '/admin',
    ]) {
      const response = await page.goto(route);
      expect(response?.ok(), `${route} should respond OK`).toBeTruthy();
      await expect(page.getByText('Page not found')).toHaveCount(0);
    }
    // Hidden operational harness (kept reachable, not normal navigation)
    await page.goto('/media/p5-canary');
    await expect(page.getByText('Page not found')).toHaveCount(0);
    // Obsolete alias: compatibility redirect preserves the query string
    await page.goto('/competitions?scope=all');
    await expect(page).toHaveURL(/\/journey\?scope=all/);
    await expect(page.getByText('Page not found')).toHaveCount(0);
  });

  test('unknown URLs get a usable recovery page', async ({ page }) => {
    await page.goto('/nonexistent-route-xyz');
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Back to Library' })).toBeVisible();
  });
});

test.describe('Library on mobile (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('F: Library is the obvious home and the review loop works', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/dives/);
    await expect(page.getByRole('heading', { name: 'Library', level: 1 })).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    // Drawer does not expose the hidden destinations
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await expect(page.getByRole('link', { name: 'Player canary' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Competitions' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Close navigation' }).click();

    await page.getByRole('textbox', { name: 'Search dives' }).fill('103');
    await rows(page).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    await page.goBack();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(new URL(page.url()).search).toContain('q=103');
    expect(new URL(page.url()).search).not.toContain('clip=');
  });
});
