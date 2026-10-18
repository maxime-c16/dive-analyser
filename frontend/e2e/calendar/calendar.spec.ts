import { test, expect } from "@playwright/test";
test.beforeEach(async ({ page }) => {
  await page.route("**/__calendar_local/training", (route) =>
    route.fulfill({
      json: ["beginners", "advanced"].flatMap((group) =>
        Array.from({ length: 6 }, (_, i) => ({
          source_key: `synthetic:${group}:${i}`,
          local_date: `2026-09-${String(8 + i).padStart(2, "0")}`,
          start_local: "18:30",
          end_local: "20:30",
          timezone: "Europe/Paris",
          venue_code: "TEST",
          group_key: group,
        })),
      ),
    }),
  );
});
const entry =
  "/e2e/fixtures/navigation-review.html?path=/calendar&lang=en&unread=1";
const nav = (page: any) => page.locator(".mobile-tab-bar");
const route = (page: any, path: string) =>
  page.evaluate((p: string) => (window as any).reviewRouter.navigate(p), path);
for (const width of [320, 375, 390, 430])
  test(`${width}px accessible five icons, unread and month`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(entry);
    await expect(
      page.getByRole("heading", { name: "Calendar", exact: true }),
    ).toBeVisible();
    await expect(nav(page).getByRole("link")).toHaveCount(5);
    await expect(
      nav(page).getByRole("link", { name: "Calendar", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect(
      nav(page).getByRole("link", { name: /Messages/ }),
    ).toHaveAccessibleName(/12/);
    const rects = await nav(page)
      .locator("a")
      .evaluateAll((els) =>
        els.map((e) => ({
          w: e.getBoundingClientRect().width,
          h: e.getBoundingClientRect().height,
        })),
      );
    for (const r of rects) {
      expect(r.w).toBeGreaterThan(48);
      expect(r.h).toBeGreaterThanOrEqual(48);
    }
    expect(
      Math.max(...rects.map((r) => r.w)) - Math.min(...rects.map((r) => r.w)),
    ).toBeLessThan(1);
    await page.getByRole("button", { name: "Month", exact: true }).click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `/tmp/calendar-task01-${width}.png`,
      fullPage: true,
    });
  });
test("assigned groups, direct detail guard, absence distinct from interest, URL and back", async ({
  page,
}) => {
  await page.goto(entry);
  await route(page, "/calendar?date=2026-09-01&role=beginners");
  await expect(page.locator(".calendar-event")).toHaveCount(6);
  await page.locator(".calendar-event").first().click();
  await page.getByRole("button", { name: "Interested", exact: true }).click();
  await page
    .getByRole("button", { name: "Report absence", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Remove interest", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByText("Absence reported", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Remove absence report", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Remove interest", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("link", { name: "Back to calendar" }).click();
  await expect(page.locator(".calendar-event")).toHaveCount(6);
  await page.locator(".calendar-controls summary").click();
  await page
    .getByRole("combobox", { name: "Fixture role / assigned group" })
    .selectOption("unassigned");
  await expect(page.locator(".calendar-event")).toHaveCount(0);
  await route(page, "/calendar/synthetic%3Abeginners%3A0?role=unassigned");
  await expect(page.getByRole("alert")).toHaveText(
    "Event unavailable for this fixture role.",
  );
  await route(page, "/calendar?role=coach&date=2026-09-01");
  expect(await page.locator(".calendar-event").count()).toBeGreaterThan(6);
});
test("create validation preserves input, edit keeps interest, cancellation and resources", async ({
  page,
}) => {
  await page.goto(entry);
  await page
    .getByRole("button", { name: "Create sample outing", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Title", exact: true })
    .fill("My local outing");
  await page.getByRole("button", { name: "Save sample", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Title", exact: true }),
  ).toHaveValue("My local outing");
  await page
    .getByRole("textbox", { name: "Venue", exact: true })
    .fill("Test pool");
  await page.getByRole("button", { name: "Save sample", exact: true }).click();
  await page.getByRole("button", { name: "Interested", exact: true }).click();
  await page.getByRole("button", { name: "Edit outing", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Venue", exact: true })
    .fill("Changed pool");
  await page.getByRole("button", { name: "Save sample", exact: true }).click();
  await expect(page.getByText(/Time or venue changed/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove interest", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page
    .getByRole("button", { name: "Cancel outing", exact: true })
    .click();
  await expect(
    page
      .locator(".calendar-detail")
      .getByRole("status")
      .filter({ hasText: /^Cancelled$/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove interest", exact: true }),
  ).toBeDisabled();
  await route(page, "/calendar/meet-demo");
  await expect(
    page.getByText("Competition resources · sample only"),
  ).toBeVisible();
  await expect(
    page.getByText("Dive sheets — Unverified · needs review"),
  ).toBeVisible();
});
test("keyboard, large text, landscape and shell overlay replacement", async ({
  page,
}) => {
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto(entry);
  await page.evaluate(() => (document.documentElement.style.fontSize = "32px"));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("link", { name: "Calendar", exact: true })
    .last()
    .focus();
  await expect(
    nav(page).getByRole("link", { name: "Calendar", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(
    nav(page).getByRole("link", { name: "Calendar", exact: true }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Account navigation" }).click();
  await expect(nav(page)).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(nav(page)).toBeVisible();
});

test("compact filters, date jump and directional month motion respect reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto(entry);
  await route(page, "/calendar?date=2026-09-01");
  await expect(page.locator(".calendar-event")).toHaveCount(6);
  await page.getByRole("group", { name: "Source", exact: true }).getByRole("button", { name: "Outings", exact: true }).click();
  await expect(page.locator(".calendar-event")).toHaveCount(0);
  await page.getByRole("button", { name: "All", exact: true }).click();
  await page.getByRole("searchbox").fill("missing venue");
  await expect(page.locator(".calendar-event")).toHaveCount(0);
  await page.getByRole("searchbox").fill("");
  await page.locator(".calendar-date-jump summary").click();
  await page.getByLabel("Date", { exact: true }).fill("2026-09-10");
  await expect(page.locator(".calendar-event")).toHaveCount(4);
  await page.locator(".calendar-date-jump summary").click();
  await page.getByRole("button", { name: "Next month", exact: true }).click();
  await expect(page.getByRole("heading", { name: "October 2026" })).toBeVisible();
  await expect(page.locator(".calendar-period")).toHaveCSS("animation-name", "calendar-next");
  await page.getByRole("button", { name: "Previous month", exact: true }).click();
  await expect(page.getByRole("heading", { name: "September 2026" })).toBeVisible();
  await expect(page.locator(".calendar-period")).toHaveCSS("animation-name", "calendar-previous");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Next month", exact: true }).click();
  await expect(page.locator(".calendar-period")).toHaveCSS("animation-name", "none");
});
