import { useContext, useEffect, useState, type ReactNode } from 'react'
import { UNSAFE_DataRouterContext, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Check, Copy, Link2, ShieldCheck, UserRound, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { bindDiver, getUser, listAllDivers, roleTitle, unbindDiver, updateUser, type AdminUser, type AdminDiver, type PublicRole } from '../services/adminUsersApi'
import AccountNavigationGuard from '../components/AccountNavigationGuard'
import './AdminAccount.css'

export type AccountLayout = 'tabs' | 'sidebar' | 'cards'
export type AccountSection = 'overview' | 'profile' | 'access'
const sections: { id: AccountSection; label: string }[] = [{ id: 'overview', label: 'Overview' }, { id: 'profile', label: 'Profile' }, { id: 'access', label: 'Access & bindings' }]
const date = (value: string | null) => value ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleDateString(undefined, { dateStyle: 'medium' }) : 'Not recorded'

export function AccountWorkspace({ accountId, currentUserId, layout = 'tabs', onBack, section, onSection, extraSections = [], renderExtra }: {
  accountId: number; currentUserId?: number; layout?: AccountLayout; onBack: () => void;
  section: string; onSection: (section: string) => void; extraSections?: { id: string; label: string }[]; renderExtra?: (section: string, user: AdminUser, refresh: () => Promise<void>) => ReactNode;
}) {
  const [user, setUser] = useState<AdminUser | null>(null)
  const [divers, setDivers] = useState<AdminDiver[]>([])
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<PublicRole>('diver')
  const [active, setActive] = useState(true)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [diverError, setDiverError] = useState('')
  const [notice, setNotice] = useState('')
  const [confirm, setConfirm] = useState<{ title: string; body: string; action: () => Promise<void> } | null>(null)
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const self = accountId === currentUserId
  const dirty = !!user && (name !== user.display_name || email !== user.email || role !== (user.is_admin ? 'administrator' : 'diver') || active !== user.is_active)
  const allSections = [...sections, ...extraSections]
  function setForm(value: AdminUser) { setName(value.display_name); setEmail(value.email); setRole(value.is_admin ? 'administrator' : 'diver'); setActive(value.is_active) }
  async function refresh() { const value = await getUser(accountId); setUser(value) }
  useEffect(() => {
    let live = true
    setUser(null); setError(''); setNotice('')
    getUser(accountId).then(value => { if (live) { setUser(value); setForm(value) } }).catch(reason => { if (live) setError(String(reason.message ?? reason)) })
    listAllDivers().then(value => { if (live) { setDivers(value); setDiverError('') } }).catch(reason => { if (live) setDiverError(String(reason.message ?? reason)) })
    return () => { live = false }
  }, [accountId])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    return () => { window.removeEventListener('beforeunload', warn) }
  }, [dirty])
  async function mutate(action: () => Promise<void>, success: string) {
    setBusy(true); setError(''); setNotice('')
    try { await action(); setNotice(success); setConfirm(null) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed. Please retry.') } finally { setBusy(false) }
  }
  async function save() {
    await mutate(async () => {
      const value = await updateUser(accountId, { display_name: name.trim(), email: email.trim(), role, is_active: active })
      setUser(value); setForm(value)
    }, 'Account changes saved.')
  }
  async function copy(value: string) { try { await navigator.clipboard.writeText(value); setNotice('Copied to clipboard.') } catch { setNotice(`Copy: ${value}`) } }
  if (!user) return <main className="account-workspace"><button className="account-button" onClick={onBack}><ArrowLeft size={16} /> Back to accounts</button>{error ? <div role="alert" className="account-alert">{error}<button onClick={() => { setError(''); void getUser(accountId).then(value => { setUser(value); setForm(value) }).catch(reason => setError(String(reason))) }}>Retry</button></div> : <p role="status">Loading account…</p>}</main>
  const bindings = user.diver_ids ?? []
  const filtered = [...divers].sort((a,b) => Number(bindings.includes(b.diver_id)) - Number(bindings.includes(a.diver_id))).filter(diver => `${diver.display_name} ${diver.canonical_name} ${diver.diver_id}`.toLowerCase().includes(query.toLowerCase()))
  const content = section === 'overview' ? <>
    <div className="account-metrics">
      <div><span>Account status</span><strong>{user.is_active ? 'Active' : 'Disabled'}</strong><small>{user.is_active ? 'Can sign in to the workspace' : 'Sign-in is blocked'}</small></div>
      <div><span>Linked divers</span><strong>{user.diver_binding_total ?? bindings.length}</strong><small>Explicit ownership bindings</small></div>
      <div><span>Live sessions</span><strong>{user.live_sessions}</strong><small>Unrevoked and unexpired</small></div>
      <div><span>Created</span><strong className="account-date">{date(user.created_at)}</strong><small>Account registration date</small></div>
    </div>
    <div className="account-grid">
      <article className="account-panel"><div className="account-panel-heading"><UserRound size={18} /><h2>Account at a glance</h2></div><dl className="account-facts"><div><dt>Email</dt><dd>{user.email}</dd></div><div><dt>Workspace role</dt><dd>{roleTitle(user)}</dd></div><div><dt>Account ID</dt><dd>#{user.user_id}</dd></div></dl><button className="account-button" onClick={() => onSection('profile')}>Edit profile →</button></article>
      <article className="account-panel"><div className="account-panel-heading"><Link2 size={18} /><h2>Dive ownership</h2></div><p className="account-muted">Diver bindings determine which dives this account owns. Administrator privileges control workspace operations separately.</p>{bindings.length === 0 && <p className="account-warning">No diver is linked. This account has no diver ownership access.</p>}<div className="account-tags">{divers.filter(d => bindings.includes(d.diver_id)).map(d => <span key={d.diver_id}>{d.display_name}</span>)}</div><button className="account-button" onClick={() => onSection('access')}>Manage bindings →</button></article>
    </div>
    {layout === 'cards' && <div className="account-shortcuts">{allSections.filter(item => item.id !== 'overview').map(item => <button key={item.id} onClick={() => onSection(item.id)}><span>{item.label}</span><small>Open account tools →</small></button>)}</div>}
  </> : section === 'profile' ? <article className="account-panel"><div className="account-panel-heading"><UserRound size={18} /><h2>Profile & account status</h2></div><p className="account-muted">Review identity and access level. Changes are saved together.</p><form id="account-profile" onSubmit={event => { event.preventDefault(); if (role !== (user.is_admin ? 'administrator' : 'diver') || active !== user.is_active) setConfirm({ title: 'Change account access?', body: 'Changing the role or disabling this account signs out its sessions. Diver bindings are preserved.', action: save }); else void save() }}><fieldset disabled={busy} className="account-form-grid"><label>Display name<input required maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label><label>Email address<input type="email" required maxLength={255} value={email} onChange={event => setEmail(event.target.value)} /></label><label>Workspace role<select value={role} disabled={self} onChange={event => setRole(event.target.value as PublicRole)}><option value="diver">Diver</option><option value="administrator">Administrator</option></select></label><label>Account status<select value={active ? 'active' : 'disabled'} disabled={self} onChange={event => setActive(event.target.value === 'active')}><option value="active">Active</option><option value="disabled">Disabled</option></select></label></fieldset>{self && <p className="account-muted">You cannot disable yourself or remove your own administrator access.</p>}<div className="account-inline-save"><button type="submit" className="account-button primary" disabled={busy || !dirty}>Save changes</button><button type="button" className="account-button" disabled={busy || !dirty} onClick={() => setForm(user)}>Discard</button></div></form></article> : section === 'access' ? <article className="account-panel"><div className="account-panel-heading"><Link2 size={18} /><h2>Access & diver bindings</h2></div><p className="account-muted">Link an account to a diver to grant ownership access to that diver’s dives. A diver can be linked to more than one account.</p><label className="account-search">Find a diver<input type="search" placeholder="Search name, canonical name or ID…" value={query} onChange={event => setQuery(event.target.value)} /></label>{diverError && <div role="alert" className="account-alert">{diverError}<button onClick={() => void listAllDivers().then(value => { setDivers(value); setDiverError('') }).catch(reason => setDiverError(String(reason)))}>Retry diver directory</button></div>}{(user.diver_binding_total ?? bindings.length) > bindings.length && <p className="account-warning">Only the first {bindings.length} bindings are returned by the current API. Additional bindings are not shown.</p>}<div className="account-binding-list">{filtered.map(diver => { const bound = bindings.includes(diver.diver_id); return <div key={diver.diver_id} className="account-binding"><div className={`account-avatar small ${bound ? '' : 'muted'}`}>{diver.display_name.slice(0,2).toUpperCase()}</div><div className="account-binding-identity"><strong>{diver.display_name}</strong><small>{diver.canonical_name} · #{diver.diver_id}{!diver.active ? ' · Inactive diver' : ''}</small>{!bound && diver.bound_to_user && <small>Already linked to another account</small>}</div><span className="account-binding-status">{bound ? 'Linked · Owner' : 'Available'}</span><button className={`account-button ${bound ? '' : 'primary'}`} disabled={busy} onClick={() => setConfirm({ title: bound ? `Remove ${diver.display_name}?` : `Link ${diver.display_name}?`, body: bound ? 'This removes ownership access to this diver’s dives. Public visibility may still permit viewing. Dive records and videos remain stored.' : 'This grants ownership access to this diver’s dives, including management actions. Existing account links are preserved.', action: async () => { await mutate(async () => { if (bound) await unbindDiver(accountId, diver.diver_id); else await bindDiver(accountId, diver.diver_id); await refresh() }, bound ? 'Diver binding removed.' : 'Diver linked.') } })}>{bound ? 'Remove' : 'Link diver'}</button></div> })}{!filtered.length && !diverError && <p className="account-muted">No divers match your search.</p>}</div></article> : renderExtra?.(section, user, refresh)
  return <main className={`account-workspace layout-${layout}`}>
    {dataRouter && <AccountNavigationGuard dirty={dirty}/>}
    <button className="account-back" onClick={() => { if (dataRouter || !dirty || window.confirm('Leave this account with unsaved changes?')) onBack() }}><ArrowLeft size={15} /> Accounts / Manage account</button>
    <header className="account-header"><div className="account-avatar">{user.display_name.slice(0,2).toUpperCase()}</div><div className="account-header-identity"><div className="account-eyebrow">ACCOUNT WORKSPACE · #{user.user_id}</div><h1>{user.display_name}</h1><div className="account-email">{user.email}<button aria-label="Copy email" onClick={() => void copy(user.email)}><Copy size={14}/></button></div></div><div className="account-header-badges"><span className={`account-badge ${user.is_active ? 'positive' : 'negative'}`}><span/> {user.is_active ? 'Active' : 'Disabled'}</span><span className="account-badge"><ShieldCheck size={13}/>{roleTitle(user)}</span>{self && <span className="account-badge">Your account</span>}</div></header>
    {notice && <div role="status" className="account-success"><Check size={16}/>{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={14}/></button></div>}
    {error && <div role="alert" className="account-alert">{error}</div>}
    <div className="account-body"><nav aria-label="Account sections" className="account-section-nav">{allSections.map(item => <button key={item.id} aria-current={section === item.id ? 'page' : undefined} onClick={() => onSection(item.id)}>{item.label}</button>)}</nav><div className="account-content">{content}</div></div>
    {dirty && <div className="account-savebar"><div><strong>Unsaved changes</strong><small>Your edits are kept while switching sections.</small></div><button className="account-button" disabled={busy} onClick={() => setForm(user)}>Discard</button><button className="account-button primary" disabled={busy} onClick={() => { onSection('profile') }}>Review & save</button></div>}
    {confirm && <div className="account-modal-backdrop"><div className="account-modal" role="dialog" aria-modal="true" aria-labelledby="account-confirm-title" onKeyDown={event => { if (event.key === 'Escape' && !busy) setConfirm(null); if (event.key === 'Tab') { const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')); const next = event.shiftKey ? buttons[0] : buttons[buttons.length - 1]; if (document.activeElement === next) { event.preventDefault(); (event.shiftKey ? buttons[buttons.length - 1] : buttons[0])?.focus() } } }}><h2 id="account-confirm-title">{confirm.title}</h2><p>{confirm.body}</p>{error && <p role="alert" className="account-alert">{error}</p>}<div><button autoFocus className="account-button" disabled={busy} onClick={() => setConfirm(null)}>Cancel</button><button className="account-button primary" disabled={busy} onClick={() => void confirm.action()}>{busy ? 'Working…' : 'Confirm'}</button></div></div></div>}
  </main>
}

export default function AdminAccount() {
  const { user } = useAuth()
  const { userId } = useParams()
  const [search, setSearch] = useSearchParams()
  const navigate = useNavigate()
  const selected = search.get('section') ?? 'overview'
  const section = sections.some(item => item.id === selected) ? selected : 'overview'
  const destination = search.get('return') ?? '/admin'
  return <AccountWorkspace key={userId} accountId={Number(userId)} currentUserId={user?.user_id} section={section} onSection={value => setSearch(previous => { const next = new URLSearchParams(previous); next.set('section', value); return next }, { replace: true })} onBack={() => navigate(destination === '/admin' || destination.startsWith('/admin?') ? destination : '/admin')} />
}
