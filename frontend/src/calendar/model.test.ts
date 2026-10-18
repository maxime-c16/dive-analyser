import { afterEach, expect, it, vi } from "vitest";
import {
  coversDay, inMonth, lastDay, matches, monthWindow, overlapsMonth, sortOccurrences, sourceOf, spanDays, validDate, weeklyDates,
} from "./model";
import { CalendarError, calendarApi } from "./api";
import { primaryTabFor } from "../navigation/mobileNavigation";
import { strings } from "./strings";
import type { Occurrence } from "./api";

type Over = Omit<Partial<Occurrence>, "event"> & { event?: Partial<Occurrence["event"]> };
const occ = (over: Over = {}): Occurrence => ({
  id: 1, occurrence_key: "k", status: "scheduled", is_all_day: false, starts_at: null, ends_at: null,
  start_date: null, end_date: null, venue_name: "SNMT", version: 1, my_interest: null, my_absence_reported: false,
  local_date: "2026-10-01", local_start: "20:00", local_end: "22:00", imported: true, local_end_date: "2026-10-01",
  series_date: null, detached: false, ...over,
  event: { id: 1, calendar_id: 1, calendar_kind: "group", club_id: 1, event_type: "training", audience: "group",
    status: "published", title: "Entraînement", timezone: "Europe/Paris", version: 1, calendar_name: "A",
    training_group_id: 1, ...over.event },
});

afterEach(() => { vi.unstubAllGlobals(); });

it("classifies sources without inventing groups", () => {
  expect(sourceOf(occ())).toBe("club");
  expect(sourceOf(occ({ event: { event_type: "outing", calendar_kind: "personal" } }))).toBe("outing");
  expect(sourceOf(occ({ event: { event_type: "competition", calendar_kind: "club" } }))).toBe("competition");
  expect(sourceOf(occ({ event: { event_type: "other", calendar_kind: "federal" } }))).toBe("competition");
});

it("windows a local month inside the 100-day API bound and sorts by local time", () => {
  expect(monthWindow("2026-10")).toEqual({ from: "2026-09-30T00:00:00Z", to: "2026-11-02T00:00:00Z" });
  expect(monthWindow("2026-12").to).toBe("2027-01-02T00:00:00Z");
  const items = [occ({ id: 3, local_date: "2026-10-02" }), occ({ id: 2, local_start: "08:00" }), occ({ id: 1, local_start: null, is_all_day: true })];
  expect(sortOccurrences(items).map((o) => o.id)).toEqual([1, 2, 3]);
  expect(inMonth(occ(), "2026-10")).toBe(true);
  expect(matches(occ(), "snmt")).toBe(true);
  expect(matches(occ(), "insep")).toBe(false);
});

it("maps calendar detail, edit and club pages to the calendar tab only", () => {
  expect(primaryTabFor("/calendar/o/12/edit")).toBe("calendar");
  expect(primaryTabFor("/calendar/club/1")).toBe("calendar");
  expect(primaryTabFor("/calendar-other")).toBeNull();
});

it("keeps FR/EN strings in parity", () =>
  expect(Object.keys(strings.fr).sort()).toEqual(Object.keys(strings.en).sort()));

it("rejects malformed date links and preserves valid leap days", () => {
  expect(validDate("2026-99-99")).toBe(false);
  expect(validDate("2026-02-30")).toBe(false);
  expect(validDate("2028-02-29")).toBe(true);
});

it("surfaces stable server error codes and sends the idempotency key", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "stale_version", message: "changed" } }), { status: 409 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: 9, occurrences: [] }), { status: 201 }));
  vi.stubGlobal("fetch", fetchMock);
  const error = await calendarApi.cancelEvent(1, 1).catch((e) => e);
  expect(error).toBeInstanceOf(CalendarError);
  expect(error.code).toBe("stale_version");
  await calendarApi.createEvent({ calendar_id: null, event_type: "outing", audience: "invited", status: "published",
    title: "x", description: "", venue_name: null, venue_address: null, map_url: null, timezone: "Europe/Paris",
    when: { all_day: true, start_date: "2026-10-01" } }, "key-1");
  expect(fetchMock.mock.calls[1][1].headers["Idempotency-Key"]).toBe("key-1");
  expect(fetchMock.mock.calls[1][1].cache).toBe("no-store");
});

it("pages through occurrence cursors", async () => {
  const page = (items: unknown[], next: string | null) => new Response(JSON.stringify({ items, next_cursor: next }));
  const fetchMock = vi.fn().mockResolvedValueOnce(page([occ({ id: 1 })], "c1")).mockResolvedValueOnce(page([occ({ id: 2 })], null));
  vi.stubGlobal("fetch", fetchMock);
  const items = await calendarApi.occurrences("2026-09-30T00:00:00Z", "2026-11-02T00:00:00Z");
  expect(items.map((o) => o.id)).toEqual([1, 2]);
  expect(String(fetchMock.mock.calls[1][0])).toContain("cursor=c1");
});

it("shows multi-day camps on every covered day and across month boundaries", () => {
  // KCPM February camp: 19-21 Feb 2027 inclusive (server end_date 22 Feb exclusive).
  const camp = occ({ is_all_day: true, local_date: "2027-02-19", local_end_date: "2027-02-21", local_start: null,
    start_date: "2027-02-19", end_date: "2027-02-22" });
  expect(lastDay(camp)).toBe("2027-02-21");
  expect(spanDays(camp)).toBe(3);
  expect(["2027-02-18", "2027-02-19", "2027-02-21", "2027-02-22"].map((d) => coversDay(camp, d))).toEqual([false, true, true, false]);
  const crossing = occ({ local_date: "2027-01-30", local_end_date: "2027-02-02" });
  expect(overlapsMonth(crossing, "2027-01") && overlapsMonth(crossing, "2027-02")).toBe(true);
  expect(overlapsMonth(crossing, "2027-03")).toBe(false);
  expect(spanDays(occ())).toBe(1);
});

it("estimates weekly sessions with exclusions", () => {
  expect(weeklyDates("2026-11-03", "2026-11-24", [2, 4], ["2026-11-10"])).toEqual(
    ["2026-11-03", "2026-11-05", "2026-11-12", "2026-11-17", "2026-11-19", "2026-11-24"]);
  expect(weeklyDates("2026-11-03", "2026-11-01", [2], [])).toEqual([]);
});


it("refuses a partial agenda when a cursor remains after page ten", async () => {
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({
    items: [occ()], next_cursor: "more",
  })));
  vi.stubGlobal("fetch", fetchMock);
  await expect(calendarApi.occurrences("2026-10-01", "2026-11-01")).rejects.toMatchObject({
    code: "incomplete_occurrences",
  });
  expect(fetchMock).toHaveBeenCalledTimes(10);
});

it("returns a complete agenda when the tenth page has no next cursor", async () => {
  let page = 0;
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({
    items: [occ({ id: ++page })], next_cursor: page < 10 ? `p${page}` : null,
  })));
  vi.stubGlobal("fetch", fetchMock);
  expect(await calendarApi.occurrences("2026-10-01", "2026-11-01")).toHaveLength(10);
  expect(fetchMock).toHaveBeenCalledTimes(10);
});
