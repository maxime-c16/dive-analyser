import { useBottomAction } from '../navigation/useMobileNavigation'
import MemberAvatar from '../components/MemberAvatar'
import { useContext, useEffect, useState, type ReactNode } from 'react'
import { UNSAFE_DataRouterContext, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Check, Copy, ShieldCheck, UserRound, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { getUser, roleTitle, updateUser, type AdminUser, type PublicRole } from '../services/adminUsersApi'
import AccountStudio from '../components/AccountStudio'
import AccountSecurity, { AccountActionDialog } from '../components/AccountSecurity'
import AccountNavigationGuard from '../components/AccountNavigationGuard'
import PageLoading from '../components/PageLoading'
import './AdminAccount.css'

export type AccountLayout = 'tabs' | 'sidebar' | 'cards'
export type AccountSection = 'overview' | 'profile' | 'access'
const sections: { id: AccountSection; label: string }[] = [{ id: 'overview', label: 'Studio' }, { id: 'profile', label: 'Identity' }]
export const securitySections = [{ id: 'security', label: 'Security' }, { id: 'history', label: 'Audit trail' }, { id: 'lifecycle', label: 'Lifecycle' }]
const date = (value: string | null) => value ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleDateString(undefined, { dateStyle: 'medium' }) : 'Not recorded'

export function AccountWorkspace({ accountId, currentUserId, layout = 'tabs', onBack, section, onSection, extraSections = [], renderExtra }: {
  accountId: number; currentUserId?: number; layout?: AccountLayout; onBack: () => void;
  section: string; onSection: (section: string) => void; extraSections?: { id: string; label: string }[]; renderExtra?: (section: string, user: AdminUser, refresh: () => Promise<void>) => ReactNode;
}) {
  const [user, setUser] = useState<AdminUser | null>(null)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<PublicRole>('diver')
  const [active, setActive] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [confirm, setConfirm] = useState<{ title: string; body: string; action: () => Promise<void> } | null>(null)
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const self = accountId === currentUserId
  const dirty = !!user && (name !== user.display_name || email !== user.email || role !== (user.is_admin ? 'administrator' : 'diver') || active !== user.is_active)
  useBottomAction(dirty)
  const draftKey = `admin-account-draft:${currentUserId ?? 'unknown'}:${accountId}`
  const allSections = [...sections, ...extraSections]
  function setForm(value: AdminUser) { setName(value.display_name); setEmail(value.email); setRole(value.is_admin ? 'administrator' : 'diver'); setActive(value.is_active) }
  async function refresh() { const value = await getUser(accountId); setUser(value) }
  useEffect(() => {
    let live = true
    setUser(null); setError(''); setNotice('')
    getUser(accountId).then(value => { if (live) {
      setUser(value); setForm(value)
      try {
        const draft = JSON.parse(sessionStorage.getItem(draftKey) ?? 'null')
        if (draft && typeof draft.name === 'string' && typeof draft.email === 'string' && ['administrator','diver'].includes(draft.role) && typeof draft.active === 'boolean') {
          setName(draft.name); setEmail(draft.email); setRole(draft.role); setActive(draft.active); setNotice('Recovered unsaved profile edits from this browser session. Review or discard them.')
        }
      } catch { /* Editing remains available when browser storage is unavailable. */ }
    } }).catch(reason => { if (live) setError(String(reason.message ?? reason)) })
    return () => { live = false }
  }, [accountId, draftKey])
  useEffect(() => {
    if (!user) return
    try { if (dirty) sessionStorage.setItem(draftKey, JSON.stringify({ name, email, role, active })); else sessionStorage.removeItem(draftKey) } catch { /* Best-effort draft recovery. */ }
  }, [user, dirty, draftKey, name, email, role, active])
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
  if (!user) return <div className="account-workspace"><button className="account-button" onClick={onBack}><ArrowLeft size={16} /> Back to accounts</button>{error ? <div role="alert" className="account-alert">{error}<button onClick={() => { setError(''); void getUser(accountId).then(value => { setUser(value); setForm(value) }).catch(reason => setError(String(reason))) }}>Retry</button></div> : <PageLoading message="Loading account…" />}</div>
  const content = section === 'overview' || section === 'access' || section === 'support' ? <AccountStudio user={user} onRefresh={refresh}/> : section === 'profile' ? <article className="account-panel"><div className="account-panel-heading"><UserRound size={18} /><h2>Profile & account status</h2></div><p className="account-muted">Review identity and access level. Changes are saved together.</p><form id="account-profile" onSubmit={event => { event.preventDefault(); if (role !== (user.is_admin ? 'administrator' : 'diver') || active !== user.is_active) setConfirm({ title: 'Change account access?', body: 'Changing the role or disabling this account signs out its sessions. Diver bindings are preserved.', action: save }); else void save() }}><fieldset disabled={busy} className="account-form-grid"><label>Display name<input required maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label><label>Email address<input type="email" required maxLength={255} value={email} onChange={event => setEmail(event.target.value)} /></label><label>Workspace role<select value={role} disabled={self} onChange={event => setRole(event.target.value as PublicRole)}><option value="diver">Diver</option><option value="administrator">Administrator</option></select></label><label>Account status<select value={active ? 'active' : 'disabled'} disabled={self} onChange={event => setActive(event.target.value === 'active')}><option value="active">Active</option><option value="disabled">Disabled</option></select></label></fieldset>{self && <p className="account-muted">You cannot disable yourself or remove your own administrator access.</p>}<div className="account-inline-save"><button type="submit" className="account-button primary" disabled={busy || !dirty}>Save changes</button><button type="button" className="account-button" disabled={busy || !dirty} onClick={() => setForm(user)}>Discard</button></div></form></article> : section === 'lifecycle' ? <article className="account-panel"><div className="account-panel-heading"><ShieldCheck size={18}/><h2>Account lifecycle</h2></div><p className="account-muted">Suspend sign-in immediately or restore this account. Ownership links and dive records are retained.</p><dl className="account-facts"><div><dt>Current status</dt><dd>{user.is_active ? 'Active' : 'Disabled'}</dd></div><div><dt>Live sessions affected</dt><dd>{user.live_sessions}</dd></div><div><dt>Ownership links preserved</dt><dd>{user.diver_binding_total ?? 0}</dd></div></dl>{self ? <p className="account-muted">You cannot disable your own administrator account.</p> : <button className="account-button primary" disabled={busy || dirty} onClick={() => setConfirm({ title: user.is_active ? 'Suspend this account?' : 'Restore this account?', body: user.is_active ? 'Sign-in and resource access will be blocked immediately. All live sessions are signed out. Bindings, dives and audit history are preserved.' : 'Sign-in is restored with the existing password and ownership bindings. Previously revoked sessions remain signed out.', action: () => mutate(async () => { const value = await updateUser(accountId, { is_active: !user.is_active }); setUser(value); setForm(value) }, user.is_active ? 'Account suspended.' : 'Account restored.') })}>{user.is_active ? 'Suspend account' : 'Restore account'}</button>}{dirty && <p className="account-warning">Save or discard your Identity edits before changing the account lifecycle.</p>}</article> : renderExtra?.(section, user, refresh)
  return <div className={`account-workspace layout-${layout}`}>
    {dataRouter && <AccountNavigationGuard dirty={dirty}/>}
    <button className="account-back" onClick={() => { if (dataRouter || !dirty || window.confirm('Leave this account with unsaved changes?')) onBack() }}><ArrowLeft size={15} /> Accounts / Manage account</button>
    <header className="account-header"><MemberAvatar member={user} size={64} /><div className="account-header-identity"><div className="account-eyebrow">ACCOUNT WORKSPACE · #{user.user_id}</div><h1>{user.display_name}</h1><div className="account-email">{user.email}<button aria-label="Copy email" onClick={() => void copy(user.email)}><Copy size={14}/></button></div></div><div className="account-header-badges"><span className={`account-badge ${user.is_active ? 'positive' : 'negative'}`}><span/> {user.is_active ? 'Active' : 'Disabled'}</span><span className="account-badge"><ShieldCheck size={13}/>{roleTitle(user)}</span>{self && <span className="account-badge">Your account</span>}</div></header>
    {notice && <div role="status" className="account-success"><Check size={16}/>{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={14}/></button></div>}
    {error && <div role="alert" className="account-alert">{error}</div>}
    <div className="account-body"><nav role="tablist" aria-label="Account sections" className="account-section-nav">{allSections.map(item => <button role="tab" id={`account-tab-${item.id}`} aria-controls="account-tab-panel" aria-selected={section === item.id} tabIndex={section === item.id ? 0 : -1} onKeyDown={event => { const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']; if (!keys.includes(event.key)) return; event.preventDefault(); const index = allSections.findIndex(s => s.id === item.id); const next = event.key === 'Home' ? 0 : event.key === 'End' ? allSections.length-1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + allSections.length) % allSections.length; onSection(allSections[next].id); document.getElementById(`account-tab-${allSections[next].id}`)?.focus() }} key={item.id} aria-current={section === item.id ? 'page' : undefined} onClick={() => onSection(item.id)}>{item.label}</button>)}</nav><section role="tabpanel" id="account-tab-panel" aria-labelledby={`account-tab-${section}`} className="account-content">{section === 'overview' || section === 'access' || section === 'support' ? content : <div className="studio-columns"><div>{content}</div><aside className="account-panel studio-context"><div className="account-eyebrow">ACCOUNT CONTEXT</div><h2>{user.display_name}</h2><dl className="account-facts"><div><dt>Account</dt><dd>#{user.user_id}</dd></div><div><dt>Role</dt><dd>{roleTitle(user)}</dd></div><div><dt>Ownership links</dt><dd>{user.diver_binding_total ?? 0}</dd></div><div><dt>Live sessions</dt><dd>{user.live_sessions}</dd></div><div><dt>Created</dt><dd>{date(user.created_at)}</dd></div></dl><p className="account-muted">Account changes are recorded in the audit trail.</p></aside></div>}</section></div>
    {dirty && <div className="account-savebar"><div><strong>Unsaved changes</strong><small>Your edits are kept while switching sections.</small></div><button className="account-button" disabled={busy} onClick={() => setForm(user)}>Discard</button><button className="account-button primary" disabled={busy} onClick={() => { if (section === 'profile') (document.getElementById('account-profile') as HTMLFormElement | null)?.requestSubmit(); else onSection('profile') }}>Review & save</button></div>}
    {confirm && <AccountActionDialog title={confirm.title} busy={busy} onCancel={() => setConfirm(null)} onConfirm={() => void confirm.action()}><p>{confirm.body}</p>{error && <p role="alert" className="account-alert">{error}</p>}</AccountActionDialog>}
  </div>
}

export default function AdminAccount() {
  const { user } = useAuth()
  const { userId } = useParams()
  const [search, setSearch] = useSearchParams()
  const navigate = useNavigate()
  const requested = search.get('section') ?? 'overview'
  const selected = requested === 'access' || requested === 'support' ? 'overview' : requested
  const section = [...sections, ...securitySections].some(item => item.id === selected) ? selected : 'overview'
  const destination = search.get('return') ?? '/admin'
  return <AccountWorkspace key={userId} accountId={Number(userId)} currentUserId={user?.user_id} section={section} extraSections={securitySections} renderExtra={(value, account, refresh) => <AccountSecurity key={value} accountId={account.user_id} section={value} self={account.user_id === user?.user_id} onRefresh={refresh} />} onSection={value => setSearch(previous => { const next = new URLSearchParams(previous); next.set('section', value); return next })} onBack={() => navigate(destination === '/admin' || destination.startsWith('/admin?') ? destination : '/admin')} />
}
