import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  CalendarError, calendarApi, newIdempotencyKey, type Audience, type EventInput, type EventType,
  type ItineraryItem, type OccurrenceDetail, type When,
} from "./api";
import { addDays, isoWeekday, validDate, weeklyDates } from "./model";
import { ExcludedDates } from "./ScheduleEditor";
import { keepFocusOnPress, useCalendarStrings, type CalendarContext } from "./useStrings";
import PageLoading from "../components/PageLoading";

type Form = {
  calendar: string; // calendar id, or "personal"
  event_type: EventType; audience: Audience; publish: boolean; title: string; description: string
  venue_name: string; venue_address: string; map_url: string; all_day: boolean
  date: string; last_date: string; start: string; end: string
  repeat: boolean; weekdays: number[]; until: string; excluded: string[]
  itinerary: ItineraryItem[]; registration: string
};
const TIME = /^\d{2}:\d{2}$/;

function when(form: Pick<Form, "all_day" | "date" | "last_date" | "start" | "end">): When {
  return form.all_day
    ? { all_day: true, start_date: form.date, end_date: addDays(form.last_date || form.date, 1) }
    : { all_day: false, start_local: `${form.date}T${form.start}`, end_local: `${form.date}T${form.end}` };
}

function valid(form: Form): boolean {
  if (!form.title.trim() || !validDate(form.date)) return false;
  if (form.itinerary.some((b) => !validDate(b.local_date) || (b.start_time && b.end_time && b.end_time <= b.start_time))) return false;
  if (form.repeat && !form.all_day && (!form.weekdays.length || !validDate(form.until) || form.until < form.date)) return false;
  if (form.all_day) return !form.last_date || (validDate(form.last_date) && form.last_date >= form.date);
  return TIME.test(form.start) && TIME.test(form.end) && form.end > form.start;
}

function errorText(t: ReturnType<typeof useCalendarStrings>["t"], e: unknown): string {
  if (e instanceof CalendarError) {
    if (e.code === "stale_version") return t.stale;
    if (e.status === 403) return t.forbidden;
    if (e.status === 422 && e.message) return `${t.error} (${e.message})`;
  }
  return t.retrySave;
}

/** Warn before leaving with unsaved input (browser navigation). */
function useLeaveGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
}

