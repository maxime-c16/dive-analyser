import React, { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, FileUp, Trash2 } from "lucide-react";
import {
  CalendarError, calendarApi, type EventDetail, type MeetAccountCandidate, type MeetEntry, type MeetPreview, type MeetWarning, type MeetResultsPage,
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
  // Arrow keys / Home / End move between event tabs and select (ARIA tabs pattern).
  const onTabKey = (e: React.KeyboardEvent) => {
    const i = events.findIndex((ev) => ev.id === current?.id);
    const to = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? events.length - 1 : null;
    if (to === null || i < 0) return;
    e.preventDefault();
    const next = events[(to + events.length) % events.length];
    select(next.id);
    window.requestAnimationFrame(() => document.getElementById(`meet-tab-${next.id}`)?.focus());
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
            <div ref={tabs} className="meet-events" role="tablist" aria-label={t.results} onKeyDown={onTabKey}>
              {events.map((e) => (
                <button key={e.id} id={`meet-tab-${e.id}`} data-id={e.id} type="button" role="tab" className="ca-pill"
                  aria-selected={e.id === current.id} aria-controls="meet-panel" tabIndex={e.id === current.id ? 0 : -1}
                  onClick={() => select(e.id)}>{e.title}</button>
              ))}
            </div>
          )}
          <section id="meet-panel" className="ca-panel meet-board" role="tabpanel"
            {...(events.length > 1 ? { "aria-labelledby": `meet-tab-${current.id}` } : { "aria-label": current.title })}>
            <ol className="meet-ranking">
              {current.entries.map((entry) => (
                <Entry key={entry.id} entry={entry} open={open === entry.id} manage={!!page.can_manage_links}
                  reload={() => setRevision((r) => r + 1)}
                  toggle={() => setOpen((o) => (o === entry.id ? null : entry.id))} />
              ))}
            </ol>
          </section>
        </>
      )}
    </article>
  );
}

