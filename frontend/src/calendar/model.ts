import type { Occurrence } from "./api";

export type Source = "club" | "outing" | "competition";

/** Filter bucket for an occurrence: training/camp from clubs, outings,
 * competitions (including curated federal dates). */
export function sourceOf(o: Pick<Occurrence, "event">): Source {
  const { event_type, calendar_kind } = o.event;
  if (event_type === "competition" || calendar_kind === "federal") return "competition";
  if (event_type === "outing" || calendar_kind === "personal") return "outing";
  return "club";
}

export function validDate(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value
  );
}

/** UTC query window covering a local month with a one-day margin either
 * side (timezones), well inside the API's 100-day limit. */
export function monthWindow(month: string): { from: string; to: string } {
  const start = new Date(`${month}-01T00:00:00Z`);
  const from = new Date(start.getTime() - 86_400_000);
  const end = new Date(start);
  end.setUTCMonth(end.getUTCMonth() + 1);
  const to = new Date(end.getTime() + 86_400_000);
  return { from: from.toISOString().replace(".000", ""), to: to.toISOString().replace(".000", "") };
}

export function inMonth(o: Pick<Occurrence, "local_date">, month: string) {
  return o.local_date.startsWith(month);
}

export function sortOccurrences<T extends Pick<Occurrence, "local_date" | "local_start" | "id">>(items: T[]): T[] {
  return [...items].sort((a, b) =>
    `${a.local_date}${a.local_start ?? "00:00"}${String(a.id).padStart(10, "0")}`.localeCompare(
      `${b.local_date}${b.local_start ?? "00:00"}${String(b.id).padStart(10, "0")}`));
}

export function matches(o: Occurrence, q: string): boolean {
  const needle = q.trim().toLowerCase();
  return !needle || `${o.event.title} ${o.venue_name ?? ""}`.toLowerCase().includes(needle);
}

export function addDays(day: string, days: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function parisToday(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now);
}

/** Inclusive last local day (all-day end dates are exclusive server-side). */
export function lastDay(o: Pick<Occurrence, "local_date" | "local_end_date">): string {
  return o.local_end_date && o.local_end_date > o.local_date ? o.local_end_date : o.local_date;
}

/** True when the occurrence covers any day of the month (multi-day camps). */
export function overlapsMonth(o: Pick<Occurrence, "local_date" | "local_end_date">, month: string): boolean {
  return o.local_date.slice(0, 7) <= month && lastDay(o).slice(0, 7) >= month;
}

export function coversDay(o: Pick<Occurrence, "local_date" | "local_end_date">, day: string): boolean {
  return o.local_date <= day && lastDay(o) >= day;
}

/** Days from first to last inclusive. */
export function spanDays(o: Pick<Occurrence, "local_date" | "local_end_date">): number {
  return Math.round((Date.parse(lastDay(o)) - Date.parse(o.local_date)) / 86_400_000) + 1;
}

/** Weekly dates from first to until, skipping excluded ones (client estimate;
 * the server is authoritative and also checks clock changes). */
export function weeklyDates(first: string, until: string, weekdays: number[], excluded: string[]): string[] {
  if (!validDate(first) || !validDate(until) || until < first) return [];
  const out: string[] = [];
  for (let day = first, i = 0; day <= until && i < 800; day = addDays(day, 1), i++) {
    const iso = ((new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7) + 1;
    if (weekdays.includes(iso) && !excluded.includes(day)) out.push(day);
  }
  return out;
}

export function isoWeekday(day: string): number {
  return ((new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7) + 1;
}
