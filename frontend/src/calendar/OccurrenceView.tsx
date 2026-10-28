import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  CalendarClock, CalendarPlus, Check, ChevronRight, Clock, ExternalLink, Globe, MapPin, Pencil, Plus, Repeat, Send,
  Star, Trophy, UserRound, Users, XCircle,
} from "lucide-react";
import {
  CalendarError, calendarApi, type EventDetail, type Invitation, type LinkableDive,
  type OccurrenceDetail,
} from "./api";
import { lastDay, parisToday, sourceOf, spanDays } from "./model";
import { searchMembers } from "../services/communityApi";
import { keepFocusOnPress, useCalendarStrings, type CalendarContext } from "./useStrings";
import PageLoading from "../components/PageLoading";
import MemberAvatar from "../components/MemberAvatar";
import { attemptScore, type Attempt } from "../utils/attemptPresentation";
import { fmtScore, scoreBand } from "../utils/codeStats";

type State = { status: "loading" } | { status: "missing" } | { status: "failed" } |
  { status: "ready"; occ: OccurrenceDetail; event: EventDetail };

const utc = (d: string) => new Date(`${d}T12:00:00Z`);

export default function OccurrenceView({ ctx, occurrenceId }: { ctx: CalendarContext; occurrenceId: number }) {
  const { t, lang } = useCalendarStrings();
  const location = useLocation();
  const [state, setState] = useState<State>({ status: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<"event" | "session" | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let live = true;
    setState((s) => (s.status === "ready" && s.occ.id === occurrenceId ? s : { status: "loading" }));
    calendarApi.occurrence(occurrenceId)
      .then(async (occ) => {
        const event = await calendarApi.event(occ.event.id);
        if (live) setState({ status: "ready", occ, event });
      })
      .catch((e) => { if (live) setState({ status: e instanceof CalendarError && e.status === 404 ? "missing" : "failed" }); });
    return () => { live = false; };
  }, [occurrenceId, revision]);

  if (state.status === "loading") return <PageLoading message={t.loading} />;
  if (state.status === "missing") return <p role="alert" className="cal-notice">{t.unavailable}</p>;
  if (state.status === "failed") return <p role="alert" className="cal-notice is-bad">{t.failed} <button className="ca-pill" onClick={() => setRevision((r) => r + 1)}>{t.retry}</button></p>;
  const { occ, event } = state;

  const act = async (fn: () => Promise<unknown>, optimistic?: Partial<OccurrenceDetail>, eventPatch?: Partial<EventDetail>) => {
    setBusy(true);
    setError(null);
    if (optimistic || eventPatch) setState({ status: "ready", occ: { ...occ, ...optimistic }, event: { ...event, ...eventPatch } });
    try {
      await fn();
      setConfirming(null);
      setRevision((r) => r + 1);
      ctx.refresh();
    } catch (e) {
      if (optimistic || eventPatch) setState({ status: "ready", occ, event });
      setError(e instanceof CalendarError && e.code === "stale_version" ? t.stale
        : e instanceof CalendarError && e.status === 403 ? t.forbidden : t.retrySave);
    } finally { setBusy(false); }
  };
  const cancelled = occ.status === "cancelled" || event.status === "cancelled";
  const open = !cancelled && event.status === "published";
  const today = parisToday();
  const viewerZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const fmt = (d: string, o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(lang, { ...o, timeZone: "UTC" }).format(utc(d));
  const multiDay = spanDays(occ) > 1;
  const away = Math.round((utc(occ.local_date).getTime() - utc(today).getTime()) / 86_400_000);
  const rec = event.recurrence;
  const series = !!rec || event.imported;
  const multi = event.occurrences.length > 1;
  const search = location.search;
  const src = sourceOf(occ);
  const group = occ.event.calendar_kind === "group" ? occ.event.calendar_name : null;
  const going = occ.going;
  const mapHref = event.map_url || (occ.venue_name
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([occ.venue_name, event.venue_address].filter(Boolean).join(", "))}` : null);


  return (
    <article className={`cal-detail cal-src-${src}`} aria-busy={busy}>
      <header className="cal-hero ca-arrive">
        <div className="cal-date-tile" aria-hidden="true">
          <span>{fmt(occ.local_date, { month: "short" }).replace(".", "")}</span>
          <b className={multiDay ? "is-range" : undefined}>{multiDay ? `${Number(occ.local_date.slice(8))}–${Number(lastDay(occ).slice(8))}` : Number(occ.local_date.slice(8))}</b>
          <small>{fmt(occ.local_date, { weekday: "short" }).replace(".", "")}{multiDay ? `–${fmt(lastDay(occ), { weekday: "short" }).replace(".", "")}` : ""}</small>
        </div>
        <div className="cal-hero-text">
          <span className="cal-tag"><i className="cal-dot" />{group ? `${t.group} ${group}` : t[src]}</span>
          <h1>{event.title}</h1>
          <p>
            <span className="sr-only">{fmt(occ.local_date, { weekday: "long", day: "numeric", month: "long", year: "numeric" })} · </span>
            {multiDay ? t.days(spanDays(occ)) : occ.is_all_day ? t.allDay : `${occ.local_start}–${occ.local_end}`}
            {!cancelled && away >= 0 && ` · ${t.inDays(away)}`}
          </p>
        </div>
      </header>

      {event.status === "draft" && <p role="status" className="cal-notice">{t.draft}</p>}
      {cancelled && <p role="status" className="cal-notice is-bad">{t.cancelled}</p>}
      {!cancelled && occ.changes.some((c) => c.kind !== "cancelled") && <p role="status" className="cal-notice">{t.changedShort}</p>}
      {error && <p role="alert" className="cal-notice is-bad">{error} {error === t.stale && <button className="ca-pill" onClick={() => setRevision((r) => r + 1)}>{t.reload}</button>}</p>}

      {event.my_invitation && event.my_invitation !== "revoked" && (
        <section className="ca-panel cal-invite">
          <h2>{t.invitedShort}</h2>
          <div className="cal-pills">
            <button className="ca-pill" aria-pressed={event.my_invitation === "accepted"} disabled={busy || cancelled}
              onClick={() => act(() => calendarApi.respond(event.id, "accepted"))}>{t.accept}</button>
            <button className="ca-pill" aria-pressed={event.my_invitation === "declined"} disabled={busy || cancelled}
              onClick={() => act(() => calendarApi.respond(event.id, "declined"))}>{t.decline}</button>
          </div>
        </section>
      )}

      {occ.can_report_absence && event.status !== "draft" && (
        <div className="cal-rsvp is-big">
          <button type="button" className="is-declined" aria-pressed={occ.my_absence_reported} disabled={busy || !open}
            onClick={() => act(() => calendarApi.setAbsence(occ.id, !occ.my_absence_reported), { my_absence_reported: !occ.my_absence_reported })}>
            {occ.my_absence_reported ? t.cancelAbsence : t.reportAbsence}
          </button>
        </div>
      )}

      {occ.shared_session_id && <Link className="cal-series" to={`/sessions/shared/${occ.shared_session_id}`}>
        {t.openSharedSession}<ChevronRight size={18} aria-hidden="true" />
      </Link>}

      {event.event_type === "competition" && (
        <Link className="cal-series" to={`/series?event=${event.id}`}>
          <Trophy size={20} aria-hidden="true" /><span>{t.seriesShort}</span><ChevronRight size={18} aria-hidden="true" />
        </Link>
      )}

      <section className="ca-panel cal-facts">
        {occ.venue_name && (
          <div className="cal-fact">
            <MapPin size={18} aria-hidden="true" />
            <div><b>{occ.venue_name}</b>{event.venue_address && <small>{event.venue_address}</small>}</div>
            {mapHref && <a className="cal-go" href={mapHref} target="_blank" rel="noopener noreferrer">{t.directions}<ExternalLink size={14} aria-hidden="true" /></a>}
          </div>
        )}
        {multiDay && (
          <div className="cal-fact">
            <Clock size={18} aria-hidden="true" />
            <div><b>{t.dateRange(fmt(occ.local_date, { weekday: "short", day: "numeric", month: "short" }), fmt(lastDay(occ), { weekday: "short", day: "numeric", month: "short" }))}</b>
              {!occ.is_all_day && <small>{occ.local_start}–{occ.local_end}</small>}</div>
          </div>
        )}
        {rec && (
          <div className="cal-fact">
            <Repeat size={18} aria-hidden="true" />
            <div><b>{t.repeatsSummary(rec.weekdays.map((d) => t.weekdayShort[d - 1]).join(", "), rec.start_time, rec.end_time, fmt(rec.until_date, { day: "numeric", month: "long", year: "numeric" }))}</b>
              {occ.detached && <small>{t.individuallyEdited}</small>}</div>
          </div>
        )}
        {event.timezone !== viewerZone && (
          <div className="cal-fact"><Globe size={18} aria-hidden="true" /><div><b>{event.timezone}</b><small>{t.timezone}</small></div></div>
        )}
        {event.organizer_name && (
          <div className="cal-fact"><UserRound size={18} aria-hidden="true" /><div><b>{event.organizer_name}</b><small>{t.organizer}</small></div></div>
        )}
        {event.status !== "draft" && going && (
          <div className="cal-fact">
            <Users size={18} aria-hidden="true" />
            <div>
              <b>{going.interested || going.maybe ? t.goingCount(going.interested) : t.nobodyYet}</b>

            </div>
            {going.people.length > 0 && (
              <span className="cal-faces" aria-label={going.people.map((p) => p.display_name).join(", ")}>
                {going.people.slice(0, 4).map((p) => <MemberAvatar key={p.user_id} member={p} size={30} />)}
                {going.interested + going.maybe > 4 && <span className="cal-faces-more">+{going.interested + going.maybe - 4}</span>}
              </span>
            )}
          </div>
        )}

      </section>

      {event.description && <section className="ca-panel"><p className="cal-description">{event.description}</p></section>}

      {(event.itinerary ?? []).length > 0 && (
        <section className="ca-panel">
          <div className="ca-panel-h"><h2>{t.itinerary}</h2></div>
          <ol className="cal-itinerary">
            {event.itinerary.map((b, i) => (
              <li key={i}>
                <b>{fmt(b.local_date, { weekday: "short", day: "numeric", month: "short" })}{b.start_time ? ` · ${b.start_time}${b.end_time ? `–${b.end_time}` : ""}` : ""}</b>
                <span>{[b.venue_name, b.label].filter(Boolean).join(" · ")}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {occ.local_date <= today && <DiveLinks occurrenceId={occ.id} />}

      {event.resources.length > 0 && (
        <section className="ca-panel cal-list">
          <div className="ca-panel-h"><h2>{t.resources}</h2></div>
          {event.resources.map((r) => {
            const label = t[`resourceKind_${r.kind}` as keyof typeof t] as string || t.resourceKind_other;
            const inner = <>
              <span className="cal-list-main"><b>{label}</b>{(r.label !== label || r.edition_label) && <small>{[r.label !== label ? r.label : null, r.edition_label].filter(Boolean).join(" · ")}</small>}</span>
              {!r.source_verified_at && <span className="cal-chip is-warn">{t.unverified.split(" · ")[0]}</span>}
              {r.kind === "club_chat" && <span className="cal-chip">{t.restricted}</span>}
              {r.url && <ExternalLink size={16} aria-hidden="true" />}
            </>;
            return r.url
              ? <a key={r.id} className="cal-list-row" href={r.url} target="_blank" rel="noopener noreferrer">{inner}</a>
              : <div key={r.id} className="cal-list-row">{inner}</div>;
          })}
        </section>
      )}

      <section className="ca-panel cal-list">
        <div className="cal-list-row">
          <Star size={18} aria-hidden="true" /><span className="cal-list-main"><b>{t.followChanges}</b></span>
          <button type="button" role="switch" className="cal-switch" aria-checked={event.following} aria-label={t.followChanges} disabled={busy}
            onClick={() => act(() => calendarApi.followEvent(event.id, !event.following), undefined, { following: !event.following })} />
        </div>
        <a className="cal-list-row" href={`/api/v1/calendar/occurrences/${occ.id}/export.ics`} download>
          <CalendarPlus size={18} aria-hidden="true" /><span className="cal-list-main"><b>{t.addToCalendar}</b></span><ChevronRight size={16} aria-hidden="true" />
        </a>
      </section>

      {event.can_edit && (
        <section className="ca-panel cal-list">
          <div className="ca-panel-h"><h2>{t.organize}</h2></div>
          {event.status === "draft" && (
            <button type="button" className="cal-list-row" disabled={busy} onClick={() => act(() => calendarApi.updateEvent(event.id, { expected_version: event.version, status: "published" }))}>
              <Send size={18} aria-hidden="true" /><span className="cal-list-main"><b>{t.publish}</b></span>
            </button>
          )}
          {!cancelled && series && <Link className="cal-list-row" to={`/calendar/o/${occ.id}/schedule${search}`}><CalendarClock size={18} aria-hidden="true" /><span className="cal-list-main"><b>{t.editSchedule}</b></span><ChevronRight size={16} aria-hidden="true" /></Link>}
          {!cancelled && multi && !series && <Link className="cal-list-row" to={`/calendar/o/${occ.id}/edit${search}`}><Pencil size={18} aria-hidden="true" /><span className="cal-list-main"><b>{t.editSession}</b></span><ChevronRight size={16} aria-hidden="true" /></Link>}
          {!cancelled && (!multi || rec) && <Link className="cal-list-row" to={`/calendar/e/${event.id}/edit${search}`}><Pencil size={18} aria-hidden="true" /><span className="cal-list-main"><b>{t.editEvent}</b></span><ChevronRight size={16} aria-hidden="true" /></Link>}
          {!cancelled && confirming === null && (
            <button type="button" className="cal-list-row is-danger" disabled={busy} onClick={() => setConfirming(multi ? "session" : "event")}>
              <XCircle size={18} aria-hidden="true" /><span className="cal-list-main"><b>{multi ? t.cancelSession : t.cancelEvent}</b></span>
            </button>
          )}
          {confirming && (
            <div className="cal-list-row cal-confirm">
              <button type="button" className="ca-pill is-danger" disabled={busy} onClick={() => act(() => confirming === "session"
                ? calendarApi.cancelOccurrence(occ.id, occ.version) : calendarApi.cancelEvent(event.id, event.version))}>{t.confirmCancel}</button>
              <button type="button" className="ca-pill" disabled={busy} onClick={() => setConfirming(null)}>{t.keepIt}</button>
            </div>
          )}
        </section>
      )}
      {event.can_edit && event.audience === "invited" && !cancelled && (
        <Invitations eventId={event.id} clubId={event.club_id} />
      )}
    </article>
  );
}

function DiveLinks({ occurrenceId }: { occurrenceId: number }) {
  const { t, lang } = useCalendarStrings();
  const [items, setItems] = useState<LinkableDive[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    calendarApi.dives(occurrenceId).then((d) => { if (live) setItems(d.items); }).catch(() => { if (live) setError(true); });
    return () => { live = false; };
  }, [occurrenceId]);
  const toggle = (dive: LinkableDive) => {
    setItems((list) => list && list.map((d) => (d.id === dive.id ? { ...d, linked: !d.linked } : d)));
    calendarApi.linkDive(occurrenceId, dive.id, !dive.linked).then((d) => setItems(d.items)).catch(() => {
      setItems((list) => list && list.map((d) => (d.id === dive.id ? { ...d, linked: dive.linked } : d)));
      setError(true);
    });
  };
  if (!items?.length && !error) return null;
  const time = (d: LinkableDive) => new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(new Date(d.dive_datetime + "Z"));
  return (
    <section className="ca-panel">
      <div className="ca-panel-h"><h2>{t.myDives}</h2>{items && <span>{t.linkedCount(items.filter((d) => d.linked).length, items.length)}</span>}</div>
      {items && (
        <div className="cal-dives">
          {items.map((d) => {
            const score = d.performance ? attemptScore(d as unknown as Attempt) : null;
            return (
              <button key={d.id} type="button" className="cal-dive" aria-pressed={d.linked} onClick={() => toggle(d)}
                aria-label={`${d.dive_code} · ${time(d)}`}>
                {d.poster_url && <img src={d.poster_url} alt="" loading="lazy" decoding="async" />}
                {score != null && <span className={`cal-dive-score ca-r-${scoreBand(score)}`}>{fmtScore(score)}</span>}
                <span className="cal-dive-mark" aria-hidden="true">{d.linked ? <Check size={14} strokeWidth={3} /> : <Plus size={14} />}</span>
                <span className="cal-dive-cap"><b>{d.dive_code}</b><small>{time(d)}{d.height ? ` · ${d.height}` : ""}</small></span>
              </button>
            );
          })}
        </div>
      )}
      {error && <p role="alert" className="cal-notice is-bad">{t.retrySave}</p>}
    </section>
  );
}

function Invitations({ eventId, clubId }: { eventId: number; clubId: number | null }) {
  const { t } = useCalendarStrings();
  const [items, setItems] = useState<Invitation[]>([]);
  const [term, setTerm] = useState("");
  const [candidates, setCandidates] = useState<{ user_id: number; display_name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { calendarApi.invitations(eventId).then((d) => setItems(d.items)).catch(() => setError(t.failed)); }, [eventId]);
  useEffect(() => {
    const needle = term.trim().toLowerCase();
    if (needle.length < 2) { setCandidates([]); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      // Club events invite active club members; personal outings any account.
      const lookup = clubId !== null
        ? calendarApi.roster(clubId).then((r) => r.items.filter((m) => m.display_name.toLowerCase().includes(needle)))
        : searchMembers(term.trim(), undefined, controller.signal).then((r) => r.items);
      lookup.then((rows) => setCandidates(rows.slice(0, 8).map((r) => ({ user_id: r.user_id, display_name: r.display_name }))))
        .catch(() => undefined);
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [term, clubId]);
  const run = (p: Promise<{ items: Invitation[] }>) => p.then((d) => { setItems(d.items); setError(null); })
    .catch((e) => setError(e instanceof CalendarError && e.code === "not_member" ? t.forbidden : t.retrySave));
  const invited = new Set(items.filter((i) => i.status !== "revoked").map((i) => i.user_id));
  return (
    <section className="ca-panel cal-list">
      <div className="ca-panel-h"><h2>{t.invitations.split(" (")[0]}</h2><span>{invited.size}</span></div>
      {items.map((i) => (
        <div key={i.user_id} className="cal-list-row">
          <MemberAvatar member={{ display_name: i.display_name }} size={30} />
          <span className="cal-list-main"><b>{i.display_name}</b><small>{t[`invitation_${i.status}` as keyof typeof t] as string}</small></span>
          {i.status !== "revoked" && <button className="ca-pill" onClick={() => run(calendarApi.revoke(eventId, i.user_id))}>{t.revoke}</button>}
        </div>
      ))}
      <label className="cal-search is-inline">
        <span className="sr-only">{t.searchPeople}</span>
        <input type="search" placeholder={t.searchPeople} value={term} onChange={(e) => setTerm(e.target.value)} />
      </label>
      {term.trim().length >= 2 && candidates.length === 0 && <p className="cal-none">{t.noMatches}</p>}
      {candidates.filter((c) => !invited.has(c.user_id)).map((c) => (
        <div key={c.user_id} className="cal-list-row">
          <MemberAvatar member={{ display_name: c.display_name }} size={30} />
          <span className="cal-list-main"><b>{c.display_name}</b></span>
          <button className="ca-pill" {...keepFocusOnPress} onClick={() => run(calendarApi.invite(eventId, [c.user_id]))}>{t.invite}</button>
        </div>
      ))}
      {error && <p role="alert" className="cal-notice is-bad">{error}</p>}
    </section>
  );
}
