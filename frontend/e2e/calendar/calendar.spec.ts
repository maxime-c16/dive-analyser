import { test, expect, type Page, type Route } from "@playwright/test";

// Browser contract tests for the production calendar UI. The calendar API is
// served by an in-test fake (synthetic data, no private schedules) that
// mimics the server's visibility, version and idempotency rules. The real
// server rules are proven by backend/tests/test_calendar_task03.py and the
// live two-account run (e2e/calendar-live).

type Who = "beginners" | "coach" | "unassigned";
type Occ = { id: number; event: number; date: string; start: string | null; end: string | null; venue: string; status: string; version: number; interest: string | null; absent: boolean };
type Ev = { id: number; title: string; kind: "group" | "club" | "personal"; group: number | null; type: string; audience: string; status: string; version: number; can_edit: boolean; following: boolean; changed: boolean };

function fake(page: Page, who: Who) {
  const events: Ev[] = [
    { id: 1, title: "Entraînement — Débutants", kind: "group", group: 1, type: "training", audience: "group", status: "published", version: 1, can_edit: who === "coach", following: false, changed: false },
    { id: 2, title: "Entraînement — Confirmés", kind: "group", group: 2, type: "training", audience: "group", status: "published", version: 1, can_edit: who === "coach", following: false, changed: false },
  ];
  const occs: Occ[] = [];
  let next = 100;
  for (const ev of [1, 2]) for (let i = 0; i < 6; i++)
    occs.push({ id: next++, event: ev, date: `2026-09-${String(8 + i).padStart(2, "0")}`, start: "18:30", end: "20:30", venue: "TEST", status: "scheduled", version: 1, interest: null, absent: false });
  const keys = new Map<string, number>();
  const state = { creates: 0, failNextCreateResponse: false, staleNextPatch: false };
  const visible = (e: Ev) => e.kind !== "group" || who === "coach" || (who === "beginners" && e.group === 1);
  const evOf = (o: Occ) => events.find((e) => e.id === o.event)!;
  const occOut = (o: Occ) => {
    const e = evOf(o);
    return { id: o.id, occurrence_key: `k${o.id}`, status: o.status, is_all_day: false, starts_at: null, ends_at: null, start_date: null, end_date: null,
      venue_name: o.venue, version: o.version, my_interest: o.interest, my_absence_reported: o.absent, local_date: o.date, local_start: o.start, local_end: o.end,
      imported: e.kind === "group",
      event: { id: e.id, calendar_id: e.id, calendar_kind: e.kind, club_id: e.kind === "personal" ? null : 1, event_type: e.type, audience: e.audience, status: e.status,
        title: e.title, timezone: "Europe/Paris", version: e.version, calendar_name: e.kind === "group" ? (e.group === 1 ? "Débutants" : "Confirmés") : "Mes sorties", training_group_id: e.group } };
  };
  const changes = (e: Ev) => (e.changed ? [{ kind: "venue_changed", at: "2026-09-01T10:00:00Z", fields: ["venue_name"] }] : []);
  const occDetail = (o: Occ) => ({ ...occOut(o), resources: [], description: "", venue_address: null, map_url: null, can_edit: evOf(o).can_edit,
    can_report_absence: who === "beginners" && evOf(o).group === 1, following: evOf(o).following, my_invitation: null, organizer_name: null, changes: changes(evOf(o)) });
  const evDetail = (e: Ev) => ({ ...occOut(occs.find((o) => o.event === e.id)!).event, description: "", venue_name: null, venue_address: null, map_url: null,
    organizer_user_id: null, organizer_name: null, my_invitation: null, resources: [], following: e.following, can_edit: e.can_edit, changes: changes(e),
    occurrences: occs.filter((o) => o.event === e.id).map(occOut) });
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { "Cache-Control": "no-store" } });
  page.route("**/api/v1/calendar/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace("/api/v1/calendar", "");
    const method = req.method();
    const body = req.postData() ? JSON.parse(req.postData()!) : {};
    let m: RegExpMatchArray | null;
    if (path === "/me") return json(route, { clubs: [{ club: { id: 1, slug: "kcpm", name: "KCPM Montreuil", short_name: "KCPM", timezone: "Europe/Paris" },
      membership: { id: 1, role: who === "coach" ? "coach" : "member", can_publish: who === "coach", can_assign_groups: who === "coach", source: "signup" },
      group: who === "beginners" ? { id: 1, club_id: 1, slug: "a", name: "Débutants" } : null, self_declared: who !== "coach" }] });
    if (path === "/calendars") return json(route, { items: [{ id: 50, kind: "club", name: "KCPM", club_id: 1, training_group_id: null, following: false, can_publish: who === "coach", allowed_audiences: who === "coach" ? ["club", "community", "invited"] : [] }] });
    if (path === "/occurrences" && method === "GET") {
      const from = url.searchParams.get("from")!.slice(0, 10), to = url.searchParams.get("to")!.slice(0, 10);
      return json(route, { items: occs.filter((o) => visible(evOf(o)) && o.date >= from && o.date < to).map(occOut), next_cursor: null });
    }
    if ((m = path.match(/^\/occurrences\/(\d+)$/)) && method === "GET") {
      const o = occs.find((x) => x.id === Number(m![1]));
      return o && visible(evOf(o)) ? json(route, occDetail(o)) : json(route, { detail: "Occurrence not found" }, 404);
    }
    if ((m = path.match(/^\/occurrences\/(\d+)\/(interest|absence)$/))) {
      const o = occs.find((x) => x.id === Number(m![1]))!;
      if (m[2] === "interest") o.interest = body.state; else o.absent = body.absent;
      return json(route, occDetail(o));
    }
    if ((m = path.match(/^\/occurrences\/(\d+)\/dives$/))) return json(route, { items: [] });
    if ((m = path.match(/^\/events\/(\d+)$/)) && method === "GET") {
      const e = events.find((x) => x.id === Number(m![1]));
      return e && visible(e) ? json(route, evDetail(e)) : json(route, { detail: "Event not found" }, 404);
    }
    if ((m = path.match(/^\/events\/(\d+)\/follow$/))) {
      events.find((x) => x.id === Number(m![1]))!.following = method === "PUT";
      return route.fulfill({ status: 204 });
    }
    if ((m = path.match(/^\/events\/(\d+)\/invitations$/))) return json(route, { items: [] });
    if (path === "/events" && method === "POST") {
      const key = req.headers()["idempotency-key"];
      const existing = keys.get(key);
      if (existing) return json(route, evDetail(events.find((e) => e.id === existing)!));
      state.creates++;
      const id = 10 + state.creates;
      events.push({ id, title: body.title, kind: "personal", group: null, type: body.event_type, audience: body.audience, status: "published", version: 1, can_edit: true, following: false, changed: false });
      const [date, start] = body.when.start_local.split("T");
      occs.push({ id: 500 + id, event: id, date, start, end: body.when.end_local.split("T")[1], venue: body.venue_name ?? "", status: "scheduled", version: 1, interest: null, absent: false });
      keys.set(key, id);
      if (state.failNextCreateResponse) { state.failNextCreateResponse = false; return route.abort("connectionreset"); }
      return json(route, evDetail(events.find((e) => e.id === id)!), 201);
    }
    if ((m = path.match(/^\/events\/(\d+)$/)) && method === "PATCH") {
      const e = events.find((x) => x.id === Number(m![1]))!;
      if (state.staleNextPatch || body.expected_version !== e.version) {
        state.staleNextPatch = false;
        return json(route, { detail: { code: "stale_version", message: "changed" } }, 409);
      }
      const o = occs.find((x) => x.event === e.id)!;
      if (body.venue_name !== undefined && body.venue_name !== o.venue) { o.venue = body.venue_name; e.changed = true; }
      if (body.title) e.title = body.title;
      e.version++;
      return json(route, evDetail(e));
    }
    if ((m = path.match(/^\/events\/(\d+)\/cancel$/))) {
      const e = events.find((x) => x.id === Number(m![1]))!;
      e.status = "cancelled"; e.version++;
      return json(route, evDetail(e));
    }
    return json(route, { detail: "unhandled in fake" }, 500);
  });
  return state;
}

