import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Plus, Search, SlidersHorizontal, Users } from "lucide-react";
import { CalendarError, calendarApi, type CalendarInfo, type MyClub, type Occurrence } from "../calendar/api";
import { coversDay, lastDay, matches, monthWindow, overlapsMonth, parisToday, sortOccurrences, sourceOf, spanDays, validDate } from "../calendar/model";
import { useCalendarStrings, type CalendarContext } from "../calendar/useStrings";
import OccurrenceView from "../calendar/OccurrenceView";
import EventForm, { OccurrenceForm } from "../calendar/EventForm";
import ScheduleEditor from "../calendar/ScheduleEditor";
import ClubAdmin from "../calendar/ClubAdmin";
import PageLoading from "../components/PageLoading";
import "./calendar.css";

type Load = "loading" | "ready" | "failed";

export default function Calendar() {
  const { t, lang } = useCalendarStrings();
  const [query, setQuery] = useSearchParams();
  const location = useLocation();
  const path = useParams()["*"] || "";
  const [now, setNow] = useState(() => new Date());
  const [revision, setRevision] = useState(0);
  const [me, setMe] = useState<MyClub[]>([]);
  const [calendars, setCalendars] = useState<CalendarInfo[]>([]);
  const [items, setItems] = useState<Occurrence[]>([]);
  const [load, setLoad] = useState<Load>("loading");
  const [incomplete, setIncomplete] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [monthDirection, setMonthDirection] = useState<"next" | "previous" | null>(null);
  const refresh = useCallback(() => setRevision((r) => r + 1), []);

  useEffect(() => {
    const tick = () => setNow(new Date());
    const timer = window.setInterval(tick, 60_000);
    // Refresh on focus: another account or device may have changed events.
    const focus = () => { tick(); refresh(); };
    window.addEventListener("focus", focus);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", focus); };
  }, [refresh]);

  const today = parisToday(now);
  const date = validDate(query.get("date") || "") ? query.get("date")! : today;
  const month = date.slice(0, 7);
  const source = query.get("source") || "";
  const q = query.get("q") || "";
  const view = query.get("view") === "month" ? "month" : "agenda";

  useEffect(() => {
    const controller = new AbortController();
    setIncomplete(false);
    setLoad((current) => (current === "ready" ? current : "loading"));
    const { from, to } = monthWindow(month);
    Promise.all([calendarApi.me(), calendarApi.calendars(), calendarApi.occurrences(from, to, controller.signal)])
      .then(([mine, cals, occurrences]) => {
        if (controller.signal.aborted) return;
        setMe(mine.clubs);
        setCalendars(cals.items);
        setItems(occurrences);
        setLoad("ready");
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setIncomplete(error instanceof CalendarError && error.code === "incomplete_occurrences");
          setLoad("failed");
        }
      });
    return () => controller.abort();
  }, [month, revision]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(query);
    if (key === "date" || key === "view") next.delete("returnDate");
    if (value) next.set(key, value); else next.delete(key);
    setQuery(next);
  };
  const changeMonth = (offset: number) => {
    setMonthDirection(offset > 0 ? "next" : "previous");
    const d = new Date(`${month}-01T12:00:00Z`);
    d.setUTCMonth(d.getUTCMonth() + offset);
    update("date", d.toISOString().slice(0, 10));
  };
  const inThisMonth = useMemo(() => sortOccurrences(items.filter((o) => overlapsMonth(o, month))), [items, month]);
  const matching = inThisMonth.filter((o) =>
    (view === "month" || lastDay(o) >= date) && (!source || sourceOf(o) === source) && matches(o, q));
  const filtered = !!source || !!q.trim();
  const ctx: CalendarContext = { me, calendars, refresh };
  const search = location.search;

  const dateLabel = (value: string) => new Intl.DateTimeFormat(lang, {
    weekday: "short", day: "numeric", month: "long", timeZone: "UTC",
  }).format(new Date(value + "T12:00:00Z"));
  const shortDate = (value: string) => new Intl.DateTimeFormat(lang, {
    weekday: "short", day: "numeric", month: "short", timeZone: "UTC",
  }).format(new Date(value + "T12:00:00Z"));
  const row = (o: Occurrence) => {
    const cancelled = o.status === "cancelled" || o.event.status === "cancelled";
    return (
      <Link key={o.id}
        className={`calendar-event ${cancelled ? "calendar-cancelled" : ""} ${o.local_date < today ? "calendar-event-past" : ""} ${o.local_date === today ? "calendar-event-today" : ""}`}
        to={`/calendar/o/${o.id}${search}`}>
        <time dateTime={o.local_date} aria-current={o.local_date === today ? "date" : undefined}>
          <strong>{o.local_date.slice(8)}</strong>
          <span>{new Intl.DateTimeFormat(lang, { weekday: "short", timeZone: "UTC" }).format(new Date(o.local_date + "T12:00:00Z"))}</span>
        </time>
        <div>
          <span className="calendar-source">
            {t[sourceOf(o)]}
            {o.event.calendar_kind === "group" && o.event.calendar_name ? ` · ${o.event.calendar_name}` : ""}
          </span>
          <h2>{o.event.title}</h2>
          <p>{spanDays(o) > 1
            ? `${t.dateRange(shortDate(o.local_date), shortDate(lastDay(o)))}${o.is_all_day ? "" : ` · ${o.local_start}–${o.local_end}`}`
            : o.is_all_day ? t.allDay : `${o.local_start}–${o.local_end}`}{o.venue_name ? ` · ${o.venue_name}` : ""}</p>
          {o.local_date <= today && <span className="calendar-date-status">{o.local_date === today ? t.today : t.past}</span>}
          {cancelled && <p className="calendar-badge">{t.cancelled}</p>}
          {o.event.status === "draft" && <p className="calendar-badge">{t.draft}</p>}
          {o.my_interest && <p className="calendar-badge calendar-badge-accent">{t[o.my_interest]}</p>}
          {o.my_absence_reported && <p className="calendar-badge">{t.absence}</p>}
        </div>
        <ChevronRight aria-hidden="true" size={18} />
      </Link>
    );
  };

  const unassigned = me.filter((c) => c.group === null && c.membership.role === "member");
  const notices = (
    <>
      {unassigned.map((c) => (
        <p key={c.club.id} role="status" className="calendar-notice">{t.noGroup(c.club.short_name || c.club.name)}</p>
      ))}
    </>
  );

  let content: React.ReactNode;
  const occMatch = path.match(/^o\/(\d+)(\/edit)?$/);
  const scheduleMatch = path.match(/^o\/(\d+)\/schedule$/);
  const editMatch = path.match(/^e\/(\d+)\/edit$/);
  const clubMatch = path.match(/^club\/(\d+)$/);
  if (path === "new") content = <EventForm ctx={ctx} defaultDate={date} />;
  else if (editMatch) content = <EventForm ctx={ctx} eventId={Number(editMatch[1])} defaultDate={date} />;
  else if (scheduleMatch) content = <ScheduleEditor ctx={ctx} occurrenceId={Number(scheduleMatch[1])} />;
  else if (occMatch && occMatch[2]) content = <OccurrenceForm ctx={ctx} occurrenceId={Number(occMatch[1])} />;
  else if (occMatch) {
    content = (
      <div className="calendar-detail-layout">
        <aside className="calendar-detail-agenda" aria-label={t.agenda}>
          <h2>{t.agenda}</h2>
          {matching.map(row)}
        </aside>
        <OccurrenceView ctx={ctx} occurrenceId={Number(occMatch[1])} />
      </div>
    );
  } else if (clubMatch) content = <ClubAdmin ctx={ctx} clubId={Number(clubMatch[1])} />;
  else if (path) content = <p role="alert">{t.unavailable}</p>;

  if (content) {
    return (
      <section className="calendar-page">
        <Link className="calendar-back" to={`/calendar${search}`}><ChevronLeft size={18} aria-hidden="true" />{t.back}</Link>
        {content}
      </section>
    );
  }

  const returnDate = query.get("returnDate");
  const monthQuery = new URLSearchParams(query);
  monthQuery.set("view", "month");
  if (returnDate && validDate(returnDate)) monthQuery.set("date", returnDate);
  monthQuery.delete("returnDate");

  return (
    <section className="calendar-page">
      <header className="calendar-heading">
        <div>
          <h1>{t.title}</h1>
          <p>{t.intro}</p>
        </div>
        <CalendarDays size={40} aria-hidden="true" />
      </header>
      {notices}
      {view === "agenda" && returnDate && validDate(returnDate) && (
        <Link className="calendar-back" to={`/calendar?${monthQuery}`}><ChevronLeft size={18} aria-hidden="true" />{t.back}</Link>
      )}
      <div className="calendar-toolbar">
        <button onClick={() => changeMonth(-1)} aria-label={t.previous}><ChevronLeft /></button>
        <details className="calendar-date-jump">
          <summary title={t.jumpDate}>
            <h2>{new Intl.DateTimeFormat(lang, { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(month + "-01T12:00:00Z"))}</h2>
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
          <div className="calendar-date-popover">
            <label>{t.date}<input type="date" value={date} onChange={(e) => validDate(e.target.value) && update("date", e.target.value)} /></label>
            <button className="calendar-mobile-today" onClick={() => update("date", today)}>{t.today}</button>
          </div>
        </details>
        <button onClick={() => changeMonth(1)} aria-label={t.next}><ChevronRight /></button>
        <button className="calendar-today" onClick={() => update("date", today)}>{t.today}</button>
      </div>
      <div className="calendar-switch">
        <div>
          {(["agenda", "month"] as const).map((v) => (
            <button key={v} aria-pressed={view === v} onClick={() => update("view", v)}>{t[v]}</button>
          ))}
        </div>
        <div className="calendar-quick-actions">
          {me.map((c) => (
            <Link key={c.club.id} className="calendar-club-link" to={`/calendar/club/${c.club.id}${search}`}
              aria-label={`${t.clubPage} ${c.club.short_name || c.club.name}`}>
              <Users size={18} aria-hidden="true" /><span>{c.club.short_name || c.club.name}</span>
            </Link>
          ))}
          <button className="calendar-filter-toggle" aria-label={t.filters} aria-expanded={filtersOpen}
            aria-controls="calendar-filters" aria-pressed={filtered} onClick={() => setFiltersOpen(!filtersOpen)}>
            <SlidersHorizontal size={19} aria-hidden="true" />
            {filtered && <span className="calendar-filter-indicator" />}
          </button>
          <Link className="calendar-create" to={`/calendar/new${search}`} aria-label={t.create}>
            <Plus size={18} aria-hidden="true" /><span>{t.create}</span>
          </Link>
        </div>
      </div>
      <div id="calendar-filters" className={`calendar-filters ${filtersOpen ? "calendar-filters-open" : ""}`}>
        <div className="calendar-source-options" role="group" aria-label={t.source}>
          {(["", "club", "outing", "competition"] as const).map((s) => (
            <button key={s} aria-pressed={source === s} onClick={() => update("source", s)}>{s ? t[s] : t.allShort}</button>
          ))}
        </div>
        <label className="calendar-search">
          <span className="sr-only">{t.search}</span>
          <Search size={18} aria-hidden="true" />
          <input type="search" placeholder={t.search} value={q} onChange={(e) => update("q", e.target.value)} />
        </label>
      </div>
      {load === "loading" && <PageLoading message={t.loading} />}
      {load === "failed" && (
        <p role="alert">{incomplete ? t.incompleteMonth : t.failed} <button onClick={refresh}>{t.retry}</button></p>
      )}
      {load === "ready" && (
        <div className="calendar-period-viewport">
          <div key={month} className={`calendar-period calendar-period-${monthDirection || "initial"}`}>
            {view === "month" ? (
              <div className="calendar-month">
                <div className="calendar-weekdays">
                  {Array.from({ length: 7 }, (_, i) => (
                    <span key={i}>{new Intl.DateTimeFormat(lang, { weekday: "short", timeZone: "UTC" }).format(new Date(`2026-01-${String(5 + i).padStart(2, "0")}T12:00:00Z`))}</span>
                  ))}
                </div>
                {Array.from({ length: (new Date(month + "-01T12:00:00Z").getUTCDay() + 6) % 7 }, (_, i) => <div aria-hidden="true" key={"blank" + i} />)}
                {Array.from({ length: new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).getUTCDate() }, (_, i) => {
                  const day = `${month}-${String(i + 1).padStart(2, "0")}`;
                  return (
                    <div key={day} className={`${day < today ? "calendar-day-past" : ""} ${day === today ? "calendar-day-today" : ""} ${day === date ? "calendar-day-selected" : ""}`}>
                      <button
                        aria-label={`${dateLabel(day)}${day === today ? ` · ${t.today}` : day < today ? ` · ${t.past}` : ""}`}
                        aria-current={day === today ? "date" : undefined}
                        onClick={() => {
                          const next = new URLSearchParams(query);
                          next.set("returnDate", date);
                          next.set("date", day);
                          next.set("view", "agenda");
                          setQuery(next);
                        }}>{i + 1}</button>
                      {matching.filter((o) => coversDay(o, day)).map((o) => (
                        <Link key={o.id} to={`/calendar/o/${o.id}${search}`}
                          className={spanDays(o) > 1 ? "calendar-month-span" : undefined}
                          aria-label={`${dateLabel(day)} ${o.event.title} ${spanDays(o) > 1 ? t.dateRange(dateLabel(o.local_date), dateLabel(lastDay(o))) : o.local_start ?? t.allDay}`}>
                          <span className={`calendar-dot calendar-dot-${sourceOf(o)}`} />
                          <span className="calendar-month-title">{o.local_date === day ? (o.local_start ?? "") : "↳"} {o.event.title}</span>
                        </Link>
                      ))}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="calendar-agenda">{matching.map(row)}</div>
            )}
            {!matching.length && <p className="calendar-empty">{filtered && inThisMonth.length ? t.emptyFiltered : t.empty}</p>}
          </div>
        </div>
      )}
    </section>
  );
}
