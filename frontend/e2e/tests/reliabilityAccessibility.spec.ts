import { test, expect } from '../fixtures/app.fixture';
import type { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * UI-U4/U5 — reliability, mobile and accessibility contract, authenticated
 * against the app. Failure scenarios use route interception only; no
 * production data or media authority is touched. Session identity comes
 * from the shared storageState fixture (no login performed here).
 */

type DiveRecord = {
  id: number;
  dive_code: string;
  video_uuid: string | null;
};

async function fetchDives(page: Page): Promise<DiveRecord[]> {
  const response = await page.request.get(
    '/api/v1/dives?limit=5000&exclude_lineup=true&diver_scope=all',
  );
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as DiveRecord[];
}

async function fetchStatus(page: Page, uuid: string): Promise<string> {
  const response = await page.request.get(`/api/v1/media/${uuid}/status`);
  if (!response.ok()) return 'unknown';
  const data = (await response.json()) as { status?: string };
  return data.status ?? 'unknown';
}

/** Deep-link straight into a clip's viewer (URL contract: clip=<attempt-id>). */
async function openClipById(page: Page, id: number) {
  await page.goto(`/dives?scope=all&clip=${id}`);
  await expect(page.getByRole('dialog')).toBeVisible();
}

function viewer(page: Page) {
  return page.getByRole('dialog');
}

/** Keyboard-only focus traversal: press Tab until the predicate matches.
 *  The predicate runs in the page and must be self-contained. */
async function tabUntil(
  page: Page,
  predicate: () => boolean,
  maxTabs = 40,
) {
  for (let i = 0; i < maxTabs; i += 1) {
    await page.keyboard.press('Tab');
    if (await page.evaluate(predicate)) return;
  }
  const stuck = await page.evaluate(
    () =>
      (document.activeElement as HTMLElement | null)?.outerHTML?.slice(0, 120) ??
      'none',
  );
  throw new Error(`tabUntil: focus target not reached; stuck at: ${stuck}`);
}

const CRITICAL_SERIOUS = ['critical', 'serious'];

async function axeScan(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .disableRules('region') // breadcrumb strip is intentionally outside nav landmarks
    .analyze();
  const blocking = results.violations.filter((violation) =>
    CRITICAL_SERIOUS.includes(violation.impact ?? ''),
  );
  if (results.violations.length > 0) {
    console.log(
      `[axe:${label}]`,
      JSON.stringify(
        results.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          nodes: v.nodes.length,
        })),
      ),
    );
  }
  expect(blocking, `${label}: critical/serious violations`).toEqual([]);
}

