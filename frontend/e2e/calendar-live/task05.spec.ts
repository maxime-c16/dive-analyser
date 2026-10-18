import { test, expect, type Browser, type Page } from "@playwright/test";

// Task05 live checks on a real backend and a DISPOSABLE database where the
// seed ran the alerts worker: alice has a delivered change alert for her
// group session; una's invitation alert was delivered, then the invitation
// was revoked (read-time redaction). Credentials are never committed.
const PASSWORD = process.env.CALENDAR_LIVE_PASSWORD;
test.skip(!PASSWORD, "CALENDAR_LIVE_PASSWORD not set (live run only)");
test.describe.configure({ mode: "serial" });

const shots = "/tmp/calendar-task05-live-shots";
const open: Page[] = [];
test.afterEach(async () => { for (const page of open.splice(0)) await page.context().close(); });

async function session(browser: Browser, who: string, width: number, height = 844): Promise<Page> {
  const context = await browser.newContext({ viewport: { width, height }, locale: "fr-FR",
    isMobile: width < 768, hasTouch: width < 768 });
  const page = await context.newPage();
  open.push(page);
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(`${who}@dev.test`);
  await page.locator('input[type="password"]').fill(PASSWORD!);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  return page;
}

test("phone: the change alert explains what moved and opens the session", async ({ browser }) => {
  const alice = await session(browser, "alice", 390);
  await alice.goto("/notifications");
  const card = alice.getByRole("article", { name: "Événement modifié · Entraînement Débutants" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Déplacé :");
  await expect(card).toContainText("20:00");
  await expect(card).toContainText("Nouveau lieu : Piscine Maurice Thorez");
  await alice.screenshot({ path: `${shots}/phone-inbox-change.png`, fullPage: true });
  await card.getByRole("link", { name: "Ouvrir l’événement" }).tap();
  await expect(alice).toHaveURL(/\/calendar\/o\/\d+$/);
  await expect(alice.getByRole("heading", { level: 1, name: "Entraînement Débutants" })).toBeVisible();
  await expect(alice.locator("text=Piscine Maurice Thorez >> visible=true").first()).toBeVisible();
  await alice.screenshot({ path: `${shots}/phone-deep-link-session.png`, fullPage: true });
});

test("phone: a revoked invitation alert is redacted and has no link", async ({ browser }) => {
  const una = await session(browser, "una", 390);
  await una.goto("/notifications");
  await expect(una.getByText("Cette notification d’agenda ne vous est plus accessible.")).toBeVisible();
  await expect(una.getByText("Sortie fosse Villeneuve")).toHaveCount(0);
  await expect(una.getByRole("link", { name: "Ouvrir l’événement" })).toHaveCount(0);
  await una.screenshot({ path: `${shots}/phone-inbox-redacted.png`, fullPage: true });
  // A guessed deep link stays unavailable for her.
  await una.goto("/calendar/o/2");
  await expect(una.getByText("Sortie fosse Villeneuve")).toHaveCount(0);
});

test("desktop: calendar alert preferences are listed and saved", async ({ browser }) => {
  const alice = await session(browser, "alice", 1280, 900);
  await alice.goto("/account");
  await alice.getByRole("button", { name: "Notifications" }).click();
  const section = alice.getByRole("region", { name: "Agenda" });
  await expect(section).toBeVisible();
  const group = section.getByRole("switch", { name: "Rappel pour chaque séance du groupe" });
  await expect(group).toBeEnabled();
  await expect(group).toHaveAttribute("aria-checked", "false");
  await expect(section.getByRole("switch", { name: "Changements et annulations" })).toHaveAttribute("aria-checked", "true");
  await group.click();
  await expect(group).toHaveAttribute("aria-checked", "true");
  await alice.screenshot({ path: `${shots}/desktop-account-calendar-prefs.png`, fullPage: true });
  await alice.reload();
  await alice.getByRole("button", { name: "Notifications" }).click();
  await expect(alice.getByRole("region", { name: "Agenda" })
    .getByRole("switch", { name: "Rappel pour chaque séance du groupe" })).toHaveAttribute("aria-checked", "true");
});

test("desktop: the change alert deep link works with a pointer too", async ({ browser }) => {
  const alice = await session(browser, "alice", 1280, 900);
  await alice.goto("/notifications");
  await alice.getByRole("link", { name: "Ouvrir l’événement" }).click();
  await expect(alice).toHaveURL(/\/calendar\/o\/\d+$/);
  await expect(alice.getByRole("heading", { level: 1, name: "Entraînement Débutants" })).toBeVisible();
  await alice.screenshot({ path: `${shots}/desktop-deep-link-session.png`, fullPage: true });
});
