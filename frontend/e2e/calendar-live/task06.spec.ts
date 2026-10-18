import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

const password = process.env.CALENDAR_LIVE_PASSWORD;
const occurrence = process.env.CALENDAR_LIVE_OCCURRENCE;
const camp = process.env.CALENDAR_LIVE_CAMP;
test.skip(!password || !occurrence || !camp, "Disposable Task06 seed required");

test("phone deep link survives login and downloads an authenticated snapshot", async ({ browser }) => {
  test.skip(process.env.CALENDAR_LIVE_OFF === "true", "Feature-on run only");
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "fr-FR" });
  try {
    const page = await context.newPage();
    await page.goto(`/calendar/o/${occurrence}`);
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await page.locator('input[type="email"]').fill("alice@example.test");
    await page.locator('input[type="password"]').fill(password!);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(new RegExp(`/calendar/o/${occurrence}$`));
    await expect(page.getByRole("heading", { name: "Groupe A training", exact: true })).toBeVisible();
    await expect(page.getByText(/Les fichiers téléchargés ne se mettent pas à jour/)).toBeVisible();
    const downloaded = page.waitForEvent("download");
    await page.getByRole("link", { name: "Télécharger cet événement (.ics)" }).tap();
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe(`calendar-${occurrence}.ics`);
    const bytes = await fs.readFile((await download.path())!);
    expect(bytes.toString()).toContain("BEGIN:VEVENT\r\n");
    expect(bytes.toString()).toContain("SUMMARY:Groupe A training");
    await fs.mkdir("/tmp/calendar-task06-live-shots", { recursive: true });
    await page.screenshot({ path: "/tmp/calendar-task06-live-shots/phone-export.png", fullPage: true });
    const denied = await context.request.get(`/api/v1/calendar/occurrences/${process.env.CALENDAR_LIVE_HIDDEN}/export.ics`);
    expect(denied.status()).toBe(404);
    await page.goto(`/calendar/o/${camp}`);
    await expect(page.getByRole("heading", { name: "Stage février KCPM", exact: true })).toBeVisible();
    await expect(page.getByText("INSEP", { exact: false }).first()).toBeVisible();
    const ics = await context.request.get(`/api/v1/calendar/occurrences/${camp}/export.ics`);
    expect(ics.headers()["cache-control"]).toBe("private, no-store");
    expect(await ics.text()).toContain("DTSTART;VALUE=DATE:20270219\r\nDTEND;VALUE=DATE:20270222");
    await page.screenshot({ path: "/tmp/calendar-task06-live-shots/phone-camp.png", fullPage: true });
  } finally { await context.close(); }
});

test("feature off preserves four mobile targets and refuses export", async ({ browser }) => {
  test.skip(process.env.CALENDAR_LIVE_OFF !== "true", "Run against flag-off disposable backend");
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, locale: "en-US" });
  try {
    const page = await context.newPage();
    await page.goto("/login");
    await page.locator('input[type="email"]').fill("alice@example.test");
    await page.locator('input[type="password"]').fill(password!);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL((url) => !url.pathname.startsWith("/login"));
    await page.goto(`/calendar/o/${occurrence}`);
    await expect(page).toHaveURL(/\/dives$/);
    await expect(page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link")).toHaveCount(4);
    await expect(page.getByRole("link", { name: "Calendar", exact: true })).toHaveCount(0);
    const response = await context.request.get(`/api/v1/calendar/occurrences/${occurrence}/export.ics`);
    expect(response.status()).toBe(404);
    await page.goto("/register");
    await expect(page.getByLabel(/Club/)).toHaveCount(0);
  } finally { await context.close(); }
});

test("desktop downloads the cancelled camp with its original UID", async ({ browser }) => {
  test.skip(process.env.CALENDAR_LIVE_OFF === "true" || process.env.CALENDAR_LIVE_CANCELLED !== "true", "Cancelled camp snapshot run only");
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "en-US" });
  try {
    const page = await context.newPage();
    await page.goto("/login");
    await page.locator('input[type="email"]').fill("coach@example.test");
    await page.locator('input[type="password"]').fill(password!);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL((url) => !url.pathname.startsWith("/login"));
    await page.goto(`/calendar/o/${camp}`);
    await expect(page.getByRole("heading", { name: "Stage février KCPM", exact: true })).toBeVisible();
    const pending = page.waitForEvent("download");
    await page.getByRole("link", { name: "Download this event (.ics)" }).click();
    const download = await pending;
    const text = await fs.readFile((await download.path())!, "utf8");
    expect(text).toContain(`UID:calendar-occurrence-${camp}@dive-analyser`);
    expect(text).toContain("STATUS:CANCELLED\r\n");
    await page.screenshot({ path: "/tmp/calendar-task06-live-shots/desktop-cancelled-export.png", fullPage: true });
  } finally { await context.close(); }
});