test.describe('Media status transport failures (desktop)', () => {
  test('D: initial status failure exits loading into an actionable retry state', async ({ page }) => {
    const dives = await fetchDives(page);
    const target = dives.find((dive) => dive.video_uuid);
    test.skip(!target, 'no attempt with linked media available');
    await page.route(`**/api/v1/media/${target!.video_uuid}/status`, (route) =>
      route.abort('connectionfailed'),
    );
    await openClipById(page, target!.id);
    const dialog = viewer(page);
    // The bounded initial retry window (~2s) must terminate in a clear,
    // actionable state — never an endless spinner.
    await expect(
      dialog.getByRole('alert').getByText(/Couldn.t check media availability/),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      dialog.getByRole('button', { name: 'Retry status check' }),
    ).toBeVisible();
    await expect(dialog.locator('.ops-running-icon')).toHaveCount(0);
  });

  test('E: a transient poll failure preserves the last known state, recovery clears it', async ({ page }) => {
    const dives = await fetchDives(page);
    const target = dives.find((dive) => dive.video_uuid);
    test.skip(!target, 'no attempt with linked media available');
    const start = Date.now();
    await page.route(`**/api/v1/media/${target!.video_uuid}/status`, (route) => {
      const elapsed = Date.now() - start;
      if (elapsed > 5000 && elapsed < 11_000) {
        return route.abort('connectionfailed');
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          video_uuid: target!.video_uuid,
          status: 'transcoding',
          can_request: false,
          available_renditions: [],
          playback_url: null,
          poster_url: null,
          job: { id: 1, status: 'transcoding', rendition: 'proxy_360p' },
        }),
      });
    });
    await openClipById(page, target!.id);
    const dialog = viewer(page);
    await expect(
      dialog.getByRole('status').getByText(/Preparing media: transcoding/),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      dialog.getByText(/transcoding — connection interrupted/),
    ).toBeVisible({ timeout: 15_000 });
    // Fresh status success clears the stale indication.
    await expect(
      dialog.getByText(/Preparing media: transcoding/),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      dialog.getByText(/connection interrupted/),
    ).toHaveCount(0);
  });

  test('F: repeated poll failures stop the automatic loop and offer a manual retry', async ({ page }) => {
    test.setTimeout(120_000);
    const dives = await fetchDives(page);
    const target = dives.find((dive) => dive.video_uuid);
    test.skip(!target, 'no attempt with linked media available');
    const start = Date.now();
    let statusRequests = 0;
    await page.route(`**/api/v1/media/${target!.video_uuid}/status`, (route) => {
      statusRequests += 1;
      const elapsed = Date.now() - start;
      if (elapsed > 5000 && elapsed < 25_000) {
        return route.abort('connectionfailed');
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          video_uuid: target!.video_uuid,
          status: 'transcoding',
          can_request: false,
          available_renditions: [],
          playback_url: null,
          poster_url: null,
          job: { id: 1, status: 'transcoding', rendition: 'proxy_360p' },
        }),
      });
    });
    await openClipById(page, target!.id);
    const dialog = viewer(page);
    await expect(
      dialog.getByText(/status checks stopped/),
    ).toBeVisible({ timeout: 40_000 });
    await expect(
      dialog.getByRole('button', { name: 'Check status again' }),
    ).toBeVisible();
    // The automatic error loop must be stopped — no further status traffic.
    const requestsAtStop = statusRequests;
    await page.waitForTimeout(8_000);
    expect(statusRequests).toBe(requestsAtStop);
  });

  test('F2: Check status again re-checks without creating a preparation job', async ({ page }) => {
    test.setTimeout(120_000);
    const dives = await fetchDives(page);
    const target = dives.find((dive) => dive.video_uuid);
    test.skip(!target, 'no attempt with linked media available');
    let failFromMs = Number.POSITIVE_INFINITY;
    let prepareRequests = 0;
    await page.route(`**/api/v1/media/${target!.video_uuid}/status`, (route) => {
      if (Date.now() >= failFromMs) {
        return route.abort('connectionfailed');
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          video_uuid: target!.video_uuid,
          status: 'transcoding',
          can_request: false,
          available_renditions: [],
          playback_url: null,
          poster_url: null,
          job: { id: 1, status: 'transcoding', rendition: 'proxy_360p' },
        }),
      });
    });
    await page.route(`**/api/v1/media/${target!.video_uuid}/request`, (route) => {
      prepareRequests += 1;
      return route.fulfill({ status: 500, body: '{}' });
    });
    await openClipById(page, target!.id);
    const dialog = viewer(page);
    // Initial check must succeed first; transport failures then hit polling.
    await expect(
      dialog.getByText(/Preparing media: transcoding/),
    ).toBeVisible({ timeout: 10_000 });
    failFromMs = Date.now();
    await expect(
      dialog.getByRole('button', { name: 'Check status again' }),
    ).toBeVisible({ timeout: 40_000 });
    failFromMs = Number.POSITIVE_INFINITY; // deterministic recovery
    await dialog.getByRole('button', { name: 'Check status again' }).click();
    // Status check recovers (window elapsed) — preparation was never POSTed.
    await expect(
      dialog.getByText(/Preparing media: transcoding/),
    ).toBeVisible({ timeout: 15_000 });
    expect(prepareRequests).toBe(0);
  });
});

test.describe('Library reliability (desktop)', () => {
  test('G: a failed Library load offers Retry, preserves URL filters, and refetches', async ({ page }) => {
    let divesCalls = 0;
    await page.route(/\/api\/v1\/dives\?/, (route) => {
      divesCalls += 1;
      if (divesCalls === 1) return route.fulfill({ status: 500, body: '{}' });
      return route.continue();
    });
    await page.goto('/dives?scope=all&height=3m');
    const alert = page.getByRole('alert');
    await expect(alert).toContainText('The dive library could not be loaded.');
    // The failed request must not destroy the URL filter state.
    expect(new URL(page.url()).searchParams.get('height')).toBe('3m');
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(alert).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: /Open .* attempt/ }).first(),
    ).toBeVisible();
    expect(new URL(page.url()).searchParams.get('height')).toBe('3m');
  });
});

