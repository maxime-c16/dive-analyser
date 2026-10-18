import { test, expect, type Browser, type Page } from "@playwright/test";
import { strings } from "../../src/calendar/strings";

// Task04 live flows (weekly series, scoped edits, camps) on a real backend and
// a DISPOSABLE database seeded with the dev accounts and the reviewed KCPM
// import. Gated by env; credentials are never committed.
const PASSWORD = process.env.CALENDAR_LIVE_PASSWORD;
test.skip(!PASSWORD, "CALENDAR_LIVE_PASSWORD not set (live run only)");
test.describe.configure({ mode: "serial" });

const t = strings.fr;
const shots = "/tmp/calendar-task04-live-shots";
const iso = (d: Date) => d.toISOString().slice(0, 10);
const plus = (day: string, n: number) => { const d = new Date(`${day}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
// First Tuesday at least two days ahead: every scoped edit targets future sessions.
const FIRST = (() => { let d = plus(iso(new Date()), 2); while (new Date(`${d}T12:00:00Z`).getUTCDay() !== 2) d = plus(d, 1); return d; })();
const UNTIL = plus(FIRST, 35);
const HOLIDAY = plus(FIRST, 7);
const TITLE = "Séance technique hebdo";
const form = (p: Page) => p.locator("form.calendar-form");

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

async function openSession(page: Page, day: string) {
  await page.goto(`/calendar?date=${day}`);
  const row = page.locator(".calendar-agenda .calendar-event").filter({ hasText: TITLE }).first();
  await row.click({ timeout: 20_000 }).catch(async (error) => {
    console.log("openSession", day, page.url(), (await page.locator(".calendar-page").innerText()).slice(-500));
    throw error;
  });
  await expect(page.getByRole("heading", { level: 1, name: TITLE })).toBeVisible();
}

test("coach creates a weekly series on a phone with a holiday excluded (first tap saves)", async ({ browser }) => {
  const coach = await session(browser, "coach", 390);
  await coach.goto(`/calendar/new?date=${FIRST}`);
  await form(coach).getByLabel(t.calendarField).selectOption({ label: "Débutants" });
  await form(coach).getByLabel(t.typeField).selectOption("training");
  await form(coach).getByLabel(t.audienceField).selectOption("group");
  await form(coach).getByLabel(t.titleField).fill(TITLE);
  await form(coach).getByLabel(t.startDate).fill(FIRST);
  await form(coach).getByLabel(t.start, { exact: true }).fill("19:00");
  await form(coach).getByLabel(t.end, { exact: true }).fill("20:30");
  await form(coach).getByLabel(t.repeatWeekly).check();
  await expect(coach.getByRole("button", { name: "mar", exact: true })).toHaveAttribute("aria-pressed", "true");
  await form(coach).getByLabel(t.seasonEnd).fill(UNTIL);
  await form(coach).getByLabel(t.excludedDates).fill(HOLIDAY);
  await coach.getByRole("button", { name: t.addDate }).click();
  await expect(coach.getByText(t.sessionCount(5))).toBeVisible();
  await form(coach).getByLabel(t.venue).fill("SNMT");
  await form(coach).getByLabel(t.venue).focus();
  await coach.screenshot({ path: `${shots}/coach-create-series-390.png`, fullPage: true });
  await coach.getByRole("button", { name: t.save }).click(); // direct first tap with a focused field
  await expect(coach).toHaveURL(/\/calendar\/o\/\d+/);
  await expect(coach.getByText(/Chaque mar, 19:00–20:30/)).toBeVisible();
  const listed = await coach.evaluate(async ([from, to, title]) => {
    const r = await fetch(`/api/v1/calendar/occurrences?from=${from}T00:00:00Z&to=${to}T00:00:00Z&limit=200`);
    return (await r.json()).items.filter((o: { event: { title: string } }) => o.event.title === title)
      .map((o: { local_date: string; local_start: string }) => `${o.local_date} ${o.local_start}`);
  }, [FIRST, plus(UNTIL, 1), TITLE]);
  expect(listed).toEqual([0, 14, 21, 28, 35].map((n) => `${plus(FIRST, n)} 19:00`)); // same wall time across the clock change
});

test("member marks interest; coach previews 'this and following' weekday change and responses follow", async ({ browser }) => {
  const third = plus(FIRST, 14);
  const alice = await session(browser, "alice", 375);
  await openSession(alice, third);
  await alice.getByRole("button", { name: t.interested }).click();
  await expect(alice.getByRole("button", { name: t.interested })).toHaveAttribute("aria-pressed", "true");

  const coach = await session(browser, "coach", 1280, 900);
  await openSession(coach, third);
  await coach.getByRole("link", { name: t.editSchedule }).click();
  await expect(coach.getByRole("radio", { name: new RegExp(t.scope_future) })).toBeChecked();
  await coach.getByRole("button", { name: "mar", exact: true }).click();
  await coach.getByRole("button", { name: "mer", exact: true }).click();
  await form(coach).getByLabel(t.seasonEnd).fill(plus(UNTIL, 1));
  await coach.getByRole("button", { name: t.previewChanges }).click();
  const preview = coach.locator(".calendar-preview");
  await expect(preview.getByRole("heading", { name: new RegExp(t.previewMoved) })).toBeVisible();
  await expect(preview.getByText(t.responseCounts(1, 0, 0))).toBeVisible();
  await expect(preview.getByText(t.responsesKept(1))).toBeVisible();
  await coach.screenshot({ path: `${shots}/coach-preview-future-1280.png`, fullPage: true });
  await coach.getByRole("button", { name: t.applyChanges }).click();
  await expect(coach).toHaveURL(/\/calendar\/o\/\d+(\?|$)/);
  await expect(coach.getByText(/Chaque mer/)).toBeVisible();

  await openSession(alice, plus(third, 1));
  await expect(alice.getByText(/^mercredi \d+ \S+ \d{4} · 19:00–20:30$/)).toBeVisible();
  await expect(alice.getByRole("button", { name: t.interested })).toHaveAttribute("aria-pressed", "true");
  await alice.screenshot({ path: `${shots}/alice-moved-keeps-interest-375.png`, fullPage: true });
});

test("a stale preview is refused and the inputs stay", async ({ browser }) => {
  const a = await session(browser, "coach", 1280, 900);
  const b = await session(browser, "manager", 390); // one live session per account: a second publisher
  for (const page of [a, b]) {
    await openSession(page, plus(FIRST, 22));
    await page.getByRole("link", { name: t.editSchedule }).click();
    await page.getByRole("radio", { name: new RegExp(t.scope_all) }).check();
  }
  await form(a).getByLabel(t.start, { exact: true }).fill("18:30");
  await form(a).getByLabel(t.end, { exact: true }).fill("20:00");
  await a.getByRole("button", { name: t.previewChanges }).click();
  await form(b).getByLabel(t.start, { exact: true }).fill("17:45");
  await form(b).getByLabel(t.end, { exact: true }).fill("19:15");
  await b.getByRole("button", { name: t.previewChanges }).click();
  await a.getByRole("button", { name: t.applyChanges }).click();
  await expect(a).toHaveURL(/\/calendar\/o\/\d+(\?|$)/);
  await b.getByRole("button", { name: t.applyChanges }).click();
  await expect(b.getByRole("alert")).toHaveText(t.stalePreview);
  await expect(form(b).getByLabel(t.start, { exact: true })).toHaveValue("17:45");
  await b.screenshot({ path: `${shots}/coach-stale-preview-390.png`, fullPage: true });
});

test("imported KCPM sessions only allow single-session changes, with a plain explanation", async ({ browser }) => {
  const coach = await session(browser, "coach", 390);
  await coach.goto("/calendar?date=2026-10-01");
  await coach.locator(".calendar-agenda .calendar-event").filter({ hasText: "Entraînement" }).first().click();
  await coach.getByRole("link", { name: t.editSchedule }).click();
  await expect(coach.getByText(t.importedSeries)).toBeVisible();
  await expect(coach.getByRole("radio")).toHaveCount(1);
  await coach.screenshot({ path: `${shots}/coach-imported-only-one-390.png`, fullPage: true });
});

const BLOCKS: [string, string, string, string][] = [
  ["2027-02-19", "18:00", "21:00", "INSEP"],
  ["2027-02-20", "10:00", "13:00", "INSEP"],
  ["2027-02-20", "15:00", "18:00", "INSEP"],
  ["2027-02-21", "09:00", "12:00", "Centre Aquatique Olympique, Saint-Denis"],
  ["2027-02-21", "15:00", "18:00", "Centre Aquatique Olympique, Saint-Denis"],
];

test("coach enters the real February camp on a phone; month view spans 19–21 February", async ({ browser }) => {
  const coach = await session(browser, "coach", 390);
  await coach.goto("/calendar/new?date=2027-02-19");
  await form(coach).getByLabel(t.calendarField).selectOption({ label: "Kingfisher Club Plongeon Montreuil" });
  await form(coach).getByLabel(t.typeField).selectOption("camp");
  await form(coach).getByLabel(t.audienceField).selectOption("club");
  await form(coach).getByLabel(t.titleField).fill("Stage février KCPM");
  await form(coach).getByLabel(t.allDay).check();
  await form(coach).getByLabel(t.startDate, { exact: true }).fill("2027-02-19");
  await form(coach).getByLabel(t.endDate).fill("2027-02-21");
  for (const [i, [day, start, end, venue]] of BLOCKS.entries()) {
    await coach.getByRole("button", { name: t.addBlock }).click();
    const block = coach.locator(".calendar-itinerary-block").nth(i);
    await block.getByLabel(t.blockDay).fill(day);
    await block.getByLabel(t.start).fill(start);
    await block.getByLabel(t.end).fill(end);
    await block.getByLabel(t.venue).fill(venue);
  }
  await form(coach).getByLabel(t.registrationLink).fill(
    "https://www.helloasso.com/associations/kingfisher-club-plongeon-montreuil-kingfisher-plongeon-montreuil/evenements/stage-fevrier-2027-kcpm");
  await coach.getByRole("button", { name: t.save }).click();
  await expect(coach).toHaveURL(/\/calendar\/o\/\d+/);
  await expect(coach.getByText(/vendredi 19 février 2027 – dimanche 21 février 2027 · 3 jours/)).toBeVisible();
  await expect(coach.locator(".calendar-itinerary li")).toHaveCount(5);
  await expect(coach.getByText(t.registrationNote)).toBeVisible();
  await coach.screenshot({ path: `${shots}/coach-camp-detail-390.png`, fullPage: true });

  const alice = await session(browser, "alice", 1280, 900);
  await alice.goto("/calendar?date=2027-02-01&view=month");
  for (const day of ["19", "20", "21"]) {
    await expect(alice.locator(".calendar-month > div").filter({ has: alice.getByRole("button", { name: new RegExp(`^\\S+ ${Number(day)} février`) }) })
      .getByRole("link", { name: /Stage février KCPM/ })).toBeVisible();
  }
  await expect(alice.locator(".calendar-month a", { hasText: "Stage février KCPM" })).toHaveCount(3);
  await alice.screenshot({ path: `${shots}/alice-month-camp-1280.png`, fullPage: true });
  await alice.locator(".calendar-month a", { hasText: "Stage février KCPM" }).nth(1).click();
  await alice.getByRole("button", { name: t.interested }).click();
  await expect(alice.getByRole("button", { name: t.interested })).toHaveAttribute("aria-pressed", "true");
});