const formats = new Map<string, { two: (n: number) => string; one: (n: number) => string; any: (n: number) => string }>();
function useNumber() {
  const { lang } = useCalendarStrings();
  let f = formats.get(lang);
  if (!f) {
    const two = new Intl.NumberFormat(lang, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const one = new Intl.NumberFormat(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    const any = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
    f = { two: (n) => two.format(n), one: (n) => one.format(n), any: (n) => any.format(n) };
    formats.set(lang, f);
  }
  return f;
}

function Entry({ entry, open, toggle, manage, reload }: {
  entry: MeetEntry; open: boolean; toggle: () => void; manage: boolean; reload: () => void;
}) {
  const { t } = useCalendarStrings();
  const fmt = useNumber();
  const podium = entry.rank && entry.rank <= 3 && !entry.status ? ` is-p${entry.rank}` : "";
  // A row with nothing behind it (no dives, nothing to manage or open) is not a button.
  const expandable = entry.dives.length > 0 || !!entry.account || (manage && !!entry.linkable);
  const Row = expandable ? "button" : "div";
  return (
    <li className={`meet-entry${open ? " is-open" : ""}${entry.is_me ? " is-me" : ""}`}>
      <Row {...(expandable ? { type: "button" as const, "aria-expanded": open, onClick: toggle } : {})} className="meet-entry-row">
        <span className={`meet-rank${podium}`}>{entry.rank ?? "–"}</span>
        {entry.account && <MemberAvatar member={entry.account} size={32} />}
        <span className="meet-who">
          <b>{entry.diver_name}</b>
          <small>{[entry.club_name, entry.birth_year].filter(Boolean).join(" · ")}</small>
          {(entry.status || entry.guest) && (
            <span className="meet-chips">
              {entry.status && <span className="cal-chip is-bad">{t[`status_${entry.status}`]}</span>}
              {entry.guest && <span className="cal-chip">{t.guest}</span>}
            </span>
          )}
        </span>
        <span className="meet-total">{fmt.two(entry.total)}</span>
        {expandable ? <ChevronDown size={16} aria-hidden="true" className="meet-chevron" /> : <span className="meet-chevron" />}
      </Row>
      {open && manage && entry.linkable && <LinkManager entry={entry} reload={reload} />}
      {open && !manage && entry.account && (
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
              <span className="meet-judges">
                <span className="sr-only">{t.judges} </span>
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

/** Administrators: who this person is tied to, in every meet. */
function LinkManager({ entry, reload }: { entry: MeetEntry; reload: () => void }) {
  const { t } = useCalendarStrings();
  const [searching, setSearching] = useState(false);
  const [term, setTerm] = useState("");
  // Results always belong to the current query: cleared on every keystroke,
  // so a stale candidate can never be picked (a link applies to every meet).
  const [search, setSearch] = useState<{ status: "idle" | "loading" | "done" | "failed"; items: MeetAccountCandidate[] }>(
    { status: "idle", items: [] });
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const q = term.trim();
    if (q.length < 2) { setSearch({ status: "idle", items: [] }); return; }
    setSearch({ status: "loading", items: [] });
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      calendarApi.meetAccounts(q, controller.signal)
        .then((r) => { if (!controller.signal.aborted) setSearch({ status: "done", items: r.items }); })
        .catch(() => { if (!controller.signal.aborted) setSearch({ status: "failed", items: [] }); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [term]);
  const act = (work: () => Promise<unknown>) => {
    setBusy(true); setFailed(false);
    work().then(() => { setSearching(false); setTerm(""); reload(); })
      .catch(() => setFailed(true)).finally(() => setBusy(false));
  };
  const source = entry.link_source === "admin" ? t.linkAdmin : entry.link_source === "auto" ? t.linkAuto : null;
  return (
    <div className="meet-link" aria-busy={busy}>
      <div className="meet-link-now">
        {entry.account
          ? <Link className="meet-link-account" to={`/users/${entry.account.user_id}`}>
              <MemberAvatar member={entry.account} size={28} />{entry.account.display_name}
            </Link>
          : <span className="meet-link-none">{entry.link_source === "admin" ? t.neverLinked : t.noAccount}</span>}
        {source && <span className={`cal-chip${entry.link_source === "admin" ? " is-warn" : ""}`}>{source}</span>}
      </div>
      <div className="cal-pills">
        <button type="button" className="ca-pill" disabled={busy} aria-expanded={searching}
          onClick={() => setSearching((v) => !v)}>{t.linkAccount}</button>
        {!(entry.link_source === "admin" && !entry.account) && (
          <button type="button" className="ca-pill" disabled={busy} onClick={() => act(() => calendarApi.setResultLink(entry.id, null))}>{t.neverLink}</button>
        )}
        {entry.link_source === "admin" && (
          <button type="button" className="ca-pill" disabled={busy} onClick={() => act(() => calendarApi.clearResultLink(entry.id))}>{t.backToAuto}</button>
        )}
      </div>
      {searching && (
        <div className="meet-link-search">
          <label className="cal-search is-inline">
            <span className="sr-only">{t.searchAccounts}</span>
            <input type="search" autoFocus placeholder={t.searchAccounts} value={term} onChange={(e) => setTerm(e.target.value)} />
          </label>
          {search.status === "loading" && <p className="meet-link-state" role="status">{t.searching}</p>}
          {search.status === "done" && search.items.length === 0 && <p className="meet-link-state" role="status">{t.noAccountFound}</p>}
          {search.status === "failed" && <p className="meet-link-state is-bad" role="alert">{t.searchFailed}</p>}
          {search.items.map((a) => (
            <button key={a.user_id} type="button" className="meet-link-candidate" disabled={busy || a.user_id === entry.account?.user_id}
              onClick={() => act(() => calendarApi.setResultLink(entry.id, a.user_id))}>
              <MemberAvatar member={a} size={28} />
              <span className="cal-list-main"><b>{a.display_name}</b>{a.diver_names.length > 0 && <small>{a.diver_names.join(", ")}</small>}</span>
            </button>
          ))}
        </div>
      )}
      {failed && <p role="alert" className="cal-notice is-bad">{t.retrySave}</p>}
    </div>
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
        onChange={(e) => { pick(e.target.files?.[0] ?? null); e.target.value = ""; }} />
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
              <ul>{preview.warnings.map((w, i) => <li key={i}>{(t.meetWarning[w.kind] as (x: MeetWarning) => string)?.(w) ?? w.kind}</li>)}</ul>
              {preview.warnings_truncated && <p>{t.warningsMore}</p>}
            </details>
          )}
          <div className="cal-pills">
            <button type="button" className="ca-pill is-primary" disabled={busy} onClick={save}>{t.saveResults}</button>
            <button type="button" className="ca-pill" disabled={busy} onClick={reset}>{t.discardImport}</button>
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
