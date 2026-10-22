import { useModalOverlay } from '../utils/overlays'
import { useEffect, useRef, useState } from 'react'
import { History, KeyRound, ShieldCheck } from 'lucide-react'
import PageLoading from './PageLoading'
import { listAccountHistory, listAccountSessions, resetPassword, revokeAccountSession, revokeSessions, type AccountAuditEvent, type AccountSession } from '../services/adminUsersApi'

const stamp = (value: string | null) => value ? new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'Not recorded'
const eventName = (event: AccountAuditEvent) => event.details.new_role ? `Role changed to ${event.details.new_role}` : ({ user_created: 'Account created', user_updated: 'Profile updated', user_disabled: 'Account disabled', user_enabled: 'Account enabled', password_reset: 'Password reset', password_changed: 'Password changed', session_revoked: 'Session signed out', ownership_granted: 'Diver ownership granted', ownership_revoked: 'Diver ownership removed', login_rate_limited: 'Login rate limited' }[event.event_type] ?? event.event_type.replace(/_/g, ' '))

export function AccountActionDialog({ title, children, busy, onCancel, onConfirm }: { title: string; children: React.ReactNode; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  useModalOverlay(ref, { layer: 100, isolationRef: overlayRef, initialFocus: () => ref.current?.querySelector<HTMLButtonElement>('button') ?? null, onClose: () => { if (!busy) onCancel() } })
  return <div ref={overlayRef} className="account-modal-backdrop"><div ref={ref} tabIndex={-1} className="account-modal" role="dialog" aria-modal="true" aria-label={title}><h2>{title}</h2>{children}<div><button className="account-button" disabled={busy} onClick={onCancel}>Cancel</button><button className="account-button primary" disabled={busy} onClick={onConfirm}>{busy ? 'Working…' : 'Confirm'}</button></div></div></div>
}

export default function AccountSecurity({ accountId, section, self, onRefresh }: { accountId: number; section: string; self: boolean; onRefresh: () => Promise<void> }) {
  const [sessions, setSessions] = useState<AccountSession[]>([])
  const [events, setEvents] = useState<AccountAuditEvent[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [password, setPassword] = useState('')
  const [reload, setReload] = useState(0)
  const [action, setAction] = useState<{ title: string; body: string; run: () => Promise<unknown> } | null>(null)
  useEffect(() => { setOffset(0); setFilter(''); setNotice(''); setPassword('') }, [accountId, section])
  useEffect(() => {
    let live = true
    setLoading(true); setError(''); setSessions([]); setEvents([])
    const pending = section === 'history' ? listAccountHistory(accountId, filter, offset).then(value => { if (live) { setEvents(value.events); setTotal(value.total) } }) : listAccountSessions(accountId, offset).then(value => { if (live) { setSessions(value.sessions); setTotal(value.total) } })
    pending.catch(reason => { if (live) setError(String(reason.message ?? reason)) }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [accountId, section, offset, filter, reload])
  async function runAction() {
    if (!action) return
    setBusy(true); setError(''); setNotice('')
    try {
      await action.run(); setPassword(''); setAction(null); setNotice('Action completed. Session access has been updated.'); setReload(value => value + 1)
      await onRefresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed. Please retry.') } finally { setBusy(false) }
  }
  return <>
    <article className="account-panel"><div className="account-panel-heading">{section === 'history' ? <History size={18}/> : <ShieldCheck size={18}/>}<h2>{section === 'history' ? 'Account history' : 'Security & sessions'}</h2></div><p className="account-muted">{section === 'history' ? 'Recorded account changes, newest first. Historical events may contain only changed field names, without before/after values.' : 'Live sessions show recorded timestamps. Device and browser information is not collected.'}</p>
      {notice && <p role="status" className="account-success">{notice}</p>}
      {error && <div role="alert" className="account-alert">{error}<button className="account-button" onClick={() => setReload(value => value + 1)}>Retry</button></div>}
      {section === 'history' && <label className="account-search">Filter history<select value={filter} onChange={event => { setFilter(event.target.value); setOffset(0) }}><option value="">All changes</option><option value="user_updated">Profile changes</option><option value="ownership_granted">Ownership grants & promotions</option><option value="ownership_revoked">Ownership removals & demotions</option><option value="session_revoked">Session revocations</option><option value="password_reset">Password resets</option><option value="user_disabled">Account disabled</option><option value="user_enabled">Account enabled</option></select></label>}
      {loading ? <PageLoading message={`Loading ${section === 'history' ? 'history' : 'sessions'}…`} /> : section === 'history' ? <div className="account-timeline">{events.map(event => <div key={event.event_id}><span className="account-timeline-dot"/><div><strong>{eventName(event)}</strong><small>{stamp(event.created_at)} · {event.actor.startsWith('admin:') ? `Administrator #${event.actor.slice(6)}` : event.actor}</small>{event.diver_id !== null && <small>Diver #{event.diver_id}</small>}{event.details.fields?.length ? <small>Changed: {event.details.fields.join(', ')}</small> : null}{event.details.revoked_sessions !== undefined && <small>{event.details.revoked_sessions} session(s) signed out</small>}</div></div>)}{!events.length && !error && <p className="account-muted">No recorded events match this filter.</p>}</div> : <div>{sessions.map(session => <div key={session.session_id} className="account-binding"><div className="account-binding-identity"><strong>Session #{session.session_id}</strong><small>Created {stamp(session.created_at)}</small><small>Last used {stamp(session.last_used_at)} · expires {stamp(session.expires_at)}</small></div><button className="account-button" disabled={busy || self} onClick={() => setAction({ title: `Sign out session #${session.session_id}?`, body: 'Only this session will be signed out. Other live sessions are preserved.', run: () => revokeAccountSession(accountId, session.session_id) })}>Sign out</button></div>)}{!sessions.length && !error && <p className="account-muted">No live sessions.</p>}{self && <p className="account-muted">Use your Account security page to sign yourself out.</p>}</div>}
      {!loading && total > 50 && <nav aria-label={`${section} pages`} className="account-inline-save"><button className="account-button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><span>{offset + 1}–{Math.min(offset + 50,total)} of {total}</span><button className="account-button" disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>Next</button></nav>}
      {section === 'security' && !self && <div className="account-inline-save"><button className="account-button" disabled={busy || !total || loading} onClick={() => setAction({ title: 'Sign out all sessions?', body: 'This account will be signed out everywhere and must sign in again. Its password and diver bindings are preserved.', run: () => revokeSessions(accountId) })}>Sign out everywhere</button></div>}
    </article>
    {section === 'security' && !self && <article className="account-panel"><div className="account-panel-heading"><KeyRound size={18}/><h2>Reset password</h2></div><p className="account-muted">Set a replacement password and sign this account out everywhere. Share the replacement through your established secure channel.</p><form onSubmit={event => { event.preventDefault(); setAction({ title: 'Reset this password?', body: 'The old password will stop working and all live sessions will be signed out.', run: () => resetPassword(accountId, password) }) }}><label className="account-search">Replacement password<input type="password" required minLength={10} autoComplete="new-password" value={password} disabled={busy} onChange={event => setPassword(event.target.value)} placeholder="At least 10 characters"/></label><button className="account-button" disabled={busy || password.length < 10}>Reset password</button></form></article>}
    {action && <AccountActionDialog title={action.title} busy={busy} onCancel={() => setAction(null)} onConfirm={() => void runAction()}><p>{action.body}</p>{error && <p role="alert" className="account-alert">{error}</p>}</AccountActionDialog>}
  </>
}