const entry = (query = "") => `/e2e/fixtures/navigation-review.html?path=${encodeURIComponent("/calendar?date=2026-09-01" + query)}&lang=en&unread=1`;
const nav = (page: Page) => page.locator(".mobile-tab-bar");
const go = (page: Page, path: string) => page.evaluate((p: string) => (window as any).reviewRouter.navigate(p), path);

for (const width of [320, 375, 390, 430]) {
  test(`${width}px: five accessible icons, unread, agenda and month without overflow`, async ({ page }) => {
    fake(page, "beginners");
    await page.setViewportSize({ width, height: 844 });
    await page.goto(entry());
    await expect(page.locator(".calendar-event")).toHaveCount(6);
    await expect(nav(page).getByRole("link")).toHaveCount(5);
    await expect(nav(page).getByRole("link", { name: "Calendar", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(nav(page).getByRole("link", { name: /Messages/ })).toHaveAccessibleName(/12/);
    const rects = await nav(page).locator("a").evaluateAll((els) => els.map((e) => e.getBoundingClientRect()).map((r) => ({ w: r.width, h: r.height })));
    for (const r of rects) { expect(r.w).toBeGreaterThan(48); expect(r.h).toBeGreaterThanOrEqual(48); }
    expect(Math.max(...rects.map((r) => r.w)) - Math.min(...rects.map((r) => r.w))).toBeLessThan(1);
    await page.getByRole("button", { name: "Month", exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `/tmp/calendar-task03-${width}.png`, fullPage: true });
  });
}

test("feature off keeps four labelled tabs and /calendar falls back to the Library", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/e2e/fixtures/navigation-review.html?path=/calendar&lang=en&calendar=off`);
  await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();
  await expect(nav(page).getByRole("link")).toHaveCount(4);
  await expect(nav(page).getByRole("link", { name: "Library" }).locator("span").last()).toBeVisible();
});

test("member sees own group only; interest and absence are independent; direct id to other group is unavailable", async ({ page }) => {
  fake(page, "beginners");
  await page.goto(entry());
  await expect(page.locator(".calendar-event")).toHaveCount(6);
  await page.locator(".calendar-event").first().click();
  await page.getByRole("button", { name: "Interested", exact: true }).click();
  await expect(page.getByRole("button", { name: "Interested", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Report absence", exact: true }).click();
  await expect(page.locator(".calendar-detail").getByText("Absence reported", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Interested", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Withdraw absence report", exact: true }).click();
  await expect(page.locator(".calendar-detail").getByText("No absence reported", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Back to calendar" }).click();
  await expect(page.locator(".calendar-event").first()).toContainText("Interested");
  await go(page, "/calendar/o/106?date=2026-09-01"); // first advanced-group session
  await expect(page.getByRole("alert")).toHaveText(/unavailable/);
});

test("unassigned member gets a clear state and no group sessions", async ({ page }) => {
  fake(page, "unassigned");
  await page.goto(entry());
  await expect(page.getByRole("status").filter({ hasText: "training group has not been assigned" })).toBeVisible();
  await expect(page.locator(".calendar-event")).toHaveCount(0);
  await expect(page.getByText("No events in this month.")).toBeVisible();
});

test("coach sees both groups; create keeps input on validation error and a lost response retries without duplicate", async ({ page }) => {
  const state = fake(page, "coach");
  await page.goto(entry());
  await expect(page.locator(".calendar-event")).toHaveCount(12);
  await page.getByRole("link", { name: "New event", exact: true }).click();
  await page.getByRole("textbox", { name: "Title", exact: true }).fill("Sortie fosse");
  await page.getByLabel("End", { exact: true }).fill("09:00"); // before start
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(/Check the title/);
  await expect(page.getByRole("textbox", { name: "Title", exact: true })).toHaveValue("Sortie fosse");
  await page.getByLabel("End", { exact: true }).fill("12:00");
  await page.getByRole("textbox", { name: "Venue", exact: true }).fill("Fosse A");
  state.failNextCreateResponse = true; // server commits, the response is lost
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(/Saving failed/);
  await expect(page.getByRole("textbox", { name: "Venue", exact: true })).toHaveValue("Fosse A");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sortie fosse", level: 1 })).toBeVisible();
  expect(state.creates).toBe(1);
  // Edit venue keeps the response; a stale version keeps the input.
  await page.getByRole("button", { name: "Interested", exact: true }).click();
  await page.getByRole("link", { name: "Edit event", exact: true }).click();
  await page.getByRole("textbox", { name: "Venue", exact: true }).fill("Fosse B");
  state.staleNextPatch = true;
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(/Someone changed this/);
  await expect(page.getByRole("textbox", { name: "Venue", exact: true })).toHaveValue("Fosse B");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/Time or venue changed/)).toBeVisible();
  await expect(page.getByText(/Notifications are not sent yet/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Interested", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Cancel event", exact: true }).click();
  await page.getByRole("button", { name: "Confirm cancellation", exact: true }).click();
  await expect(page.getByText(/Responses are kept as history/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Interested", exact: true })).toBeDisabled();
});

test("keyboard, large text, landscape and shell overlay replacement", async ({ page }) => {
  fake(page, "beginners");
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto(entry());
  await page.evaluate(() => (document.documentElement.style.fontSize = "32px"));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await nav(page).getByRole("link", { name: "Calendar", exact: true }).focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(nav(page).getByRole("link", { name: "Calendar", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Account navigation" }).click();
  await expect(nav(page)).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(nav(page)).toBeVisible();
});

test("filters, date jump and directional month motion respect reduced motion", async ({ page }) => {
  fake(page, "beginners");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto(entry());
  await expect(page.locator(".calendar-event")).toHaveCount(6);
  await page.getByRole("group", { name: "Source", exact: true }).getByRole("button", { name: "Outings", exact: true }).click();
  await expect(page.locator(".calendar-event")).toHaveCount(0);
  await expect(page.getByText("No events match these filters.")).toBeVisible();
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
  await expect(page.locator(".calendar-period")).toHaveCSS("animation-name", "calendar-previous");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Next month", exact: true }).click();
  await expect(page.locator(".calendar-period")).toHaveCSS("animation-name", "none");
});

test("small phone shows useful content before scrolling and reveals secondary filters", async ({ page }) => {
  fake(page, "beginners");
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto(entry());
  await expect(page.locator(".calendar-event")).toHaveCount(6);
  const firstEvent = await page.locator(".calendar-event").first().boundingBox();
  const bottomNav = await nav(page).boundingBox();
  expect(firstEvent!.y).toBeLessThan(300);
  expect(firstEvent!.y + firstEvent!.height).toBeLessThan(bottomNav!.y);
  await expect(page.getByRole("searchbox")).toBeHidden();
  await page.getByRole("button", { name: "Search and filters", exact: true }).click();
  await expect(page.getByRole("searchbox")).toBeVisible();
  await expect(page.getByRole("link", { name: "New event", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("Paris today marker and historical dates remain usable", async ({ page }) => {
  fake(page, "beginners");
  await page.clock.install({ time: new Date("2026-09-09T22:30:00Z") }); // already 10 Sep in Paris
  await page.goto(entry("&view=month"));
  await expect(page.locator('.calendar-month [aria-current="date"]')).toHaveText("10");
  const pastDay = page.locator(".calendar-day-past > button").filter({ hasText: /^8$/ });
  await expect(pastDay).toHaveAccessibleName(/Past/);
  await pastDay.click();
  await expect(page.locator(".calendar-event")).toHaveCount(6);
  await expect(page.locator(".calendar-event-today time")).toHaveAttribute("datetime", "2026-09-10");
});

test("day drill-down returns to the same month with filters preserved", async ({ page }) => {
  fake(page, "coach");
  await page.goto(entry("&view=month&source=club&q=Entra"));
  await page.locator(".calendar-month > div > button").filter({ hasText: /^8$/ }).click();
  await expect(page.getByRole("button", { name: "Agenda", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.locator(".calendar-event").first().click();
  await page.getByRole("link", { name: "Back to calendar", exact: true }).click();
  await page.getByRole("link", { name: "Back to calendar", exact: true }).click();
  await expect(page.locator(".calendar-month")).toBeVisible();
  await expect(page.getByRole("heading", { name: "September 2026", exact: true })).toBeVisible();
  await expect(page.getByRole("searchbox")).toHaveValue("Entra");
  const url = await page.evaluate(() => (window as any).reviewRouter.state.location.search);
  expect(new URLSearchParams(url).get("date")).toBe("2026-09-01");
  expect(new URLSearchParams(url).has("returnDate")).toBe(false);
});

for (const keyboard of ["focused field", "keyboard dismissed"]) {
  test(`touch phone: first tap on Save works with ${keyboard}`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await context.newPage();
    fake(page, "beginners");
    await page.goto(entry());
    await expect(page.locator(".calendar-event")).toHaveCount(6);
    await page.getByRole("link", { name: "New event", exact: true }).click();
    await page.getByRole("textbox", { name: "Title", exact: true }).fill("Tap test");
    await page.getByRole("textbox", { name: "Venue", exact: true }).fill("Pool");
    // Coarse pointer + focused text field: the shell hides the bottom nav.
    await expect(nav(page)).toHaveCount(0);
    if (keyboard === "keyboard dismissed") {
      await page.getByRole("heading", { level: 1 }).tap();
      await expect(nav(page)).toBeVisible();
    }
    await page.getByRole("button", { name: "Save", exact: true }).tap();
    await expect(page.getByRole("heading", { name: "Tap test", level: 1 })).toBeVisible();
    await context.close();
  });
}


test("agenda explicitly reports a cursor remaining after ten pages", async ({ page }) => {
  fake(page, "beginners");
  await page.route("**/api/v1/calendar/occurrences?*", (route) => route.fulfill({
    contentType: "application/json", body: JSON.stringify({ items: [], next_cursor: "more" }),
  }));
  await page.goto(entry());
  await expect(page.getByRole("alert")).toContainText("would be incomplete");
  await expect(page.locator(".calendar-event")).toHaveCount(0);
});
