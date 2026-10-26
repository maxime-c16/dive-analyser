import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, MapPin, Plus, Search, Users, X } from "lucide-react";
import { CalendarError, calendarApi, type CalendarInfo, type Interest, type MyClub, type Occurrence } from "../calendar/api";
import { addDays, coversDay, lastDay, matches, monthWindow, overlapsMonth, parisToday, sortOccurrences, sourceOf, spanDays, validDate } from "../calendar/model";
import { useCalendarStrings, type CalendarContext } from "../calendar/useStrings";
import EventRow from "../calendar/EventRow";
import OccurrenceView from "../calendar/OccurrenceView";
import EventForm, { OccurrenceForm } from "../calendar/EventForm";
import ScheduleEditor from "../calendar/ScheduleEditor";
import ClubAdmin from "../calendar/ClubAdmin";
import PageLoading from "../components/PageLoading";
import { Segmented } from "../components/code-analysis/parts";
import "../components/code-analysis/codeAnalysis.css";
import "./calendar.css";
import { MobileShellActions } from "../navigation/mobileShellActions";

type Window = Occurrence[] | "failed" | "incomplete";
const HORIZON_DAYS = 92; // the API serves at most 100 days per window

const utc = (d: string) => new Date(`${d}T12:00:00Z`);
const iso = (d: string) => `${d}T00:00:00Z`;
const daysBetween = (a: string, b: string) => Math.round((utc(b).getTime() - utc(a).getTime()) / 86_400_000);
const parisTime = (d: Date) => new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Europe/Paris" }).format(d);
const weekStart = (d: string) => addDays(d, -((utc(d).getUTCDay() + 6) % 7));

/** Occurrences of one UTC window, refetched on `revision` without blanking what is shown. */
function useWindow(from: string | null, to: string | null, revision: number): Window | null {
  const [state, setState] = useState<{ key: string; data: Window } | null>(null);
  const key = from && to ? `${from}|${to}` : "";
  useEffect(() => {
    if (!from || !to) return;
    const controller = new AbortController();
    calendarApi.occurrences(from, to, controller.signal)
      .then((items) => setState({ key, data: items }))
      .catch((error) => {
        if (!controller.signal.aborted) setState({ key, data: error instanceof CalendarError && error.code === "incomplete_occurrences" ? "incomplete" : "failed" });
      });
    return () => controller.abort();
  }, [key, revision]);
  return state && state.key === key ? state.data : null;
}

