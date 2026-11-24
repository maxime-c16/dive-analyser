import React, { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, FileUp, Trash2 } from "lucide-react";
import {
  CalendarError, calendarApi, type EventDetail, type MeetEntry, type MeetPreview, type MeetResultsPage,
} from "./api";
import { useCalendarStrings } from "./useStrings";
import PageLoading from "../components/PageLoading";
import MemberAvatar from "../components/MemberAvatar";

type State = { status: "loading" } | { status: "missing" } | { status: "failed" } |
  { status: "ready"; event: EventDetail; page: MeetResultsPage };

/** Official results of a competition, as published on the meet's sheet
 * (docs/SCORING.md §4): shown as printed, never recomputed or re-ranked. */
export default function MeetResults({ eventId }: { eventId: number }) {
  const { t, lang } = useCalendarStrings();
  const [state, setState] = useState<State>({ status: "loading" });
  const [revision, setRevision] = useState(0);
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState<number | null>(null);
  const tabs = useRef<HTMLDivElement>(null);
  const shownId = useRef<number | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([calendarApi.event(eventId), calendarApi.results(eventId)])
      .then(([event, page]) => { if (live) setState({ status: "ready", event, page }); })
      .catch((e) => { if (live) setState({ status: e instanceof CalendarError && e.status === 404 ? "missing" : "failed" }); });
    return () => { live = false; };
  }, [eventId, revision]);

  // Keep the selected event tab in view (it may be far right in a long list).
  useEffect(() => {
    const el = tabs.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    const id = Number(el?.dataset.id);
    if (!el || id === shownId.current) return;
    shownId.current = id;
    el.scrollIntoView?.({ block: "nearest", inline: "center" });
  });

  if (state.status === "loading") return <PageLoading message={t.loading} />;
  if (state.status === "missing") return <p role="alert" className="cal-notice">{t.unavailable}</p>;
  if (state.status === "failed") return <p role="alert" className="cal-notice is-bad">{t.failed} <button className="ca-pill" onClick={() => setRevision((r) => r + 1)}>{t.retry}</button></p>;

  const { event, page } = state;
  const results = page.results;
  const events = results?.events ?? [];
  const selectedId = Number(params.get("epreuve"));
  // Open on the viewer's own event unless one was picked.
  const current = events.find((e) => e.id === selectedId) ?? events.find((e) => e.entries.some((en) => en.is_me)) ?? events[0];
  const date = results?.meet_date
    ? new Intl.DateTimeFormat(lang, { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
      .format(new Date(`${results.meet_date}T12:00:00Z`))
    : null;
  const select = (id: number) => {
    setOpen(null);
    setParams((p) => { const next = new URLSearchParams(p); next.set("epreuve", String(id)); return next; }, { replace: true });
  };

  return (
    <article className="cal-detail cal-src-competition meet">
      <header className="cal-hero-text ca-arrive">
        <span className="cal-tag"><i className="cal-dot" />{t.results}</span>
        <h1 className="meet-title">{event.title}</h1>
        {date && <p className="meet-date">{date}</p>}
      </header>

      {page.can_import && (
        <ImportPanel eventId={eventId} hasResults={!!results}
          onSaved={(next) => setState({ status: "ready", event, page: next })} />
      )}

      {!results && !page.can_import && <p className="cal-notice">{t.noResults}</p>}

      {current && (
        <>
          {events.length > 1 && (
            <div ref={tabs} className="meet-events" role="tablist" aria-label={t.results}>
              {events.map((e) => (
                <button key={e.id} data-id={e.id} type="button" role="tab" className="ca-pill" aria-selected={e.id === current.id}
                  aria-pressed={e.id === current.id} onClick={() => select(e.id)}>{e.title}</button>
              ))}
            </div>
          )}
          <section className="ca-panel meet-board" role="tabpanel" aria-label={current.title}>
            <ol className="meet-ranking">
              {current.entries.map((entry) => (
                <Entry key={entry.id} entry={entry} open={open === entry.id}
                  toggle={() => setOpen((o) => (o === entry.id ? null : entry.id))} />
              ))}
            </ol>
          </section>
        </>
      )}
    </article>
  );
}

function useNumber() {
  const { lang } = useCalendarStrings();
  const two = new Intl.NumberFormat(lang, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const one = new Intl.NumberFormat(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const any = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
  return { two: (n: number) => two.format(n), one: (n: number) => one.format(n), any: (n: number) => any.format(n) };
}

function Entry({ entry, open, toggle }: { entry: MeetEntry; open: boolean; toggle: () => void }) {
  const { t } = useCalendarStrings();
  const fmt = useNumber();
  const podium = entry.rank && entry.rank <= 3 && !entry.status ? ` is-p${entry.rank}` : "";
  return (
    <li className={`meet-entry${open ? " is-open" : ""}${entry.is_me ? " is-me" : ""}`}>
      <button type="button" className="meet-entry-row" aria-expanded={open} onClick={toggle}>
        <span className={`meet-rank${podium}`}>{entry.rank ?? "–"}</span>
        {entry.account && <MemberAvatar member={entry.account} size={32} />}
        <span className="meet-who">
          <b>{entry.diver_name}</b>
          <small>{[entry.club_name, entry.birth_year].filter(Boolean).join(" · ")}</small>
        </span>
        {entry.status && <span className="cal-chip is-bad">{t[`status_${entry.status}`]}</span>}
        {entry.guest && <span className="cal-chip">{t.guest}</span>}
        <span className="meet-total">{fmt.two(entry.total)}</span>
        <ChevronDown size={16} aria-hidden="true" className="meet-chevron" />
      </button>
      {open && entry.account && (
        <Link className="meet-profile" to={`/users/${entry.account.user_id}`}>
          {entry.account.display_name}<ChevronRight size={14} aria-hidden="true" />
        </Link>
      )}
      {open && entry.dives.length > 0 && (
        <ol className="meet-dives">
          {entry.dives.map((d, i) => (
            <li key={i} className="meet-dive">
              <span className="meet-dive-code">
                <b>{d.dive_code}</b>
                <small>{fmt.any(d.height)} m · {fmt.one(d.dd)}</small>
              </span>
              <span className="meet-judges" aria-label={`${t.judges} ${d.judges.map(fmt.one).join(", ")}`}>
                {d.judges.map((j, k) => <span key={k}>{fmt.one(j)}</span>)}
                {d.penalty ? <span className="cal-chip is-warn">{t.penalty[d.penalty] ?? d.penalty}</span> : null}
              </span>
              <span className="meet-points"><b>{fmt.two(d.points)}</b><small>{fmt.two(d.running_total)}</small></span>
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}

function ImportPanel({ eventId, hasResults, onSaved }: {
  eventId: number; hasResults: boolean; onSaved: (page: MeetResultsPage) => void;
}) {
  const { t, lang } = useCalendarStrings();
  const input = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<MeetPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const fail = (e: unknown) => {
    const key = e instanceof CalendarError ? `meetError_${e.code}` : "";
    setError((t as Record<string, unknown>)[key] as string ?? (e instanceof CalendarError && e.status === 403 ? t.forbidden : t.retrySave));
  };
  const reset = () => { generation.current += 1; setFile(null); setPreview(null); setBusy(false); if (input.current) input.current.value = ""; };
  // Each step is tagged: a later pick, discard or save makes earlier answers stale.
  const run = async <T,>(work: () => Promise<T>, done: (value: T) => void) => {
    const mine = ++generation.current;
    setBusy(true); setError(null);
    try {
      const value = await work();
      if (generation.current === mine) done(value);
    } catch (e) {
      if (generation.current === mine) fail(e);
    } finally {
      if (generation.current === mine) setBusy(false);
    }
  };
  const pick = (next: File | null) => {
    if (!next) return;
    setPreview(null); setFile(next);
    run(() => calendarApi.previewResults(eventId, next), setPreview);
  };
  const save = () => file && run(() => calendarApi.saveResults(eventId, file), (page) => { reset(); onSaved(page); });
  const remove = () => run(() => calendarApi.deleteResults(eventId), () => {
    setConfirming(false);
    onSaved({ can_import: true, available: false, results: null });
  });
  const day = (d: string) => new Intl.DateTimeFormat(lang, { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${d}T12:00:00Z`));

  return (
    <section className="ca-panel cal-list meet-import" aria-busy={busy}>
      <input ref={input} type="file" accept="application/pdf,.pdf" hidden
        onChange={(e) => pick(e.target.files?.[0] ?? null)} />
      {!preview && (
        <button type="button" className="cal-list-row" disabled={busy} onClick={() => input.current?.click()}>
          <FileUp size={18} aria-hidden="true" />
          <span className="cal-list-main"><b>{hasResults ? t.replaceResults : t.importResults}</b>{file && busy && <small>{file.name}</small>}</span>
        </button>
      )}
      {preview && (
        <div className="meet-preview">
          <b>{t.resultsCount(preview.events.length, preview.entry_count, preview.dive_count)}</b>
          {preview.linked_count > 0 && <small>{t.linkedAccounts(preview.linked_count)}</small>}
          <small>{file?.name}</small>
          {preview.date_matches === false && preview.meet_date && <p className="cal-notice">{t.dateMismatch(day(preview.meet_date))}</p>}
          {preview.replaces && <p className="cal-notice">{t.replacesResults}</p>}
          {preview.warnings.length > 0 && (
            <details className="meet-warnings">
              <summary>{t.linesToCheck(preview.warnings.length)}</summary>
              <ul>{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </details>
          )}
          <div className="cal-pills">
            <button type="button" className="ca-pill is-primary" disabled={busy} onClick={save}>{t.saveResults}</button>
            <button type="button" className="ca-pill" onClick={reset}>{t.discardImport}</button>
          </div>
        </div>
      )}
      {hasResults && !preview && !confirming && (
        <button type="button" className="cal-list-row is-danger" disabled={busy} onClick={() => setConfirming(true)}>
          <Trash2 size={18} aria-hidden="true" /><span className="cal-list-main"><b>{t.deleteResults}</b></span>
        </button>
      )}
      {confirming && (
        <div className="cal-list-row cal-confirm">
          <button type="button" className="ca-pill is-danger" disabled={busy} onClick={remove}>{t.confirmDelete}</button>
          <button type="button" className="ca-pill" disabled={busy} onClick={() => setConfirming(false)}>{t.keepIt}</button>
        </div>
      )}
      {error && <p role="alert" className="cal-notice is-bad">{error}</p>}
    </section>
  );
}
