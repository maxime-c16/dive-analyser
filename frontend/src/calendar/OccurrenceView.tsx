import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { MapPin } from "lucide-react";
import {
  CalendarError, calendarApi, type EventDetail, type Interest, type Invitation, type LinkableDive,
  type OccurrenceDetail,
} from "./api";
import { sourceOf } from "./model";
import { searchMembers } from "../services/communityApi";
import { keepFocusOnPress, useCalendarStrings, type CalendarContext } from "./useStrings";

type State = { status: "loading" } | { status: "missing" } | { status: "failed" } |
  { status: "ready"; occ: OccurrenceDetail; event: EventDetail };

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

  if (state.status === "loading") return <p role="status">{t.loading}</p>;
  if (state.status === "missing") return <p role="alert">{t.unavailable}</p>;
  if (state.status === "failed") return <p role="alert">{t.failed} <button onClick={() => setRevision((r) => r + 1)}>{t.retry}</button></p>;
  const { occ, event } = state;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setConfirming(null);
      setRevision((r) => r + 1);
      ctx.refresh();
    } catch (e) {
      setError(e instanceof CalendarError && e.code === "stale_version" ? t.stale
        : e instanceof CalendarError && e.status === 403 ? t.forbidden : t.retrySave);
    } finally { setBusy(false); }
  };
  const cancelled = occ.status === "cancelled" || event.status === "cancelled";
  const open = !cancelled && event.status === "published";
  const viewerZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const dateText = new Intl.DateTimeFormat(lang, { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${occ.local_date}T12:00:00Z`));
  const multi = event.occurrences.length > 1;
  const search = location.search;

  return (
    <article className="calendar-detail" aria-busy={busy}>
      <span className="calendar-source">
        {t[sourceOf(occ)]}{occ.event.calendar_name ? ` · ${occ.event.calendar_name}` : ""}{occ.imported ? ` · ${t.imported}` : ""}
      </span>
      <h1>{event.title}</h1>
      <p>
        {dateText} · {occ.is_all_day ? t.allDay : `${occ.local_start}–${occ.local_end}`}
      </p>
      {event.timezone !== viewerZone && <p>{t.timezone}: {event.timezone}</p>}
      {occ.venue_name && (
        <p className="calendar-venue"><MapPin size={18} aria-hidden="true" />{occ.venue_name}
          {event.venue_address ? ` — ${event.venue_address}` : ""}</p>
      )}
      {event.map_url && <p><a href={event.map_url} target="_blank" rel="noopener noreferrer">{t.openMap}</a></p>}
      {event.organizer_name && <p>{t.organizer}: {event.organizer_name}</p>}
      {event.status === "draft" && <p role="status" className="calendar-notice">{t.draft}</p>}
      {cancelled && <p role="status" className="calendar-notice">{t.cancelledNotice}</p>}
      {!cancelled && occ.changes.some((c) => c.kind !== "cancelled") && <p role="status" className="calendar-notice">{t.changed}</p>}
      {event.description && <p className="calendar-description">{event.description}</p>}
      {error && <p role="alert" className="calendar-error">{error} {error === t.stale && <button onClick={() => setRevision((r) => r + 1)}>{t.reload}</button>}</p>}

      {event.my_invitation && event.my_invitation !== "revoked" && (
        <div className="calendar-group">
          <h2>{t.invitedYou}</h2>
          <p role="status">{t.invitation}: {t[`invitation_${event.my_invitation}` as keyof typeof t] as string}</p>
          <div className="calendar-actions">
            <button aria-pressed={event.my_invitation === "accepted"} disabled={busy || cancelled}
              onClick={() => act(() => calendarApi.respond(event.id, "accepted"))}>{t.accept}</button>
            <button aria-pressed={event.my_invitation === "declined"} disabled={busy || cancelled}
              onClick={() => act(() => calendarApi.respond(event.id, "declined"))}>{t.decline}</button>
          </div>
        </div>
      )}

      {event.status !== "draft" && (
        <div className="calendar-group" role="group" aria-labelledby="calendar-response">
          <h2 id="calendar-response">{t.yourResponse}</h2>
          <p>{t.interestNote}</p>
          <div className="calendar-actions">
            {(["interested", "maybe", "declined"] as Interest[]).map((state) => (
              <button key={state} aria-pressed={occ.my_interest === state} disabled={busy || !open}
                onClick={() => act(() => calendarApi.setInterest(occ.id, state))}>{t[state]}</button>
            ))}
            {occ.my_interest && open && (
              <button disabled={busy} onClick={() => act(() => calendarApi.setInterest(occ.id, null))}>{t.clearInterest}</button>
            )}
          </div>
        </div>
      )}

      {occ.event.calendar_kind === "group" && (
        <div className="calendar-group">
          <h2>{t.training}</h2>
          <p>{t.assignment}</p>
          {occ.can_report_absence && (
            <>
              <p role="status">{occ.my_absence_reported ? t.absence : t.noAbsence}</p>
              <button aria-pressed={occ.my_absence_reported} disabled={busy || !open}
                onClick={() => act(() => calendarApi.setAbsence(occ.id, !occ.my_absence_reported))}>
                {occ.my_absence_reported ? t.undoAbsence : t.absent}
              </button>
            </>
          )}
        </div>
      )}
      {occ.event.calendar_kind !== "group" && occ.can_report_absence && (
        <div className="calendar-group">
          <p role="status">{occ.my_absence_reported ? t.absence : t.noAbsence}</p>
          <button aria-pressed={occ.my_absence_reported} disabled={busy || !open}
            onClick={() => act(() => calendarApi.setAbsence(occ.id, !occ.my_absence_reported))}>
            {occ.my_absence_reported ? t.undoAbsence : t.absent}
          </button>
        </div>
      )}

      <div className="calendar-group">
        <button aria-pressed={event.following} disabled={busy}
          onClick={() => act(() => calendarApi.followEvent(event.id, !event.following))}>
          {event.following ? t.following : t.follow}
        </button>
        <p>{t.followNote}</p>
      </div>

      {event.resources.length > 0 && (
        <div className="calendar-group">
          <h2>{t.resources}</h2>
          <ul className="calendar-resources">
            {event.resources.map((r) => (
              <li key={r.id}>
                <span>{t[`resourceKind_${r.kind}` as keyof typeof t] as string || t.resourceKind_other}</span>{" "}
                {r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer">{r.label}</a> : r.label}
                {r.edition_label && <span className="calendar-badge"> {r.edition_label}</span>}
                {!r.source_verified_at && <span className="calendar-badge"> {t.unverified}</span>}
                {r.kind === "club_chat" && <span className="calendar-badge"> {t.restricted}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <DiveLinks occurrenceId={occ.id} />

      {event.can_edit && (
        <div className="calendar-actions calendar-group">
          {event.status === "draft" && (
            <button disabled={busy} onClick={() => act(() => calendarApi.updateEvent(event.id, { expected_version: event.version, status: "published" }))}>{t.publish}</button>
          )}
          {!cancelled && (multi
            ? <Link className="calendar-button" to={`/calendar/o/${occ.id}/edit${search}`}>{t.editSession}</Link>
            : <Link className="calendar-button" to={`/calendar/e/${event.id}/edit${search}`}>{t.editEvent}</Link>)}
          {!cancelled && confirming === null && (
            <button disabled={busy} onClick={() => setConfirming(multi ? "session" : "event")}>{multi ? t.cancelSession : t.cancelEvent}</button>
          )}
          {confirming && (
            <>
              <button disabled={busy} className="calendar-danger" onClick={() => act(() => confirming === "session"
                ? calendarApi.cancelOccurrence(occ.id, occ.version) : calendarApi.cancelEvent(event.id, event.version))}>{t.confirmCancel}</button>
              <button disabled={busy} onClick={() => setConfirming(null)}>{t.keepIt}</button>
            </>
          )}
        </div>
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
  const load = () => calendarApi.dives(occurrenceId).then((d) => setItems(d.items)).catch(() => setError(true));
  const toggle = (dive: LinkableDive) => calendarApi.linkDive(occurrenceId, dive.id, !dive.linked)
    .then((d) => setItems(d.items)).catch(() => setError(true));
  return (
    <div className="calendar-group">
      <h2>{t.dives}</h2>
      <p>{t.divesNote}</p>
      {items === null ? <button onClick={load}>{t.linkDives}</button> : items.length === 0 ? <p>{t.noDives}</p> : (
        <ul className="calendar-dive-list">
          {items.map((d) => (
            <li key={d.id}>
              <label className="calendar-check">
                <input type="checkbox" checked={d.linked} onChange={() => toggle(d)} />
                {d.dive_code} · {new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(new Date(d.dive_datetime + "Z"))}
              </label>
            </li>
          ))}
        </ul>
      )}
      {error && <p role="alert">{t.retrySave}</p>}
    </div>
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
    <div className="calendar-group">
      <h2>{t.invitations}</h2>
      <p>{t.invitationsNote}</p>
      <ul className="calendar-invitations">
        {items.map((i) => (
          <li key={i.user_id}>
            <span>{i.display_name} · {t[`invitation_${i.status}` as keyof typeof t] as string}</span>
            {i.status !== "revoked" && <button onClick={() => run(calendarApi.revoke(eventId, i.user_id))}>{t.revoke}</button>}
          </li>
        ))}
      </ul>
      <label>{t.searchPeople}<input type="search" value={term} onChange={(e) => setTerm(e.target.value)} /></label>
      {term.trim().length >= 2 && candidates.length === 0 && <p>{t.noMatches}</p>}
      <ul className="calendar-invitations">
        {candidates.filter((c) => !invited.has(c.user_id)).map((c) => (
          <li key={c.user_id}>
            <span>{c.display_name}</span>
            <button {...keepFocusOnPress} onClick={() => run(calendarApi.invite(eventId, [c.user_id]))}>{t.invite}</button>
          </li>
        ))}
      </ul>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
