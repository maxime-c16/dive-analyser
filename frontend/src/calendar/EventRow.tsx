import { Link } from "react-router-dom";
import { ChevronRight, MapPin, Plus } from "lucide-react";
import type { Occurrence } from "./api";
import { lastDay, sourceOf, spanDays } from "./model";
import { useCalendarStrings } from "./useStrings";

const utc = (d: string) => new Date(`${d}T12:00:00Z`);

/** One occurrence in a list: colour rail by source, title, time and place, my answer. */
export default function EventRow({ o, today, search, selected = false, pop = false, index = 0 }: {
  o: Occurrence; today: string; search: string; selected?: boolean; pop?: boolean; index?: number
}) {
  const { t, lang } = useCalendarStrings();
  const cancelled = o.status === "cancelled" || o.event.status === "cancelled";
  const short = (d: string) => new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", timeZone: "UTC" }).format(utc(d));
  const multi = spanDays(o) > 1;
  const when = multi
    ? `${t.dateRange(short(o.local_date), short(lastDay(o)))} · ${t.days(spanDays(o))}`
    : o.is_all_day ? t.allDay : `${o.local_start}–${o.local_end}`;
  const isOpen = !!o.open_access;
  const isJoined = isOpen && o.my_interest === "interested";
  const openGroup = isOpen && o.event.calendar_name
    && !o.event.title.toLocaleLowerCase().includes(o.event.calendar_name.toLocaleLowerCase())
    ? o.event.calendar_name : null;
  return (
    <Link to={`/calendar/o/${o.id}${search}`} aria-current={selected ? "page" : undefined}
      className={`cal-ev cal-src-${sourceOf(o)}${isOpen ? " is-open" : ""}${isJoined ? " is-joined" : ""}${multi ? " is-multi" : ""}${lastDay(o) < today ? " is-past" : ""}${cancelled ? " is-cancelled" : ""}${pop ? " ca-pop" : ""}`}
      style={pop ? { ["--i" as string]: Math.min(index, 12) } : undefined}>
      <div className="cal-ev-body">
        <span className="cal-ev-title">{o.event.title}</span>
        <span className="cal-ev-sub">
          <span className="cal-ev-time">{when}</span>
          {o.venue_name && <span className="cal-ev-venue"><MapPin size={13} aria-hidden="true" />{o.venue_name}</span>}
          {openGroup && <span className={`cal-chip${isJoined ? "" : " is-open"}`}>{!isJoined && <Plus size={11} strokeWidth={2.5} aria-hidden="true" />}{openGroup}</span>}
          {cancelled && <span className="cal-chip is-bad">{t.cancelled}</span>}
          {o.event.status === "draft" && <span className="cal-chip">{t.draft}</span>}
          {isJoined && <span className="cal-chip is-yes">{t.goingShort}</span>}
          {o.my_absence_reported && <span className="cal-chip">{t.absence}</span>}
        </span>
      </div>
      <ChevronRight className="cal-ev-go" size={18} aria-hidden="true" />
    </Link>
  );
}
