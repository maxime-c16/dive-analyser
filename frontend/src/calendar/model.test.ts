import { expect, it, vi } from "vitest";
import { samples, trainingEvents, visibleEvents, validDate } from "./model";
import { primaryTabFor } from "../navigation/mobileNavigation";
it("preserves exact irregular dates, group IDs and timezone without generating recurrence", () => {
  const rows = ["2026-10-10", "2026-11-04"].map((date, i) => ({
    source_key: `synthetic-${i}`,
    local_date: date,
    start_local: "18:30",
    end_local: "20:30",
    timezone: "Europe/Paris",
    venue_code: "TEST",
    group_key: i ? "advanced" : "beginners",
  }));
  const events = trainingEvents(rows);
  expect(events.map((e) => e.date)).toEqual(rows.map((r) => r.local_date));
  expect(events.every((e) => e.zone === "Europe/Paris")).toBe(true);
  expect(
    visibleEvents([...events, ...samples], "beginners").map((e) => e.id),
  ).toEqual(["synthetic-0", ...samples.map((e) => e.id)]);
  expect(visibleEvents(events, "advanced")).toEqual([events[1]]);
  expect(visibleEvents(events, "unassigned")).toEqual([]);
  expect(visibleEvents(events, "coach")).toEqual(events);
});
it("maps calendar detail and edit to the same dev-only primary tab", () => {
  expect(primaryTabFor("/calendar/local/edit")).toBe("calendar");
  expect(primaryTabFor("/calendar-other")).toBeNull();
});

it("removes calendar mapping in production", () => {
  vi.stubEnv("DEV", false);
  expect(primaryTabFor("/calendar")).toBeNull();
  vi.unstubAllEnvs();
});

import { strings } from "./strings";
it("keeps prototype FR/EN strings in parity", () =>
  expect(Object.keys(strings.fr).sort()).toEqual(
    Object.keys(strings.en).sort(),
  ));
it("rejects malformed date links and preserves valid leap days", () => {
  expect(validDate("2026-99-99")).toBe(false);
  expect(validDate("2026-02-30")).toBe(false);
  expect(validDate("2028-02-29")).toBe(true);
});
