import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  CalendarError, calendarApi, type EventDetail, type OccurrenceDetail, type ScheduleEdit, type SchedulePreview, type Scope,
} from "./api";
import { validDate } from "./model";
import { keepFocusOnPress, useCalendarStrings, type CalendarContext } from "./useStrings";
import PageLoading from "../components/PageLoading";

const TIME = /^\d{2}:\d{2}$/;

type Form = {
  scope: Scope; date: string; start: string; end: string; venue: string; cancel: boolean
  weekdays: number[]; patternStart: string; patternEnd: string; until: string; excluded: string[]; newExcluded: string
};

/** Scoped schedule change: choose sessions, preview the exact effect on
 * dates and responses, then apply. The server recomputes the plan and
 * refuses a stale preview; inputs are always kept. */
export default function ScheduleEditor({ ctx, occurrenceId }: { ctx: CalendarContext; occurrenceId: number }) {
  const { t, lang } = useCalendarStrings();
  const navigate = useNavigate();
  const location = useLocation();
  const [occ, setOcc] = useState<OccurrenceDetail | null>(null);
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [initialVenue, setInitialVenue] = useState("");
  const [preview, setPreview] = useState<SchedulePreview | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let live = true;
    calendarApi.occurrence(occurrenceId).then(async (o) => {
      const e = await calendarApi.event(o.event.id);
      if (!live) return;
      if (!e.can_edit) { setMissing(true); return; }
      setOcc(o);
      setEvent(e);
      if (revision > 0) return; // reload after a conflict: keep the user's inputs
      const r = e.recurrence;
      setInitialVenue(o.venue_name ?? "");
      setForm({
        scope: r && !e.imported ? "future" : "one", date: o.local_date, start: o.local_start ?? "", end: o.local_end ?? "",
        venue: o.venue_name ?? "", cancel: false, weekdays: r?.weekdays ?? [], patternStart: r?.start_time ?? "",
        patternEnd: r?.end_time ?? "", until: r?.until_date ?? "", excluded: r?.excluded_dates ?? [], newExcluded: "",
      });
    }).catch(() => { if (live) setMissing(true); });
    return () => { live = false; };
  }, [occurrenceId, revision]);

  if (missing) return <p role="alert">{t.unavailable}</p>;
  if (!occ || !event || !form) return <PageLoading message={t.loading} />;
  const series = !!event.recurrence && !event.imported;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => { setForm({ ...form, [k]: v }); setPreview(null); };
  const dayLabel = (d: string) => new Intl.DateTimeFormat(lang, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(`${d}T12:00:00Z`));
  const slot = (s: { date: string; start: string | null; end: string | null }) =>
    `${dayLabel(s.date)}${s.start ? ` ${s.start}–${s.end}` : ""}`;

  const body = (): ScheduleEdit | null => {
    const base = { expected_version: event.version, scope: form.scope, occurrence_id: occ.id };
    const venue = form.venue.trim() !== initialVenue.trim() ? { venue_name: form.venue.trim() || null } : {};
    if (form.scope === "one") {
      if (form.cancel) return { ...base, cancel: true };
      if (!validDate(form.date) || !TIME.test(form.start) || !TIME.test(form.end) || form.end <= form.start) return null;
      return { ...base, ...venue, when: { all_day: false, start_local: `${form.date}T${form.start}`, end_local: `${form.date}T${form.end}` } };
    }
    if (!form.weekdays.length || !TIME.test(form.patternStart) || !TIME.test(form.patternEnd)
      || form.patternEnd <= form.patternStart || !validDate(form.until)) return null;
    return { ...base, ...venue, weekdays: form.weekdays, start_time: form.patternStart, end_time: form.patternEnd,
      until_date: form.until, excluded_dates: form.excluded };
  };
  const failure = (e: unknown) => {
    if (e instanceof CalendarError && (e.code === "stale_version" || e.code === "stale_preview")) {
      setPreview(null);
      setRevision((r) => r + 1); // fetch the new version; inputs stay
      return t.stalePreview;
    }
    if (e instanceof CalendarError && e.code === "imported_series") return t.importedSeries;
    if (e instanceof CalendarError && e.status === 403) return t.forbidden;
    if (e instanceof CalendarError && e.status === 422 && e.message) return `${t.error} (${e.message})`;
    return t.retrySave;
  };
  const runPreview = async (e: React.FormEvent) => {
    e.preventDefault();
    const b = body();
    if (!b) { setError(t.error); return; }
    setBusy(true); setError(null);
    try { setPreview(await calendarApi.previewSchedule(event.id, b)); } catch (err) { setError(failure(err)); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    const b = body();
    if (!b || !preview) return;
    setBusy(true); setError(null);
    try {
      await calendarApi.applySchedule(event.id, { ...b, plan_hash: preview.plan_hash });
      ctx.refresh();
      navigate(`/calendar/o/${occ.id}${location.search}`, { replace: true });
    } catch (err) { setError(failure(err)); } finally { setBusy(false); }
  };
  const toggleDay = (d: number) => set("weekdays", form.weekdays.includes(d) ? form.weekdays.filter((x) => x !== d) : [...form.weekdays, d].sort());
  const plan = preview?.plan;
  const counts = (r: { interested: number; maybe: number; absences: number }) => t.responseCounts(r.interested, r.maybe, r.absences);

  return (
    <form noValidate onSubmit={runPreview} className="calendar-form" aria-busy={busy}>
      <h1>{t.editSchedule}</h1>
      <p>{event.title} · {slot({ date: occ.local_date, start: occ.local_start, end: occ.local_end })}</p>
      {event.imported && <p role="status" className="calendar-notice">{t.importedSeries}</p>}
      <fieldset className="calendar-scope">
        <legend>{t.scope}</legend>
        {(series ? (["one", "future", "all"] as Scope[]) : (["one"] as Scope[])).map((s) => (
          <label key={s} className="calendar-check calendar-scope-option">
            <input type="radio" {...keepFocusOnPress} name="scope" value={s} checked={form.scope === s} onChange={() => set("scope", s)} />
            <span><strong>{t[`scope_${s}`]}</strong><small>{t[`scope_${s}_help`]}</small></span>
          </label>
        ))}
      </fieldset>
      {form.scope === "one" ? (
        <>
          <label className="calendar-check"><input type="checkbox" {...keepFocusOnPress} checked={form.cancel} onChange={(e) => set("cancel", e.target.checked)} />{t.cancelThisSession}</label>
          {!form.cancel && (
            <>
              <label>{t.startDate}<input type="date" value={form.date} onChange={(e) => set("date", e.target.value)} /></label>
              <div className="calendar-form-row">
                <label>{t.start}<input type="time" value={form.start} onChange={(e) => set("start", e.target.value)} /></label>
                <label>{t.end}<input type="time" value={form.end} onChange={(e) => set("end", e.target.value)} /></label>
              </div>
            </>
          )}
        </>
      ) : (
        <>
          <fieldset className="calendar-weekdays-pick">
            <legend>{t.weekdays}</legend>
            {t.weekdayShort.map((label, i) => (
              <button type="button" {...keepFocusOnPress} key={label} aria-pressed={form.weekdays.includes(i + 1)} onClick={() => toggleDay(i + 1)}>{label}</button>
            ))}
          </fieldset>
          <div className="calendar-form-row">
            <label>{t.start}<input type="time" value={form.patternStart} onChange={(e) => set("patternStart", e.target.value)} /></label>
            <label>{t.end}<input type="time" value={form.patternEnd} onChange={(e) => set("patternEnd", e.target.value)} /></label>
          </div>
          <label>{t.seasonEnd}<input type="date" value={form.until} onChange={(e) => set("until", e.target.value)} /></label>
          <ExcludedDates t={t} dates={form.excluded} onChange={(d) => set("excluded", d)} label={dayLabel} />
        </>
      )}
      {!(form.scope === "one" && form.cancel) && (
        <label>{t.venue}<input type="text" maxLength={200} value={form.venue} onChange={(e) => set("venue", e.target.value)} /></label>
      )}
      {error && <p role="alert" className="calendar-error">{error}</p>}
      {plan && preview && (
        <section className="calendar-preview" aria-labelledby="calendar-preview-title" aria-live="polite">
          <h2 id="calendar-preview-title">{t.previewTitle}</h2>
          {!plan.moved.length && !plan.cancelled.length && !plan.created.length && <p>{t.previewNothing}</p>}
          {plan.moved.length > 0 && (<><h3>{t.previewMoved} ({plan.moved.length})</h3>
            <ul>{plan.moved.map((m) => <li key={m.occurrence_id}>{slot(m.from)} → {slot(m.to)} <small>{counts(m.responses)}</small></li>)}</ul></>)}
          {plan.cancelled.length > 0 && (<><h3>{t.previewCancelled} ({plan.cancelled.length})</h3>
            <ul>{plan.cancelled.map((c) => <li key={c.occurrence_id}>{slot(c)} <small>{counts(c.responses)}</small></li>)}</ul></>)}
          {plan.created.length > 0 && (<><h3>{t.previewCreated} ({plan.created.length})</h3>
            <ul>{plan.created.map((c) => <li key={c.series_date}>{slot(c)}</li>)}</ul></>)}
          {plan.kept.length > 0 && (<><h3>{t.previewKept} ({plan.kept.length})</h3>
            <ul>{plan.kept.map((k) => <li key={k.occurrence_id}>{slot(k)} — {k.reason === "cancelled" ? t.keptCancelled : t.keptEdited}</li>)}</ul></>)}
          {plan.unchanged > 0 && <p>{t.previewUnchanged(plan.unchanged)}</p>}
          {preview.summary.responses_kept > 0 && <p>{t.responsesKept(preview.summary.responses_kept)}</p>}
          {preview.summary.responses_on_cancelled > 0 && <p role="status" className="calendar-notice">{t.responsesCancelled(preview.summary.responses_on_cancelled)}</p>}
        </section>
      )}
      <div className="calendar-actions">
        {preview ? (
          <>
            <button type="button" disabled={busy || (!plan!.moved.length && !plan!.cancelled.length && !plan!.created.length)}
              onClick={apply} {...keepFocusOnPress}>{busy ? t.saving : t.applyChanges}</button>
            <button type="button" {...keepFocusOnPress} disabled={busy} onClick={() => setPreview(null)}>{t.editAgain}</button>
          </>
        ) : (
          <button type="submit" disabled={busy} {...keepFocusOnPress}>{busy ? t.loading : t.previewChanges}</button>
        )}
        <Link to={`/calendar/o/${occ.id}${location.search}`}>{t.discard}</Link>
      </div>
    </form>
  );
}

export function ExcludedDates({ t, dates, onChange, label }: {
  t: ReturnType<typeof useCalendarStrings>["t"]; dates: string[]; onChange: (d: string[]) => void; label: (d: string) => string
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    if (validDate(draft) && !dates.includes(draft)) onChange([...dates, draft].sort());
    setDraft("");
  };
  return (
    <fieldset className="calendar-excluded">
      <legend>{t.excludedDates}</legend>
      <div className="calendar-form-row">
        <input type="date" aria-label={t.excludedDates} value={draft} onChange={(e) => setDraft(e.target.value)} />
        <button type="button" disabled={!validDate(draft)} onClick={add} {...keepFocusOnPress}>{t.addDate}</button>
      </div>
      {dates.length > 0 && (
        <ul className="calendar-chips">
          {dates.map((d) => (
            <li key={d}>{label(d)}
              <button type="button" {...keepFocusOnPress} aria-label={t.removeDate(label(d))} onClick={() => onChange(dates.filter((x) => x !== d))}>×</button>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}
