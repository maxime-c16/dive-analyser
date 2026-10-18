import React, { useEffect, useState } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  MapPin,
  Plus,
} from "lucide-react";
import {
  Event,
  Role,
  samples,
  trainingEvents,
  visibleEvents,
  validDate,
} from "../calendar/model";
import { strings } from "../calendar/strings";
import "./calendarPrototype.css";

const session: {
  events: Event[];
  interest: Record<string, boolean>;
  absence: Record<string, boolean>;
} = { events: samples, interest: {}, absence: {} };

export default function CalendarPrototype() {
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage?.startsWith("fr") ? "fr" : "en";
  const t = strings[lang];
  const [query, setQuery] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();
  const path = params["*"] || "";
  const [events, setEvents] = useState<Event[]>(session.events);
  const [load, setLoad] = useState("loading");
  const [revision, setRevision] = useState(0);
  const role = (
    ["beginners", "advanced", "coach", "unassigned"].includes(
      query.get("role") || "",
    )
      ? query.get("role")
      : "beginners"
  ) as Role;
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Paris",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const date = validDate(query.get("date") || "") ? query.get("date")! : today;
  const month = date.slice(0, 7);
  const source = query.get("source") || "";
  const view = query.get("view") || "agenda";
  const [interest, setInterest] = useState<Record<string, boolean>>(
    session.interest,
  );
  const [absence, setAbsence] = useState<Record<string, boolean>>(
    session.absence,
  );
  const [linked, setLinked] = useState(false);
  useEffect(() => {
    session.events = events;
    session.interest = interest;
    session.absence = absence;
  }, [events, interest, absence]);
  const [form, setForm] = useState({
    title: "",
    date,
    time: "10:00",
    venue: "",
  });
  const [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    setLoad("loading");
    fetch("/__calendar_local/training")
      .then((r) => {
        if (!r.ok) throw Error();
        return r.json();
      })
      .then((data) => {
        if (live) {
          setEvents((old) => [
            ...old.filter((e) => e.source !== "club"),
            ...trainingEvents(data),
          ]);
          setLoad("ready");
        }
      })
      .catch(() => {
        if (live) setLoad("failed");
      });
    return () => {
      live = false;
    };
  }, [revision]);
  const update = (key: string, value: string) => {
    const q = new URLSearchParams(query);
    value ? q.set(key, value) : q.delete(key);
    setQuery(q);
  };
  const accessible = visibleEvents(events, role);
  const id = path.replace(/\/edit$/, "");
  const event = accessible.find((e) => e.id === id);
  const editing = path === "new" || path.endsWith("/edit");
  const back = "/calendar" + location.search;
  const openForm = (e?: Event) => {
    setForm(
      e
        ? { title: e.title, date: e.date, time: e.time, venue: e.venue }
        : { title: "", date, time: "10:00", venue: "" },
    );
    setError(false);
    navigate(
      e
        ? `/calendar/${encodeURIComponent(e.id)}/edit${location.search}`
        : `/calendar/new${location.search}`,
    );
  };
  useEffect(() => {
    if (event && path.endsWith("/edit"))
      setForm({
        title: event.title,
        date: event.date,
        time: event.time,
        venue: event.venue,
      });
  }, [path, event?.id]);
  const changeMonth = (offset: number) => {
    const d = new Date(`${month}-01T12:00:00Z`);
    d.setUTCMonth(d.getUTCMonth() + offset);
    update("date", d.toISOString().slice(0, 10));
  };
  const matching = accessible
    .filter(
      (e) =>
        e.date.startsWith(month) &&
        (view === "month" || e.date >= date) &&
        (!source || e.source === source) &&
        `${e.title} ${e.venue}`
          .toLowerCase()
          .includes((query.get("q") || "").toLowerCase()),
    )
    .sort((a, b) => `${a.date}${a.time}`.localeCompare(`${b.date}${b.time}`));
  const dateLabel = (value: string) =>
    new Intl.DateTimeFormat(lang, {
      weekday: "short",
      day: "numeric",
      month: "long",
      timeZone: "Europe/Paris",
    }).format(new Date(value + "T12:00:00Z"));
  const row = (e: Event) => (
    <Link
      key={e.id}
      className={`calendar-event ${e.cancelled ? "calendar-cancelled" : ""}`}
      to={`/calendar/${encodeURIComponent(e.id)}${location.search}`}
    >
      <time dateTime={e.date}>
        <strong>{e.date.slice(8)}</strong>
        <span>
          {new Intl.DateTimeFormat(lang, { weekday: "short" }).format(
            new Date(e.date + "T12:00:00"),
          )}
        </span>
      </time>
      <div>
        <span className="calendar-source">
          {t[e.source]}
          {e.group
            ? ` · ${t[e.group as "beginners" | "advanced"]}`
            : ` · ${t.sample}`}
        </span>
        <h2>{e.title}</h2>
        <p>
          {e.time}
          {e.end ? `–${e.end}` : ""} · {e.venue}
        </p>
        {e.cancelled && <p>{t.cancelled}</p>}
        {e.changed && <p>{t.changed}</p>}
      </div>
      <ChevronRight aria-hidden="true" size={18} />
    </Link>
  );
  return (
    <section className="calendar-prototype">
      <details className="calendar-controls">
        <summary>{t.prototype}</summary>
        <label>
          {t.role}
          <select value={role} onChange={(e) => update("role", e.target.value)}>
            {(["beginners", "advanced", "coach", "unassigned"] as Role[]).map(
              (r) => (
                <option key={r} value={r}>
                  {t[r]}
                </option>
              ),
            )}
          </select>
        </label>
        <p>{t.membership}</p>
        <p>
          {t.count}: {events.filter((e) => e.source === "club").length} ·
          Europe/Paris
        </p>
        <p>{t.local}</p>
      </details>
      {role === "unassigned" && (
        <p role="status" className="calendar-notice">
          {t.noGroup}
        </p>
      )}
      {path && (
        <Link className="calendar-back" to={back}>
          <ChevronLeft size={18} />
          {t.back}
        </Link>
      )}
      <div
        className={
          path && event && !editing ? "calendar-detail-layout" : undefined
        }
      >
        {path && event && !editing && (
          <aside className="calendar-detail-agenda" aria-label={t.agenda}>
            <h2>{t.agenda}</h2>
            {matching.map((e) => row({ ...e, changed: false }))}
          </aside>
        )}
        <div>
          {editing ? (
            path !== "new" && (!event || event.source !== "outing" || event.cancelled) ? (
              <p>{t.unavailable}</p>
            ) : (
              <form
                noValidate
                onSubmit={(e) => {
                  e.preventDefault();
                  if (
                    !form.title.trim() ||
                    !form.venue.trim() ||
                    !validDate(form.date) ||
                    !/^\d{2}:\d{2}$/.test(form.time)
                  ) {
                    setError(true);
                    return;
                  }
                  const saved: Event = {
                    ...(event || {
                      id: `local-${Date.now()}`,
                      zone: "Europe/Paris",
                      source: "outing" as const,
                    }),
                    ...form,
                    changed:
                      !!event &&
                      (!!event.changed ||
                        event.time !== form.time ||
                        event.venue !== form.venue),
                  };
                  setEvents((old) => [
                    ...old.filter((x) => x.id !== saved.id),
                    saved,
                  ]);
                  navigate(
                    `/calendar/${encodeURIComponent(saved.id)}${location.search}`,
                  );
                }}
              >
                <h1>{event ? t.edit : t.create}</h1>
                <p>{t.invite}</p>
                {(["title", "date", "time", "venue"] as const).map((k) => (
                  <label key={k}>
                    {k === "title" ? t.titleField : t[k]}
                    <input
                      required
                      type={k === "date" || k === "time" ? k : "text"}
                      value={form[k]}
                      onChange={(e) =>
                        setForm({ ...form, [k]: e.target.value })
                      }
                    />
                  </label>
                ))}
                {error && <p role="alert">{t.error}</p>}
                <button type="submit">{t.save}</button>
                <Link to={back}>{t.cancelEdit}</Link>
              </form>
            )
          ) : path ? (
            event ? (
              <article className="calendar-detail">
                <span className="calendar-source">{t[event.source]}</span>
                <h1>{event.title}</h1>
                <p>
                  {dateLabel(event.date)} · {event.time}
                  {event.end ? `–${event.end}` : ""}
                </p>
                <p>
                  {t.timezone}: {event.zone}
                </p>
                <p className="calendar-venue">
                  <MapPin size={18} />
                  {event.venue}
                </p>
                {event.cancelled && <p role="status">{t.cancelled}</p>}
                {event.changed && (
                  <p role="status" className="calendar-notice">
                    {t.changed}
                  </p>
                )}
                <p>{t.interestNote}</p>
                <button
                  disabled={event.cancelled}
                  aria-pressed={!!interest[event.id]}
                  onClick={() =>
                    setInterest({
                      ...interest,
                      [event.id]: !interest[event.id],
                    })
                  }
                >
                  {interest[event.id] ? t.uninterested : t.interest}
                </button>
                {event.group && (
                  <div className="calendar-group">
                    <h2>{t.training}</h2>
                    <p>{t.assignment}</p>
                    {role === event.group && (
                      <>
                        <p role="status">
                          {absence[event.id] ? t.absence : t.noAbsence}
                        </p>
                        <button
                          aria-pressed={!!absence[event.id]}
                          onClick={() =>
                            setAbsence({
                              ...absence,
                              [event.id]: !absence[event.id],
                            })
                          }
                        >
                          {absence[event.id] ? t.undoAbsence : t.absent}
                        </button>
                      </>
                    )}
                  </div>
                )}
                {event.source === "outing" && (
                  <div className="calendar-actions">
                    <p>{t.invite}</p>
                    <button
                      disabled={event.cancelled}
                      onClick={() => openForm(event)}
                    >
                      {t.edit}
                    </button>
                    <button
                      disabled={event.cancelled}
                      onClick={() =>
                        setEvents((old) =>
                          old.map((e) =>
                            e.id === event.id ? { ...e, cancelled: true } : e,
                          ),
                        )
                      }
                    >
                      {t.cancel}
                    </button>
                  </div>
                )}
                {event.source === "competition" && (
                  <div className="calendar-group">
                    <h2>{t.resources}</h2>
                    <p>{t.review}</p>
                    <ul>
                      {(
                        ["official", "entry", "sheets", "results"] as const
                      ).map((k) => (
                        <li key={k}>
                          {t[k]} — {t.review}
                        </li>
                      ))}
                    </ul>
                    <p>{t.deadline}</p>
                    <p>{t.resourceNote}</p>
                  </div>
                )}
                <div className="calendar-group">
                  <button onClick={() => setLinked(true)}>{t.link}</button>
                  {linked && <p role="status">{t.linked}</p>}
                </div>
              </article>
            ) : (
              <p role="alert">{t.unavailable}</p>
            )
          ) : (
            <>
              <header className="calendar-heading">
                <div>
                  <h1>{t.title}</h1>
                  <p>{t.intro}</p>
                </div>
                <CalendarDays size={40} aria-hidden="true" />
              </header>
              <div className="calendar-toolbar">
                <button onClick={() => changeMonth(-1)} aria-label={t.previous}>
                  <ChevronLeft />
                </button>
                <h2>
                  {new Intl.DateTimeFormat(lang, {
                    month: "long",
                    year: "numeric",
                  }).format(new Date(month + "-01T12:00:00"))}
                </h2>
                <button onClick={() => changeMonth(1)} aria-label={t.next}>
                  <ChevronRight />
                </button>
                <button onClick={() => update("date", today)}>{t.today}</button>
              </div>
              <div className="calendar-filters">
                <label>
                  {t.date}
                  <input
                    type="date"
                    value={date}
                    onChange={(e) => update("date", e.target.value)}
                  />
                </label>
                <label>
                  {t.source}
                  <select
                    value={source}
                    onChange={(e) => update("source", e.target.value)}
                  >
                    <option value="">{t.all}</option>
                    {(["club", "outing", "competition"] as const).map((s) => (
                      <option key={s} value={s}>
                        {t[s]}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t.search}
                  <input
                    type="search"
                    value={query.get("q") || ""}
                    onChange={(e) => update("q", e.target.value)}
                  />
                </label>
              </div>
              <div className="calendar-switch">
                <div>
                  {["agenda", "month"].map((v) => (
                    <button
                      key={v}
                      aria-pressed={view === v}
                      onClick={() => update("view", v)}
                    >
                      {t[v as "agenda" | "month"]}
                    </button>
                  ))}
                </div>
                <button onClick={() => openForm()}>
                  <Plus size={18} />
                  {t.create}
                </button>
              </div>
              {load === "loading" && <p role="status">{t.loading}</p>}
              {load === "failed" && (
                <p role="alert">
                  {t.failed}{" "}
                  <button onClick={() => setRevision((x) => x + 1)}>
                    {t.retry}
                  </button>
                </p>
              )}
              {view === "month" ? (
                <div className="calendar-month">
                  <div className="calendar-weekdays">
                    {Array.from({ length: 7 }, (_, i) => (
                      <span key={i}>
                        {new Intl.DateTimeFormat(lang, {
                          weekday: "short",
                          timeZone: "Europe/Paris",
                        }).format(
                          new Date(
                            `2026-01-${String(5 + i).padStart(2, "0")}T12:00:00Z`,
                          ),
                        )}
                      </span>
                    ))}
                  </div>
                  {Array.from(
                    {
                      length:
                        (new Date(month + "-01T12:00:00").getDay() + 6) % 7,
                    },
                    (_, i) => (
                      <div aria-hidden="true" key={"blank" + i} />
                    ),
                  )}
                  {Array.from(
                    {
                      length: new Date(
                        Number(month.slice(0, 4)),
                        Number(month.slice(5)),
                        0,
                      ).getDate(),
                    },
                    (_, i) => {
                      const day = `${month}-${String(i + 1).padStart(2, "0")}`;
                      return (
                        <div key={day}>
                          <button
                            aria-label={dateLabel(day)}
                            onClick={() => {
                              const q = new URLSearchParams(query);
                              q.set("date", day);
                              q.set("view", "agenda");
                              setQuery(q);
                            }}
                          >
                            {i + 1}
                          </button>
                          {matching
                            .filter((e) => e.date === day)
                            .map((e) => (
                              <Link
                                key={e.id}
                                to={`/calendar/${encodeURIComponent(e.id)}${location.search}`}
                                aria-label={`${dateLabel(day)} ${e.title} ${e.time}`}
                              >
                                <span
                                  className={`calendar-dot calendar-dot-${e.source}`}
                                />
                                <span className="calendar-month-title">
                                  {e.time} {e.title}
                                </span>
                              </Link>
                            ))}
                        </div>
                      );
                    },
                  )}
                </div>
              ) : (
                <div className="calendar-agenda">{matching.map(row)}</div>
              )}
              {!matching.length && <p className="calendar-empty">{t.empty}</p>}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