test.describe('Viewer focus containment (desktop)', () => {
  test('C: Tab/Shift+Tab stay within the viewer; close returns to the originating card', async ({ page }) => {
    test.setTimeout(90_000);
    test.skip(
      test.info().project.name === 'mobile-chromium',
      'Desktop keyboard-loop contract; the mobile loop is validated with touch semantics in the mobile describes.',
    );
    const dives = await fetchDives(page);
    const target = dives.find((dive) => dive.video_uuid);
    test.skip(!target, 'no attempt with linked media available');
    await page.goto('/dives?scope=all');
    await page.getByRole('textbox', { name: 'Search dives' }).fill(target!.dive_code.slice(0, 3));
    const card = page.locator(`[data-attempt-id="${target!.id}"]`).first();
    await card.click();
    const dialog = viewer(page);
    await expect(dialog).toBeVisible();
    // Repeated Tab cycles must never escape into the inert background.
    for (let i = 0; i < 14; i += 1) {
      await page.keyboard.press('Tab');
      const inside = await page.evaluate(
        () =>
          document
            .querySelector<HTMLElement>('[role="dialog"]')
            ?.contains(document.activeElement) ?? false,
      );
      expect(inside, `Tab #${i} escaped the viewer`).toBe(true);
    }
    for (let i = 0; i < 4; i += 1) {
      await page.keyboard.press('Shift+Tab');
      const inside = await page.evaluate(
        () =>
          document
            .querySelector<HTMLElement>('[role="dialog"]')
            ?.contains(document.activeElement) ?? false,
      );
      expect(inside, `Shift+Tab #${i} escaped the viewer`).toBe(true);
    }
    // The background Library must not be keyboard-reachable.
    const backgroundInert = await page.evaluate(() => {
      const card = document.querySelector<HTMLElement>('[data-attempt-id]');
      return card ? card.closest('[inert]') !== null : false;
    });
    expect(backgroundInert).toBe(true);
    await page.keyboard.press('Escape');
    // Under heavy main-thread load (many card thumbnails) the close commit
    // can take several seconds; the close itself must still happen.
    await expect(dialog).toHaveCount(0, { timeout: 30_000 });
    await expect(card).toBeFocused({ timeout: 10_000 });
  });
});

test.describe('Keyboard-only core review loop (desktop)', () => {
  test('B: skip link, search, open, navigate, details, close — no pointer, no background leakage', async ({ page }) => {
    test.skip(
      test.info().project.name === 'mobile-chromium',
      'Desktop keyboard-loop contract; mobile-emulated Tab traversal through native selects is not representative. Mobile loop validated in the mobile describes.',
    );
    await page.goto('/dives?scope=all');
    const skipLink = page.getByRole('link', { name: 'Skip to main content' });
    await expect(skipLink).toBeVisible();
    // Skip link is the first focusable element and moves focus to main.
    await page.keyboard.press('Tab');
    await expect(skipLink).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('main')).toBeFocused();
    // Keyboard into the search field.
    await tabUntil(page, () => (document.activeElement as HTMLElement | null)?.getAttribute('aria-label') === 'Search dives');
    await expect(page.getByRole('textbox', { name: 'Search dives' })).toBeFocused();
    await page.keyboard.type('103');
    // The result grid renders after the library fetch; wait for it before
    // keyboard traversal.
    await expect(
      page.getByRole('button', { name: /Open .* attempt/ }).first(),
    ).toBeVisible({ timeout: 20_000 });
    // Tab to the first result card and open it.
    await tabUntil(page, () => (document.activeElement as HTMLElement | null)?.dataset?.attemptId !== undefined);
    await page.keyboard.press('Enter');
    const dialog = viewer(page);
    await expect(dialog).toBeVisible();
    const openClipUrl = new URL(page.url()).searchParams.get('clip');
    // Next / Previous via the frozen U3 shortcuts.
    await page.keyboard.press('Shift+ArrowRight');
    await expect(dialog.getByText(/^2 \/ \d+$/)).toBeVisible();
    expect(new URL(page.url()).searchParams.get('clip')).not.toBe(openClipUrl);
    await page.keyboard.press('Shift+ArrowLeft');
    await expect(dialog.getByText(/^1 \/ \d+$/)).toBeVisible();
    // Details toggle via keyboard.
    await dialog.getByRole('button', { name: /Details/ }).focus();
    await page.keyboard.press('Enter');
    await expect(dialog.getByRole('button', { name: /Details/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    await page.keyboard.press('Enter');
    await expect(dialog.getByRole('button', { name: /Details/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    // Close returns focus to the originating card.
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              (document.activeElement as HTMLElement | null)?.dataset
                ?.attemptId ?? null,
          ),
        { timeout: 5_000 },
      )
      .not.toBeNull();
  });
});

test.describe('Reduced motion (desktop)', () => {
  test('H: app-owned loading animation is disabled while the review loop stays usable', async ({ page }) => {
    test.setTimeout(60_000);
    // Context-level reducedMotion emulation is unreliable in this browser
    // build; the runtime API is equivalent and verified by the probe.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const dives = await fetchDives(page);
    const target = dives.find((dive) => dive.video_uuid);
    test.skip(!target, 'no attempt with linked media available');
    await page.route(`**/api/v1/media/${target!.video_uuid}/status`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          video_uuid: target!.video_uuid,
          status: 'transcoding',
          can_request: false,
          available_renditions: [],
          playback_url: null,
          poster_url: null,
          job: { id: 1, status: 'transcoding', rendition: 'proxy_360p' },
        }),
      }),
    );
    await openClipById(page, target!.id);
    const dialog = viewer(page);
    await expect(
      dialog.getByText(/Preparing media: transcoding/),
    ).toBeVisible();
    // The spinner element renders but does not animate under reduced motion.
    const animationName = await page.evaluate(() => {
      const icon = document.querySelector<HTMLElement>('.ops-running-icon');
      return icon ? getComputedStyle(icon).animationName : 'none';
    });
    expect(animationName).toBe('none');
    // The state remains understandable and the loop remains usable.
    await expect(dialog.getByRole('button', { name: 'Back to Library' })).toBeVisible();
    await dialog.getByRole('button', { name: 'Back to Library' }).click();
    await expect(dialog).toHaveCount(0);
  });
});

