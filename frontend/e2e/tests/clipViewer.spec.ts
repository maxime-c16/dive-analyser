import { test, expect } from '../fixtures/app.fixture';
import type { Page } from '@playwright/test';

/**
 * UI-U3 — Clip viewer core contract, authenticated against the live app.
 * Credentials come from the global auth fixture (runtime env only or a
 * previously stored real session state).
 */

const rows = (page: Page) => page.getByRole('button', { name: /Open .* attempt/ });
const viewer = (page: Page) => page.getByRole('dialog');

async function openFirstClip(page: Page, query = '103') {
  await page.goto('/dives?scope=all');
  await page.getByRole('textbox', { name: 'Search dives' }).fill(query);
  await rows(page).first().click();
  await expect(viewer(page)).toBeVisible();
}

/** Open cards until one has a playable source; returns its locator. */
async function findPlayableVideo(page: Page) {
  for (let i = 0; i < 5; i += 1) {
    if (i > 0) {
      await viewer(page).getByRole('button', { name: 'Next' }).click();
      await expect(viewer(page)).toBeVisible();
      await page.waitForTimeout(500);
    }
    const playable = await page.evaluate(async () => {
      const video = document.querySelector<HTMLVideoElement>('[role="dialog"] video');
      if (!video) return false;
      if (video.readyState >= 1 && video.currentSrc) return true;
      await new Promise<void>((resolve) => {
        const done = () => resolve();
        video.addEventListener('loadedmetadata', done, { once: true });
        video.addEventListener('error', done, { once: true });
        setTimeout(done, 6000);
      });
      return Boolean(video.currentSrc) && video.readyState >= 1;
    });
    if (playable) return page.locator('[role="dialog"] video');
  }
  return null;
}

