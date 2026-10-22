import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarError, calendarApi, type Resource, type Roster, type RosterEntry } from "./api";
import { parisToday } from "./model";
import { keepFocusOnPress, useCalendarStrings, type CalendarContext } from "./useStrings";
import PageLoading from "../components/PageLoading";

/** Club page: app-account roster (never a complete club roster), group
 * assignment for managers/authorized coaches, coach grants for managers,
 * calendar follows and the member's own leave action. Every action is
 * re-authorized by the server; hidden buttons are convenience only. */
export default function ClubAdmin({ ctx, clubId }: { ctx: CalendarContext; clubId: number }) {
  const { t } = useCalendarStrings();
  const navigate = useNavigate();
  const [roster, setRoster] = useState<Roster | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [revision, setRevision] = useState(0);
  const mine = ctx.me.find((c) => c.club.id === clubId);

  useEffect(() => {
    Promise.all([calendarApi.roster(clubId), calendarApi.clubResources(clubId)])
      .then(([r, res]) => { setRoster(r); setResources(res); setState("ready"); })
      .catch(() => setState("missing"));
  }, [clubId, revision]);

  if (state === "loading") return <PageLoading message={t.loading} />;
  if (state === "missing" || !roster) return <p role="alert">{t.unavailable}</p>;
  const run = async (fn: () => Promise<unknown>, after?: () => void) => {
    setMessage(null);
    try {
      await fn();
      setMessage(t.saved);
      setRevision((r) => r + 1);
      ctx.refresh();
      after?.();
    } catch (e) {
      setMessage(e instanceof CalendarError && e.code === "last_manager" ? t.lastManager
        : e instanceof CalendarError && e.status === 403 ? t.forbidden : t.retrySave);
    }
  };
  const groupName = (id: number | null) => roster.groups.find((g) => g.id === id)?.name ?? t.unassigned;
  const calendars = ctx.calendars.filter((c) => c.club_id === clubId || c.kind === "federal");

  return (
    <article className="calendar-club">
      <h1>{mine?.club.name ?? t.clubPage}</h1>
      {mine && (
        <p>
          {t[`role_${mine.membership.role}` as keyof typeof t] as string}
          {mine.group ? ` · ${t.group}: ${mine.group.name}` : mine.membership.role === "member" ? ` · ${t.group}: ${t.unassigned}` : ""}
        </p>
      )}
      {mine?.self_declared && <p>{t.selfDeclared}</p>}
      {message && <p role="status" className="calendar-notice">{message}</p>}

      <section className="calendar-group">
        <h2>{t.members}</h2>
        <p>{t.rosterNote}</p>
        <ul className="calendar-roster">
          {roster.items.map((m) => (
            <MemberRow key={m.user_id} member={m} roster={roster} groupName={groupName}
              onAssign={(group, from) => run(() => calendarApi.assignGroup(clubId, m.user_id, group, from))}
              onRole={(body) => run(() => calendarApi.updateMembership(clubId, m.membership_id!, body))}
              onRemove={() => run(() => calendarApi.endMembership(clubId, m.membership_id!))} />
          ))}
        </ul>
      </section>

      <section className="calendar-group">
        <h2>{t.calendars}</h2>
        <p>{t.followNote}</p>
        <ul className="calendar-roster">
          {calendars.map((c) => (
            <li key={c.id}>
              <span>{c.name}</span>
              <button aria-pressed={c.following} onClick={() => run(() => calendarApi.followCalendar(c.id, !c.following))}>
                {c.following ? t.unfollowCalendar : t.followCalendar}
              </button>
            </li>
          ))}
        </ul>
      </section>

      {resources.length > 0 && (
        <section className="calendar-group">
          <h2>{t.resources}</h2>
          <ul className="calendar-resources">
            {resources.map((r) => (
              <li key={r.id}>
                <span>{t[`resourceKind_${r.kind}` as keyof typeof t] as string || t.resourceKind_other}</span>{" "}
                {r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer">{r.label}</a> : r.label}
                {r.edition_label && <span className="calendar-badge"> {r.edition_label}</span>}
                {!r.source_verified_at && <span className="calendar-badge"> {t.unverified}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {mine && (
        <section className="calendar-group">
          {!confirmLeave ? <button onClick={() => setConfirmLeave(true)}>{t.leave}</button> : (
            <div className="calendar-actions">
              <button className="calendar-danger" onClick={() => run(() => calendarApi.leaveClub(clubId), () => navigate("/calendar"))}>{t.confirmLeave}</button>
              <button onClick={() => setConfirmLeave(false)}>{t.keepIt}</button>
            </div>
          )}
        </section>
      )}
    </article>
  );
}

function MemberRow({ member, roster, groupName, onAssign, onRole, onRemove }: {
  member: RosterEntry; roster: Roster; groupName: (id: number | null) => string
  onAssign: (group: number | null, from: string) => void
  onRole: (body: { role?: "member" | "coach"; can_publish?: boolean; can_assign_groups?: boolean }) => void
  onRemove: () => void
}) {
  const { t } = useCalendarStrings();
  const [group, setGroup] = useState(member.group_id === null ? "" : String(member.group_id));
  const [from, setFrom] = useState(parisToday());
  const staffView = member.membership_id !== null;
  const manageable = roster.can_manage_members && member.role !== "manager";
  return (
    <li className="calendar-member">
      <div>
        <strong>{member.display_name}</strong>{" "}
        <span>{t[`role_${member.role}` as keyof typeof t] as string}</span>
        {member.self_declared && <span className="calendar-badge"> {t.selfDeclaredBadge}</span>}
        {staffView && <p>{t.group}: {groupName(member.group_id)}{member.group_since ? ` (${t.since} ${member.group_since})` : ""}</p>}
      </div>
      {roster.can_assign_groups && staffView && (
        <form className="calendar-inline-form" onSubmit={(e) => { e.preventDefault(); onAssign(group ? Number(group) : null, from); }}>
          <label>{t.group}
            <select value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">{t.unassigned}</option>
              {roster.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </label>
          <label>{t.effectiveFrom}<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <button type="submit" {...keepFocusOnPress}>{t.assign}</button>
        </form>
      )}
      {manageable && (
        <div className="calendar-inline-form">
          <label>{t.roleField}
            <select value={member.role} onChange={(e) => onRole({ role: e.target.value as "member" | "coach" })}>
              <option value="member">{t.role_member}</option>
              <option value="coach">{t.role_coach}</option>
            </select>
          </label>
          {member.role === "coach" && (
            <>
              <label className="calendar-check"><input type="checkbox" checked={!!member.can_publish} onChange={(e) => onRole({ can_publish: e.target.checked })} />{t.canPublish}</label>
              <label className="calendar-check"><input type="checkbox" checked={!!member.can_assign_groups} onChange={(e) => onRole({ can_assign_groups: e.target.checked })} />{t.canAssign}</label>
            </>
          )}
          <button className="calendar-danger" onClick={() => { if (window.confirm(`${t.remove}: ${member.display_name}?`)) onRemove(); }}>{t.remove}</button>
        </div>
      )}
    </li>
  );
}