export default function Calendar() {
  const { t, lang } = useCalendarStrings();
  const [query, setQuery] = useSearchParams();
  const location = useLocation();
  const path = useParams()["*"] || "";
  const [now, setNow] = useState(() => new Date());
  const [revision, setRevision] = useState(0);
  const [me, setMe] = useState<MyClub[] | null>(null);
  const [calendars, setCalendars] = useState<CalendarInfo[]>([]);
  const [searching, setSearching] = useState(false);
  const [answers, setAnswers] = useState<Record<number, Interest | null>>({});
  const [answerError, setAnswerError] = useState(false);
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

  useEffect(() => {
    Promise.all([calendarApi.me(), calendarApi.calendars()])
      .then(([mine, cals]) => { setMe(mine.clubs); setCalendars(cals.items); })
      .catch(() => setMe((current) => current ?? []));
  }, [revision]);

  const today = parisToday(now);
  const date = validDate(query.get("date") || "") ? query.get("date")! : today;
  const month = date.slice(0, 7);
  const source = query.get("source") || "";
  const q = query.get("q") || "";
  const view = query.get("view") === "month" ? "month" : "upcoming";
  const showPast = query.get("past") === "1";

  const monthRange = monthWindow(month);
  const monthData = useWindow(monthRange.from, monthRange.to, revision);
  const upcomingData = useWindow(iso(addDays(today, -1)), iso(addDays(today, HORIZON_DAYS)), revision);
  const pastData = useWindow(showPast ? iso(addDays(today, -HORIZON_DAYS)) : null, showPast ? iso(today) : null, revision);

  // Rows pop in once, on the first paint; later changes never replay the entrance.
  const [intro, setIntro] = useState(true);
  const ready = me !== null && Array.isArray(view === "month" ? monthData : upcomingData);
  useEffect(() => {
    if (!ready || !intro) return;
    const timer = window.setTimeout(() => setIntro(false), 900);
    return () => window.clearTimeout(timer);
  }, [ready, intro]);

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(query);
    for (const [key, value] of Object.entries(changes)) if (value) next.set(key, value); else next.delete(key);
    setQuery(next, { replace: true });
  };
  const changeMonth = (offset: number) => {
    setMonthDirection(offset > 0 ? "next" : "previous");
    const d = utc(`${month}-01`);
    d.setUTCMonth(d.getUTCMonth() + offset);
    const first = d.toISOString().slice(0, 10);
    update({ date: first.slice(0, 7) === today.slice(0, 7) ? today : first });
  };

  const withAnswers = (items: Occurrence[]) => items.map((o) => (o.id in answers ? { ...o, my_interest: answers[o.id] } : o));
  const keep = (o: Occurrence) => (!source || sourceOf(o) === source) && matches(o, q);
  const upcoming = useMemo(() => Array.isArray(upcomingData)
    ? sortOccurrences(withAnswers(upcomingData).filter((o) => lastDay(o) >= today && keep(o))) : [],
  [upcomingData, answers, today, source, q]);
  const past = useMemo(() => Array.isArray(pastData)
    ? sortOccurrences(withAnswers(pastData).filter((o) => lastDay(o) < today && keep(o))) : [],
  [pastData, answers, today, source, q]);
  const inMonth = useMemo(() => Array.isArray(monthData)
    ? sortOccurrences(withAnswers(monthData).filter((o) => overlapsMonth(o, month) && keep(o))) : [],
  [monthData, answers, month, source, q]);
  const filtered = !!source || !!q.trim();
  const ctx: CalendarContext = { me: me ?? [], calendars, refresh };
  const search = location.search;

  const answer = (o: Occurrence, state: Interest) => {
    const next = o.my_interest === state ? null : state;
    setAnswers((a) => ({ ...a, [o.id]: next }));
    setAnswerError(false);
    calendarApi.setInterest(o.id, next).then(refresh).catch(() => {
      setAnswers((a) => { const { [o.id]: _drop, ...rest } = a; return rest; });
      setAnswerError(true);
    });
  };

  const head = (children?: React.ReactNode) => (
    <div className="cal-head">{children}<span className="cal-head-fill" /><MobileShellActions /></div>
  );

  // ---- Sub-pages -------------------------------------------------------------
  let content: React.ReactNode;
  const occMatch = path.match(/^o\/(\d+)(\/edit)?$/);
  const scheduleMatch = path.match(/^o\/(\d+)\/schedule$/);
  const editMatch = path.match(/^e\/(\d+)\/edit$/);
  const clubMatch = path.match(/^club\/(\d+)$/);
  if (path === "new") content = <div className="calendar-legacy"><EventForm ctx={ctx} defaultDate={date} /></div>;
  else if (editMatch) content = <div className="calendar-legacy"><EventForm ctx={ctx} eventId={Number(editMatch[1])} defaultDate={date} /></div>;
  else if (scheduleMatch) content = <div className="calendar-legacy"><ScheduleEditor ctx={ctx} occurrenceId={Number(scheduleMatch[1])} /></div>;
  else if (occMatch && occMatch[2]) content = <div className="calendar-legacy"><OccurrenceForm ctx={ctx} occurrenceId={Number(occMatch[1])} /></div>;
  else if (occMatch) {
    const id = Number(occMatch[1]);
    content = (
      <div className="cal-detail-layout">
        <aside className="cal-detail-agenda" aria-label={t.upcoming}>
          {upcoming.slice(0, 12).map((o) => <EventRow key={o.id} o={o} today={today} search={search} selected={o.id === id} />)}
        </aside>
        <OccurrenceView ctx={ctx} occurrenceId={id} />
      </div>
    );
  } else if (clubMatch) content = <div className="calendar-legacy"><ClubAdmin ctx={ctx} clubId={Number(clubMatch[1])} /></div>;
  else if (path) content = <p role="alert">{t.unavailable}</p>;

  if (content) {
    return (
      <section className="ca calendar-page cal-sub">
        {head(<Link className="ca-back" to={`/calendar${search}`}><ChevronLeft size={18} aria-hidden="true" />{t.title}</Link>)}
        {content}
      </section>
    );
  }

  // ---- Main page -------------------------------------------------------------
  const failed = (view === "month" ? monthData : upcomingData);
  const fmtDay = (d: string, o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(lang, { ...o, timeZone: "UTC" }).format(utc(d));
  const weekLabel = (w: string) => {
    const current = weekStart(today);
    if (w === current) return t.thisWeek;
    if (w === addDays(current, 7)) return t.nextWeek;
    const end = addDays(w, 6);
    return t.dateRange(fmtDay(w, w.slice(5, 7) === end.slice(5, 7) ? { day: "numeric" } : { day: "numeric", month: "short" }), fmtDay(end, { day: "numeric", month: "short" }));
  };
  const agenda = (items: Occurrence[]) => {
    const weeks = new Map<string, Map<string, Occurrence[]>>();
    for (const o of items) {
      const day = o.local_date < today && lastDay(o) >= today ? today : o.local_date;
      const w = weekStart(day);
      if (!weeks.has(w)) weeks.set(w, new Map());
      const days = weeks.get(w)!;
      days.set(day, [...(days.get(day) ?? []), o]);
    }
    let index = 0;
    return [...weeks].map(([w, days]) => (
      <section key={w} className="cal-week" aria-label={weekLabel(w)}>
        <h2 className="cal-week-h">{weekLabel(w)}</h2>
        {[...days].map(([day, list]) => (
          <div key={day} className="cal-day">
            <time className={`cal-day-tile${day === today ? " is-today" : ""}`} dateTime={day} aria-current={day === today ? "date" : undefined}>
              <b>{Number(day.slice(8))}</b><span>{fmtDay(day, { weekday: "short" }).replace(".", "")}</span>
            </time>
            <div className="cal-day-events">
              {list.map((o) => <EventRow key={o.id} o={o} today={today} search={search} pop={intro} index={index++} />)}
            </div>
          </div>
        ))}
      </section>
    ));
  };

  const next = upcoming.find((o) => o.status !== "cancelled" && o.event.status === "published" && !o.is_all_day
    && (o.local_date > today || (o.local_end ?? "") > parisTime(now)));
  const nextCard = next && (() => {
    const n = daysBetween(today, next.local_date);
    const group = next.event.calendar_kind === "group" ? next.event.calendar_name : null;
    return (
      <div className={`cal-next cal-src-${sourceOf(next)}${intro ? " ca-pop" : ""}`}>
        <Link className="cal-next-link" to={`/calendar/o/${next.id}${search}`}>
          <span className="cal-next-top">
            <span className="cal-tag"><i className="cal-dot" />{t.nextUp}{group ? ` · ${group}` : ""}</span>
            <span className="cal-count">{n === 0 ? t.today : n}{n > 0 && <small>{t.daysLeft(n)}</small>}</span>
          </span>
          <span className="cal-next-title">{next.event.title}</span>
          <span className="cal-next-meta">
            <b>{fmtDay(next.local_date, { weekday: "long", day: "numeric", month: "long" })}</b>
            <span>{next.local_start}–{next.local_end}</span>
            {next.venue_name && <span><MapPin size={14} aria-hidden="true" />{next.venue_name}</span>}
          </span>
        </Link>
        <div className="cal-rsvp" role="group" aria-label={t.yourResponse}>
          {([["interested", t.goingShort], ["maybe", t.maybe], ["declined", t.no]] as const).map(([state, label]) => (
            <button key={state} type="button" className={`is-${state}`} aria-pressed={next.my_interest === state} onClick={() => answer(next, state)}>
              {state === "interested" && <Check size={16} strokeWidth={3} aria-hidden="true" />}{label}
            </button>
          ))}
        </div>
      </div>
    );
  })();

  const monthCells = (() => {
    const pad = (utc(`${month}-01`).getUTCDay() + 6) % 7;
    const count = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).getUTCDate();
    const cells: React.ReactNode[] = Array.from({ length: pad }, (_, i) => <span key={`pad${i}`} aria-hidden="true" />);
    for (let i = 1; i <= count; i++) {
      const day = `${month}-${String(i).padStart(2, "0")}`;
      const list = inMonth.filter((o) => coversDay(o, day));
      const span = list.find((o) => spanDays(o) > 1);
      const dots = list.filter((o) => spanDays(o) === 1).slice(0, 3);
      const label = fmtDay(day, { weekday: "long", day: "numeric", month: "long" });
      cells.push(
        <button key={day} type="button" onClick={() => update({ date: day })}
          className={`cal-cell${day < today ? " is-past" : ""}${day === today ? " is-today" : ""}${day === date ? " is-selected" : ""}`}
          aria-pressed={day === date} aria-current={day === today ? "date" : undefined}
          aria-label={`${label}${list.length ? ` · ${list.map((o) => o.event.title).join(", ")}` : ""}`}>
          <span className="cal-cell-n">{i}</span>
          <span className="cal-cell-dots">{dots.map((o) => <i key={o.id} className={`cal-dot cal-src-${sourceOf(o)}`} />)}</span>
          {span && <span className={`cal-cell-span cal-src-${sourceOf(span)}${day === span.local_date ? " is-start" : ""}${day === lastDay(span) ? " is-end" : ""}`} />}
        </button>,
      );
    }
    return cells;
  })();
  const weekdays = Array.from({ length: 7 }, (_, i) => fmtDay(`2026-01-${String(5 + i).padStart(2, "0")}`, { weekday: "short" }).replace(".", ""));
  const monthPanel = (
    <div className="cal-month-wrap">
      <div className="cal-month-bar">
        <details className="cal-jump">
          <summary title={t.jumpDate}>
            <span className="cal-month-name">{fmtDay(`${month}-01`, { month: "long" })}</span> <span className="cal-month-year">{month.slice(0, 4)}</span>
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
          <div className="cal-jump-pop">
            <input type="date" aria-label={t.date} value={date} onChange={(e) => validDate(e.target.value) && update({ date: e.target.value })} />
            <button type="button" className="ca-pill" onClick={() => update({ date: today })}>{t.today}</button>
          </div>
        </details>
        <span className="cal-head-fill" />
        <div className="cal-nav2">
          <button type="button" onClick={() => changeMonth(-1)} aria-label={t.previous}><ChevronLeft size={18} /></button>
          <button type="button" onClick={() => changeMonth(1)} aria-label={t.next}><ChevronRight size={18} /></button>
        </div>
      </div>
      <div className="ca-panel cal-month">
        <div className="cal-weekdays" aria-hidden="true">{weekdays.map((d) => <span key={d}>{d}</span>)}</div>
        {Array.isArray(monthData)
          ? <div key={month} className={`cal-grid cal-grid-${monthDirection ?? "initial"}`}>{monthCells}</div>
          : monthData ? <p role="alert" className="cal-empty">{monthData === "incomplete" ? t.incompleteMonth : t.failed}</p>
          : <div className="cal-grid-skeleton" />}
      </div>
    </div>
  );
  const daySheet = (
    <section className="cal-sheet" aria-label={fmtDay(date, { weekday: "long", day: "numeric", month: "long" })}>
      <h2 className="cal-sheet-h">{date === today ? t.today : fmtDay(date, { weekday: "long", day: "numeric", month: "long" })}</h2>
      <div className="cal-day-events">
        {inMonth.filter((o) => coversDay(o, date)).map((o) => <EventRow key={o.id} o={o} today={today} search={search} />)}
        {Array.isArray(monthData) && !inMonth.some((o) => coversDay(o, date)) && <p className="cal-none">{t.nothingThatDay}</p>}
      </div>
    </section>
  );

  const unassigned = (me ?? []).filter((c) => c.group === null && c.membership.role === "member");
  return (
    <section className="ca calendar-page cal-main">
      {head(<h1>{t.title}</h1>)}
      <div className="cal-tools">
        <Segmented label={t.title} value={view} onChange={(v) => update({ view: v === "month" ? "month" : null })}
          options={[["upcoming", t.upcoming], ["month", t.month]] as const} />
        <span className="cal-head-fill" />
        <button type="button" className={`cal-icon${searching || q ? " is-on" : ""}`} aria-label={t.searchToggle} aria-expanded={searching || !!q}
          onClick={() => { if (searching || q) { setSearching(false); update({ q: null }); } else setSearching(true); }}>
          {searching || q ? <X size={18} /> : <Search size={18} />}
        </button>
        <Link className="cal-icon cal-create" to={`/calendar/new${search}`} aria-label={t.create}><Plus size={20} strokeWidth={2.5} /></Link>
      </div>
      {(searching || q) && (
        <label className="cal-search">
          <Search size={17} aria-hidden="true" />
          <input type="search" autoFocus placeholder={t.search} value={q} onChange={(e) => update({ q: e.target.value || null })} />
        </label>
      )}
      <div className="ca-scroll cal-filters" role="group" aria-label={t.source}>
        {(["", "club", "outing", "competition"] as const).map((s) => (
          <button key={s} type="button" className={`ca-pill${s ? ` cal-src-${s}` : ""}`} aria-pressed={source === s} onClick={() => update({ source: s || null })}>
            {s && <i className="cal-dot" />}{s ? t[s] : t.allShort}
          </button>
        ))}
        {(me ?? []).length > 0 && <span className="ca-divider" aria-hidden="true" />}
        {(me ?? []).map((c) => (
          <Link key={c.club.id} className="ca-pill cal-club" to={`/calendar/club/${c.club.id}${search}`} aria-label={`${t.clubPage} ${c.club.short_name || c.club.name}`}>
            <Users size={15} aria-hidden="true" />{c.club.short_name || c.club.name}
          </Link>
        ))}
      </div>
      {unassigned.map((c) => <p key={c.club.id} role="status" className="cal-notice">{t.noGroup(c.club.short_name || c.club.name)}</p>)}
      {answerError && <p role="alert" className="cal-notice is-bad">{t.retrySave}</p>}

      {!ready && !(failed === "failed" || failed === "incomplete") && <PageLoading message={t.loading} />}
      {ready || failed === "failed" || failed === "incomplete" ? (
        view === "month" ? (
          <div className="cal-cols">
            {monthPanel}
            {daySheet}
          </div>
        ) : (
          <div className="cal-cols">
            <div className="cal-stack">
              {failed === "failed" || failed === "incomplete"
                ? <p role="alert" className="cal-notice is-bad">{t.failed} <button type="button" className="ca-pill" onClick={refresh}>{t.retry}</button></p>
                : <>
                  {!filtered && nextCard}
                  <button type="button" className="ca-pill cal-past-toggle" aria-expanded={showPast} onClick={() => update({ past: showPast ? null : "1" })}>
                    {showPast ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronUp size={15} aria-hidden="true" />}{showPast ? t.hidePast : t.pastSessions}
                  </button>
                  {showPast && <div className="cal-agenda is-past">{Array.isArray(pastData) ? agenda(past) : <div className="cal-grid-skeleton" />}</div>}
                  <div className="cal-agenda">{agenda(upcoming)}</div>
                  {!upcoming.length && <p className="cal-empty">{filtered ? t.emptyFiltered : t.nothingUpcoming}</p>}
                </>}
            </div>
            <aside className="cal-side">
              {monthPanel}
              {daySheet}
            </aside>
          </div>
        )
      ) : null}
    </section>
  );
}