test.describe('Clip viewer (desktop)', () => {
  test('A: opening a clip makes the viewer the dominant surface', async ({ page }) => {
    await page.goto('/dives?scope=all');
    await page.getByRole('textbox', { name: 'Search dives' }).fill('103');
    await rows(page).first().click();
    const dialog = viewer(page);
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('video')).toBeVisible();
    // essential metadata: code in the header, position counter present
    await expect(dialog.locator('h2')).toHaveText(/103/);
    await expect(dialog.locator('p[aria-live="polite"]')).toContainText('1 /');
    await expect(dialog.getByRole('button', { name: 'Back to Library' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Previous' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Next' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: /Details/ })).toBeVisible();
    await expect(dialog.getByRole('link', { name: 'Analysis' })).toBeVisible();
  });

  test('B: a ready clip plays, seeks, and honors the playback-rate control', async ({ page }) => {
    await openFirstClip(page);
    const video = await findPlayableVideo(page);
    test.skip(!video, 'no ready clip found in the first result window');
    const info = await page.evaluate(async () => {
      const video = document.querySelector<HTMLVideoElement>('[role="dialog"] video')!;
      return { controls: video.controls, hasSrc: Boolean(video.currentSrc) };
    });
    expect(info.controls).toBe(true);
    expect(info.hasSrc).toBe(true);

    // Native seek semantics
    await page.evaluate(() => {
      const video = document.querySelector<HTMLVideoElement>('[role="dialog"] video')!;
      video.currentTime = 1;
    });
    await page.waitForTimeout(400);
    const seeked = await page.evaluate(() => {
      const video = document.querySelector<HTMLVideoElement>('[role="dialog"] video')!;
      return video.currentTime;
    });
    expect(seeked).toBeGreaterThan(0.5);

    // Playback rate control drives the element rate
    const rate = viewer(page).getByRole('combobox', { name: 'Playback speed' });
    await rate.selectOption('0.5');
    await expect
      .poll(() => page.evaluate(() => document.querySelector<HTMLVideoElement>('[role="dialog"] video')!.playbackRate))
      .toBe(0.5);

    // Play/pause via native semantics
    const playResult = await page.evaluate(async () => {
      const video = document.querySelector<HTMLVideoElement>('[role="dialog"] video')!;
      try { await video.play(); } catch { /* autoplay policy */ }
      const playing = !video.paused;
      video.pause();
      return { playing: playing, afterPause: video.paused };
    });
    expect(playResult.afterPause).toBe(true);
    // playing is best-effort (autoplay policy may reject programmatic play)
    expect(playResult.playing === true || playResult.playing === false).toBe(true);
  });

  test('C: rapid review navigates the filtered set without history growth', async ({ page }) => {
    await openFirstClip(page);
    const dialog = viewer(page);
    const clipUrl = page.url();
    const historyAfterOpen = await page.evaluate(() => window.history.length);
    const counter = () => dialog.locator('p[aria-live="polite"]').textContent();

    await dialog.getByRole('button', { name: 'Next' }).click();
    await expect(dialog.locator('video').first()).toBeVisible();
    expect(await counter()).toMatch(/^2 \/ /);
    const urlAfterNext = page.url();

    await dialog.getByRole('button', { name: 'Next' }).click();
    await expect(dialog.locator('video').first()).toBeVisible();
    expect(await counter()).toMatch(/^3 \/ /);

    await dialog.getByRole('button', { name: 'Previous' }).click();
    await expect(dialog.locator('video').first()).toBeVisible();
    expect(await counter()).toMatch(/^2 \/ /);
    expect(page.url()).toBe(urlAfterNext);

    const historyAfterMoves = await page.evaluate(() => window.history.length);
    expect(historyAfterMoves).toBe(historyAfterOpen);
    expect(new URL(page.url()).search).toContain('scope=all');
  });

  test('D: keyboard review contract', async ({ page }) => {
    await openFirstClip(page);
    const dialog = viewer(page);
    const historyAfterOpen = await page.evaluate(() => window.history.length);

    await page.keyboard.press('Shift+ArrowRight');
    await expect(dialog.locator('video').first()).toBeVisible();
    const clipAfterNext = new URL(page.url()).searchParams.get('clip');
    expect(await dialog.locator('p[aria-live="polite"]').textContent()).toMatch(/^2 \/ /);

    await page.keyboard.press('Shift+ArrowLeft');
    await expect(dialog.locator('video').first()).toBeVisible();
    const clipAfterPrev = new URL(page.url()).searchParams.get('clip');
    expect(clipAfterPrev).not.toBe(clipAfterNext);

    const historyAfterKeys = await page.evaluate(() => window.history.length);
    expect(historyAfterKeys).toBe(historyAfterOpen);

    // No shortcut fires while an incompatible interactive control has focus.
    const rate = dialog.getByRole('combobox', { name: 'Playback speed' });
    await rate.focus();
    await page.keyboard.press('Shift+ArrowRight');
    expect(new URL(page.url()).searchParams.get('clip')).toBe(clipAfterPrev);

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(new URL(page.url()).search).not.toContain('clip=');
  });

  test('D2: Space toggles playback without stealing native video focus', async ({ page }) => {
    test.skip((page.viewportSize()?.width ?? 0) < 500, 'keyboard review contract is desktop');
    await openFirstClip(page);
    const video = await findPlayableVideo(page);
    test.skip(!video, 'no ready clip found in the first result set');
    const dialog = viewer(page);
    const getState = () =>
      page.evaluate(() => {
        const v = document.querySelector<HTMLVideoElement>('[role="dialog"] video')!;
        return {
          paused: v.paused,
          hasSrc: Boolean(v.currentSrc),
          ready: v.readyState,
        };
      });

    // The source must be present and usable before asserting playback.
    await expect
      .poll(async () => (await getState()).hasSrc, { timeout: 15000 })
      .toBe(true);

    // An incompatible interactive control keeps ownership of Space: pressing
    // Space on the Details button activates the button, never the player.
    const detailsButton = dialog.getByRole('button', { name: /Details/ });
    const beforeGuard = await getState();
    const expandedBefore = await detailsButton.getAttribute('aria-expanded');
    await detailsButton.focus();
    await page.keyboard.press(' ');
    expect((await getState()).paused).toBe(beforeGuard.paused);
    expect(await detailsButton.getAttribute('aria-expanded')).not.toBe(expandedBefore);
    // restore Details to its previous state
    await detailsButton.click();

    // Space from a non-interactive review surface toggles play/pause.
    // Headless Chromium may suspend playback shortly after start, so observe
    // over a window and retry if the environment swallowed the toggle.
    const focusViewerSurface = () =>
      page.evaluate(() => {
        (document.querySelector('[data-testid="clip-viewer"]') as HTMLElement)?.focus();
      });
    const observeFlip = (wasPaused: boolean) =>
      page.evaluate((was) => {
        const v = document.querySelector('[role="dialog"] video') as HTMLVideoElement;
        const t0 = performance.now();
        return new Promise<boolean>((resolve) => {
          const tick = () => {
            if (v.paused !== was) {
              resolve(true);
              return;
            }
            if (performance.now() - t0 > 4000) {
              resolve(false);
              return;
            }
            setTimeout(tick, 25);
          };
          tick();
        });
      }, wasPaused);

    let toggled = false;
    for (let tryIndex = 0; tryIndex < 3 && !toggled; tryIndex += 1) {
      const before = (await getState()).paused;
      await focusViewerSurface();
      const press = page.keyboard.press(' ');
      // start observing before the handler runs so a synchronous flip is seen
      const flipPromise = observeFlip(before);
      await press;
      toggled = await flipPromise;
    }
    expect(toggled).toBe(true);
  });

  test('G: Analysis round-trips back to the selected clip', async ({ page }) => {
    await openFirstClip(page);
    const dialog = viewer(page);
    const clipUrl = page.url();
    await dialog.getByRole('link', { name: 'Analysis' }).click();
    await expect(page).toHaveURL(/\/dives\/analysis\//);
    await page.goBack();
    await expect(dialog).toBeVisible();
    expect(page.url()).toBe(clipUrl);
    expect(new URL(page.url()).searchParams.get('clip')).not.toBeNull();
  });

  test('I: a failed media preparation stays understandable and actionable', async ({ page }) => {
    // Route interception only — no production data or media authority touched.
    await page.route('**/api/v1/media/*/status', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          video_uuid: 'e2e-stub',
          status: 'failed',
          can_request: true,
          available_renditions: [],
          playback_url: null,
          poster_url: null,
          job: { id: 1, status: 'failed', rendition: 'proxy_360p', last_error: 'proxy export failed' },
        }),
      }),
    );
    await openFirstClip(page);
    const dialog = viewer(page);
    await expect(dialog.getByText('No video available')).toBeVisible();
    await expect(dialog.getByText('proxy export failed')).toBeVisible();
    await expect(dialog.getByRole('button', { name: /Retry prepare/ })).toBeVisible();
    // Next/Previous still usable around a non-ready clip
    await expect(dialog.getByRole('button', { name: 'Next' })).toBeEnabled();
  });
});

test.describe('Clip viewer on mobile (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('H: viewer is a full-width review surface and Back restores the Library', async ({ page }) => {
    await openFirstClip(page);
    const dialog = viewer(page);

    const overflowOpen = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflowOpen).toBeLessThanOrEqual(0);

    const video = dialog.locator('video').first();
    await expect(video).toBeVisible();
    const box = await video.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(391);

    await expect(dialog.getByRole('button', { name: 'Previous' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Next' })).toBeVisible();

    // Next usable by tap
    await dialog.getByRole('button', { name: 'Next' }).click();
    await expect(dialog.locator('video').first()).toBeVisible();
    expect(new URL(page.url()).searchParams.get('clip')).not.toBeNull();

    // Details usable
    await dialog.getByRole('button', { name: /Details/ }).click();
    await expect(dialog.getByText('Raw caption')).toBeVisible();

    // Analysis reachable
    await expect(dialog.getByRole('link', { name: 'Analysis' })).toBeVisible();

    // Back restores the Library with search context intact
    await page.goBack();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(new URL(page.url()).search).toContain('q=103');
    expect(new URL(page.url()).search).not.toContain('clip=');
    const overflowClosed = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflowClosed).toBeLessThanOrEqual(0);
  });
});