test.describe('Narrow mobile reflow (~320px)', () => {
  test.use({ viewport: { width: 320, height: 700 }, isMobile: true, hasTouch: true });

  test('J: Library and Viewer have no unintended horizontal overflow and keep critical controls', async ({ page }) => {
    await page.goto('/dives?scope=all');
    await expect(
      page.getByRole('button', { name: /Open .* attempt/ }).first(),
    ).toBeVisible();
    const libraryOverflow = await page.evaluate(
      () => document.scrollingElement!.scrollWidth,
    );
    expect(libraryOverflow).toBeLessThanOrEqual(320);
    await page.getByRole('button', { name: /Open .* attempt/ }).first().click();
    const dialog = viewer(page);
    await expect(dialog).toBeVisible();
    const viewerOverflow = await page.evaluate(
      () => document.scrollingElement!.scrollWidth,
    );
    expect(viewerOverflow).toBeLessThanOrEqual(320);
    for (const name of ['Back to Library', 'Previous', 'Next', /Details/]) {
      await expect(dialog.getByRole('button', { name }).first()).toBeVisible();
    }
    await expect(dialog.getByRole('combobox', { name: 'Playback speed' })).toBeVisible();
    await dialog.getByRole('button', { name: 'Back to Library' }).click();
    await expect(dialog).toHaveCount(0);
  });
});

test.describe('Mobile landscape (844x390)', () => {
  test.use({ viewport: { width: 844, height: 390 }, isMobile: true, hasTouch: true });

  test('K: critical review controls remain reachable in landscape', async ({ page }) => {
    await page.goto('/dives?scope=all');
    await page.getByRole('button', { name: /Open .* attempt/ }).first().click();
    const dialog = viewer(page);
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('video').first()).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Back to Library' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Previous' }).first()).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Next' }).first()).toBeVisible();
    await expect(dialog.getByRole('combobox', { name: 'Playback speed' })).toBeVisible();
    await dialog.getByRole('button', { name: 'Back to Library' }).click();
    await expect(dialog).toHaveCount(0);
  });
});

test.describe('Automated accessibility (axe core)', () => {
  test('L: Library, ready viewer, error viewer and mobile viewer have no critical/serious violations', async ({ page }) => {
    await page.goto('/dives?scope=all');
    await expect(
      page.getByRole('button', { name: /Open .* attempt/ }).first(),
    ).toBeVisible();
    await axeScan(page, 'library');

    // Ready viewer state (natural valid production state, read-only lookup).
    const dives = await fetchDives(page);
    let readyClip: DiveRecord | null = null;
    for (const dive of dives.filter((d) => d.video_uuid).slice(0, 12)) {
      const status = await fetchStatus(page, dive.video_uuid!);
      if (status === 'ready') {
        readyClip = dive;
        break;
      }
    }
    if (readyClip) {
      await openClipById(page, readyClip.id);
      await expect(viewer(page).locator('video').first()).toBeVisible();
      await axeScan(page, 'viewer-ready');
      await viewer(page).getByRole('button', { name: 'Back to Library' }).click();
    } else {
      test.info().annotations.push({
        type: 'note',
        description: 'no ready clip found; viewer-ready axe scan skipped',
      });
    }

    // Non-ready/error viewer state via route interception only.
    const anyClip = dives.find((dive) => dive.video_uuid);
    test.skip(!anyClip, 'no attempt with linked media available');
    await page.route(`**/api/v1/media/${anyClip!.video_uuid}/status`, (route) =>
      route.abort('connectionfailed'),
    );
    await openClipById(page, anyClip!.id);
    await expect(
      viewer(page).getByRole('alert').getByText(/Couldn.t check media availability/),
    ).toBeVisible({ timeout: 10_000 });
    await axeScan(page, 'viewer-error');
  });

  test('L2: mobile viewer has no critical/serious violations', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/dives?scope=all');
    await page.getByRole('button', { name: /Open .* attempt/ }).first().click();
    await expect(viewer(page)).toBeVisible();
    await axeScan(page, 'viewer-mobile-390');
  });
});