export default function EventForm({ ctx, eventId, defaultDate }: { ctx: CalendarContext; eventId?: number; defaultDate: string }) {
  const { t, lang } = useCalendarStrings();
  const navigate = useNavigate();
  const location = useLocation();
  const blank: Form = {
    calendar: "personal", event_type: "outing", audience: "invited", publish: true, title: "", description: "",
    venue_name: "", venue_address: "", map_url: "", all_day: false, date: defaultDate, last_date: "",
    start: "10:00", end: "12:00", repeat: false, weekdays: [], until: "", excluded: [], itinerary: [], registration: "",
  };
  const [form, setForm] = useState<Form>(blank);
  const [initial, setInitial] = useState<Form>(blank);
  const [version, setVersion] = useState<number | null>(null);
  const [single, setSingle] = useState(true);
  const [loading, setLoading] = useState(!!eventId);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [reloading, setReloading] = useState(false);
  // One key per create attempt: a retried submit after a network error
  // replays the same event instead of creating a duplicate.
  const key = useRef(newIdempotencyKey());

  const writable = ctx.calendars.filter((c) => c.can_publish && c.kind !== "personal");
  const personal = ctx.calendars.find((c) => c.kind === "personal" && c.can_publish);
  const selected = form.calendar === "personal" ? null : ctx.calendars.find((c) => String(c.id) === form.calendar);
  const audiences: Audience[] = selected ? selected.allowed_audiences : ["invited", "community"];

  useEffect(() => {
    if (!eventId) return;
    let live = true;
    calendarApi.event(eventId).then((e) => {
      if (!live) return;
      if (!e.can_edit) { setMissing(true); setLoading(false); return; }
      const o = e.occurrences[0];
      const loaded: Form = {
        calendar: e.calendar_kind === "personal" ? "personal" : String(e.calendar_id), event_type: e.event_type,
        audience: e.audience, publish: e.status !== "draft", title: e.title, description: e.description,
        venue_name: e.venue_name ?? "", venue_address: e.venue_address ?? "", map_url: e.map_url ?? "",
        all_day: !!o?.is_all_day, date: o?.local_date ?? defaultDate,
        last_date: o?.is_all_day && o.end_date ? addDays(o.end_date, -1) : "",
        start: o?.local_start ?? "10:00", end: o?.local_end ?? "12:00", repeat: !!e.recurrence,
        weekdays: e.recurrence?.weekdays ?? [], until: e.recurrence?.until_date ?? "",
        excluded: e.recurrence?.excluded_dates ?? [], itinerary: e.itinerary ?? [],
        registration: e.resources.find((r) => r.kind === "registration")?.url ?? "",
      };
      setSingle(e.occurrences.length === 1 && !e.recurrence);
      setVersion(e.version);
      setInitial(loaded);
      if (revision === 0) setForm(loaded); // a reload after a conflict keeps the user's input
      else { setError(null); setReloading(false); } // now based on the latest version
      setLoading(false);
    }).catch(() => { if (live) { setMissing(true); setLoading(false); } });
    return () => { live = false; };
  }, [eventId, revision]);

  useEffect(() => {
    if (!audiences.includes(form.audience)) setForm((f) => ({ ...f, audience: audiences[0] }));
  }, [form.calendar]);

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(initial), [form, initial]);
  useLeaveGuard(dirty && !busy);
  if (loading) return <PageLoading message={t.loading} />;
  if (missing) return <p role="alert">{t.unavailable}</p>;

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid(form)) { setError(t.error); return; }
    const repeating = form.repeat && !form.all_day && form.event_type !== "camp";
    setBusy(true);
    setError(null);
    const body: EventInput = {
      calendar_id: form.calendar === "personal" ? (personal?.id ?? null) : Number(form.calendar),
      event_type: form.event_type, audience: form.audience,
      status: form.publish || form.calendar === "personal" ? "published" : "draft",
      title: form.title.trim(), description: form.description, venue_name: form.venue_name.trim() || null,
      venue_address: form.venue_address.trim() || null, map_url: form.map_url.trim() || null,
      timezone: "Europe/Paris", when: when(form),
      itinerary: form.itinerary.map((b) => ({ ...b, start_time: b.start_time || null, end_time: b.end_time || null,
        venue_name: b.venue_name?.trim() || null, label: b.label?.trim() || null })),
      registration_url: form.registration.trim() || null,
      ...(repeating && !eventId ? { recurrence: { weekdays: form.weekdays, until_date: form.until, excluded_dates: form.excluded } } : {}),
    };
    try {
      let saved;
      if (eventId && version !== null) {
        const { calendar_id: _c, status, recurrence: _r, ...rest } = body;
        void _c; void _r;
        saved = await calendarApi.updateEvent(eventId, {
          ...rest, expected_version: version, ...(status === "published" && !initial.publish ? { status } : {}),
          ...(single ? {} : { when: undefined, itinerary: undefined }),
        });
      } else {
        saved = await calendarApi.createEvent(body, key.current);
        key.current = newIdempotencyKey();
      }
      setInitial(form);
      ctx.refresh();
      const occurrence = saved.occurrences[0];
      navigate(occurrence ? `/calendar/o/${occurrence.id}${location.search}` : `/calendar${location.search}`, { replace: true });
    } catch (err) {
      setError(errorText(t, err)); // input stays in the form
    } finally { setBusy(false); }
  };
  const field = (k: keyof Form, label: string, type = "text", extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label>{label}<input type={type} value={form[k] as string} onChange={(e) => set(k, e.target.value as never)} {...extra} /></label>
  );
  const clubCalendar = form.calendar !== "personal";
  const canRepeat = !eventId && !form.all_day && form.event_type !== "camp";
  const sessionCount = form.repeat ? weeklyDates(form.date, form.until, form.weekdays, form.excluded).length : 0;
  const dayLabel = (d: string) => new Intl.DateTimeFormat(lang, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(`${d}T12:00:00Z`));
  const setBlock = (i: number, patch: Partial<ItineraryItem>) =>
    set("itinerary", form.itinerary.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const showItinerary = single && (form.event_type === "camp" || form.itinerary.length > 0);

  return (
    <form noValidate onSubmit={submit} className="calendar-form" aria-busy={busy}>
      <h1>{eventId ? t.editEvent : t.create}</h1>
      {!eventId && (
        <label>{t.calendarField}
          <select value={form.calendar} onChange={(e) => set("calendar", e.target.value)}>
            <option value="personal">{t.personal}</option>
            {writable.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      )}
      <label>{t.typeField}
        <select value={form.event_type} onChange={(e) => set("event_type", e.target.value as EventType)}>
          {(["outing", "training", "camp", "competition", "other"] as EventType[]).map((v) => (
            <option key={v} value={v}>{t[`type_${v}` as keyof typeof t] as string}</option>))}
        </select>
      </label>
      <label>{t.audienceField}
        <select value={form.audience} onChange={(e) => set("audience", e.target.value as Audience)}>
          {audiences.map((v) => <option key={v} value={v}>{t[`audience_${v}` as keyof typeof t] as string}</option>)}
        </select>
      </label>
      {field("title", t.titleField, "text", { required: true, maxLength: 200 })}
      {single && (
        <>
          <label className="calendar-check"><input type="checkbox" {...keepFocusOnPress} checked={form.all_day} onChange={(e) => set("all_day", e.target.checked)} />{t.allDay}</label>
          {field("date", t.startDate, "date", { required: true })}
          {form.all_day ? field("last_date", t.endDate, "date") : (
            <div className="calendar-form-row">
              {field("start", t.start, "time", { required: true })}
              {field("end", t.end, "time", { required: true })}
            </div>
          )}
          {canRepeat && (
            <label className="calendar-check"><input type="checkbox" {...keepFocusOnPress} checked={form.repeat} onChange={(e) => { const repeat = e.target.checked; setForm((f) => ({
              ...f, repeat,
              weekdays: f.weekdays.length || !validDate(f.date) ? f.weekdays : [isoWeekday(f.date)] })); }} />{t.repeatWeekly}</label>
          )}
          {canRepeat && form.repeat && (
            <>
              <fieldset className="calendar-weekdays-pick">
                <legend>{t.weekdays}</legend>
                {t.weekdayShort.map((label, i) => (
                  <button type="button" {...keepFocusOnPress} key={label} aria-pressed={form.weekdays.includes(i + 1)}
                    onClick={() => set("weekdays", form.weekdays.includes(i + 1) ? form.weekdays.filter((d) => d !== i + 1) : [...form.weekdays, i + 1].sort())}>{label}</button>
                ))}
              </fieldset>
              {field("until", t.seasonEnd, "date", { required: true, min: form.date })}
              <ExcludedDates t={t} dates={form.excluded} onChange={(d) => set("excluded", d)} label={dayLabel} />
              <p role="status">{t.sessionCount(sessionCount)} {t.seriesLimit}</p>
            </>
          )}
        </>
      )}
      {!single && initial.repeat && <p className="calendar-notice">{t.scope_all_help}</p>}
      {showItinerary && (
        <fieldset className="calendar-itinerary-edit">
          <legend>{t.itinerary}</legend>
          <p>{t.itineraryNote}</p>
          {form.itinerary.map((b, i) => (
            <div key={i} className="calendar-itinerary-block">
              <label>{t.blockDay}<input type="date" value={b.local_date} onChange={(e) => setBlock(i, { local_date: e.target.value })} /></label>
              <div className="calendar-form-row">
                <label>{t.start}<input type="time" value={b.start_time ?? ""} onChange={(e) => setBlock(i, { start_time: e.target.value })} /></label>
                <label>{t.end}<input type="time" value={b.end_time ?? ""} onChange={(e) => setBlock(i, { end_time: e.target.value })} /></label>
              </div>
              <label>{t.venue}<input type="text" maxLength={200} value={b.venue_name ?? ""} onChange={(e) => setBlock(i, { venue_name: e.target.value })} /></label>
              <label>{t.blockLabel}<input type="text" maxLength={200} value={b.label ?? ""} onChange={(e) => setBlock(i, { label: e.target.value })} /></label>
              <button type="button" {...keepFocusOnPress} onClick={() => set("itinerary", form.itinerary.filter((_b, j) => j !== i))}>{t.removeBlock}</button>
            </div>
          ))}
          {form.itinerary.length < 20 && (
            <button type="button" {...keepFocusOnPress} onClick={() => set("itinerary", [...form.itinerary, {
              local_date: form.itinerary[form.itinerary.length - 1]?.local_date ?? form.date, start_time: "", end_time: "",
              venue_name: form.itinerary[form.itinerary.length - 1]?.venue_name ?? "", label: "" }])}>{t.addBlock}</button>
          )}
        </fieldset>
      )}
      {field("venue_name", t.venue, "text", { maxLength: 200 })}
      {field("venue_address", t.address, "text", { maxLength: 300 })}
      {field("map_url", t.mapLink, "url", { maxLength: 500 })}
      {(form.event_type === "camp" || form.event_type === "competition" || form.registration) && (
        <>
          {field("registration", t.registrationLink, "url", { maxLength: 1000 })}
          <p>{t.registrationNote}</p>
        </>
      )}
      <label>{t.description}<textarea value={form.description} maxLength={4000} rows={4} onChange={(e) => set("description", e.target.value)} /></label>
      {clubCalendar && !(eventId && initial.publish) && (
        <label className="calendar-check"><input type="checkbox" checked={form.publish} onChange={(e) => set("publish", e.target.checked)} />{t.publishNow}</label>
      )}
      {clubCalendar && !form.publish && <p>{t.saveDraft}</p>}
      {error && (
        <p role="alert" className="calendar-error">{error}{" "}
          {error === t.stale && <button type="button" disabled={reloading} onClick={() => { setReloading(true); setRevision((r) => r + 1); }}>{t.reload}</button>}
        </p>
      )}
      <div className="calendar-actions">
        <button type="submit" disabled={busy || reloading} {...keepFocusOnPress}>{busy ? t.saving : t.save}</button>
        <Link to={`/calendar${location.search}`} onClick={(e) => { if (dirty && !window.confirm(t.leaveWarning)) e.preventDefault(); }}>{t.discard}</Link>
      </div>
    </form>
  );
}

/** One session of a multi-date event (e.g. an imported club schedule). */
export function OccurrenceForm({ ctx, occurrenceId }: { ctx: CalendarContext; occurrenceId: number }) {
  const { t } = useCalendarStrings();
  const navigate = useNavigate();
  const location = useLocation();
  const [occ, setOcc] = useState<OccurrenceDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [form, setForm] = useState({ all_day: false, date: "", last_date: "", start: "", end: "", venue: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [reloading, setReloading] = useState(false);
  useEffect(() => {
    calendarApi.occurrence(occurrenceId).then((o) => {
      if (!o.can_edit) { setMissing(true); return; }
      setOcc(o);
      if (revision > 0) { setError(null); setReloading(false); }
      if (revision === 0) setForm({ all_day: o.is_all_day, date: o.local_date,
        last_date: o.is_all_day && o.end_date ? addDays(o.end_date, -1) : "",
        start: o.local_start ?? "", end: o.local_end ?? "", venue: o.venue_name ?? "" });
    }).catch(() => setMissing(true));
  }, [occurrenceId, revision]);
  if (missing) return <p role="alert">{t.unavailable}</p>;
  if (!occ) return <PageLoading message={t.loading} />;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = validDate(form.date) && (form.all_day || (TIME.test(form.start) && TIME.test(form.end) && form.end > form.start));
    if (!ok) { setError(t.error); return; }
    setBusy(true);
    setError(null);
    try {
      await calendarApi.updateOccurrence(occ.id, { expected_version: occ.version, when: when(form), venue_name: form.venue.trim() || null });
      ctx.refresh();
      navigate(`/calendar/o/${occ.id}${location.search}`, { replace: true });
    } catch (err) { setError(errorText(t, err)); } finally { setBusy(false); }
  };
  return (
    <form noValidate onSubmit={submit} className="calendar-form" aria-busy={busy}>
      <h1>{t.editSession}</h1>
      <p>{occ.event.title}</p>
      <label>{t.startDate}<input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></label>
      {!form.all_day && (
        <div className="calendar-form-row">
          <label>{t.start}<input type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></label>
          <label>{t.end}<input type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></label>
        </div>
      )}
      <label>{t.venue}<input type="text" maxLength={200} value={form.venue} onChange={(e) => setForm({ ...form, venue: e.target.value })} /></label>
      {error && <p role="alert" className="calendar-error">{error}{" "}
        {error === t.stale && <button type="button" disabled={reloading} onClick={() => { setReloading(true); setRevision((r) => r + 1); }}>{t.reload}</button>}</p>}
      <div className="calendar-actions">
        <button type="submit" disabled={busy || reloading} {...keepFocusOnPress}>{busy ? t.saving : t.save}</button>
        <Link to={`/calendar/o/${occ.id}${location.search}`}>{t.discard}</Link>
      </div>
    </form>
  );
}
