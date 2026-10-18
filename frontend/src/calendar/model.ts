export type Event = {
  id: string;
  title: string;
  date: string;
  time: string;
  end?: string;
  zone: string;
  venue: string;
  source: "club" | "outing" | "competition";
  group?: string;
  cancelled?: boolean;
  changed?: boolean;
};
export type Role = "beginners" | "advanced" | "coach" | "unassigned";
export const visibleEvents = (events: Event[], role: Role) =>
  events.filter((e) => !e.group || role === "coach" || e.group === role);
export const samples: Event[] = [
  {
    id: "outing-demo",
    title: "Sortie entre plongeurs / Divers’ outing",
    date: "2026-10-24",
    time: "10:00",
    zone: "Europe/Paris",
    venue: "Piscine de démonstration",
    source: "outing",
  },
  {
    id: "meet-demo",
    title: "Rencontre de démonstration / Sample meet",
    date: "2026-11-14",
    time: "09:00",
    zone: "Europe/Paris",
    venue: "Lieu à vérifier / Venue to review",
    source: "competition",
  },
];
export function trainingEvents(rows: Record<string, string>[]): Event[] {
  return rows.map((r) => ({
    id: r.source_key,
    title: "KCPM",
    date: r.local_date,
    time: r.start_local,
    end: r.end_local,
    zone: r.timezone,
    venue: r.venue_code,
    group: r.group_key,
    source: "club",
  }));
}

export function validDate(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value
  );
}
