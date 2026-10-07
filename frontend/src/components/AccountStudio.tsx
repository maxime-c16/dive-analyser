import { useEffect, useRef, useState } from 'react'
import { ArrowRight, GitBranch, Link2, ShieldCheck, UserRound } from 'lucide-react'
import { bindDiver, unbindDiver, getAccountStudio, listAllDivers, previewBinding, type AccountStudio as StudioData, type AdminUser, type AdminDiver, type BindingPreview } from '../services/adminUsersApi'
import AccountInvestigation from './AccountInvestigation'
import { AccountActionDialog } from './AccountSecurity'

export default function AccountStudio({ user, onRefresh }: { user: AdminUser; onRefresh: () => Promise<void> }) {
  const [data, setData] = useState<StudioData | null>(null)
  const [divers, setDivers] = useState<AdminDiver[]>([])
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [directoryPage, setDirectoryPage] = useState(0)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [staged, setStaged] = useState<BindingPreview | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [revision, setRevision] = useState(0)
  const tray = useRef<HTMLElement>(null)
  useEffect(() => {
    let live = true
    setError('')
    async function load() {
      const [first, directory] = await Promise.all([getAccountStudio(user.user_id), listAllDivers()])
      const bindings = [...first.bindings]
      for (let start = 50; start < first.total; start += 50) {
        const page = await getAccountStudio(user.user_id, start)
        bindings.push(...page.bindings)
        if (!page.bindings.length) break
      }
      if (live) { setData({ ...first, bindings }); setDivers(directory) }
    }
    void load().catch(reason => { if (live) setError(String(reason.message ?? reason)) })
    return () => { live = false }
  }, [user.user_id, user.is_active, user.is_admin, reload])
  async function stage(diverId: number, bound: boolean) {
    if (busy) return
    setBusy(true); setError(''); setNotice(''); setStaged(null)
    try { setStaged(await previewBinding(user.user_id, diverId, bound)) } catch (reason) { setError(String((reason as Error).message)) } finally { setBusy(false) }
  }
  useEffect(() => { if (staged) { tray.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' }); tray.current?.focus({ preventScroll: true }) } }, [staged])
  async function apply() {
    if (!staged) return
    setBusy(true); setError('')
    try {
      const latest = await previewBinding(user.user_id, staged.diver_id, staged.proposed_bound)
      if (JSON.stringify(latest) !== JSON.stringify(staged)) {
        setStaged(latest); setConfirm(false); setNotice('Access changed since this preview. Review the refreshed impact before confirming.'); return
      }
      if (staged.proposed_bound) await bindDiver(user.user_id, staged.diver_id)
      else await unbindDiver(user.user_id, staged.diver_id)
      setConfirm(false); setStaged(null); setNotice('Ownership updated. Access checks now use the new binding.'); setReload(v => v + 1); setRevision(v => v + 1)
      await onRefresh()
    } catch (reason) { setError(String((reason as Error).message)) } finally { setBusy(false) }
  }
  const linked = new Set(data?.bindings.map(b => b.diver_id))
  const filtered = [...divers].sort((a,b) => Number(linked.has(b.diver_id)) - Number(linked.has(a.diver_id))).filter(d => `${d.display_name} ${d.canonical_name} ${d.diver_id}`.toLowerCase().includes(query.toLowerCase()))
  return <>
    {!data && !error && <p role="status" className="account-muted">Loading ownership and effective access…</p>}
    {busy && !staged && <p role="status" className="account-muted">Loading change preview…</p>}
    {error && <div role="alert" className="account-alert">{error}<button className="account-button" disabled={busy} onClick={() => setReload(v => v + 1)}>Reload access</button></div>}
    {notice && <p role="status" className="account-success">{notice}</p>}
    <div className="account-metrics"><div><span>Owned collections</span><strong>{data?.total ?? '…'}</strong><small>Explicit diver bindings</small></div><div><span>Viewable dives</span><strong>{data?.viewable_dives ?? '…'}</strong><small>Effective viewing access</small></div><div><span>Manageable dives</span><strong>{data?.manageable_dives ?? '…'}</strong><small>Editing and deletion access</small></div><div><span>Live sessions</span><strong>{user.live_sessions}</strong><small>Unrevoked and unexpired</small></div></div>
    <article className="account-panel"><div className="account-panel-heading"><GitBranch size={18}/><h2>Ownership studio</h2><span className="account-badge">Live authorization</span></div><p className="account-muted">Follow the account’s ownership links. Workspace administration and signed-in public viewing are separate from diver ownership.</p><div className="studio-graph"><div className="studio-identity"><UserRound/><strong>{user.display_name}</strong><small>{user.is_active ? 'Active account' : 'Access suspended'}</small><span className="account-badge">{user.is_admin ? 'Administrator' : 'Diver'}</span></div><div className="studio-collections">{data?.bindings.slice(offset,offset + 6).map(binding => <div className="studio-collection" key={binding.diver_id}><small>EXPLICIT OWNERSHIP</small><div><strong>{binding.display_name}</strong><span>{binding.dive_count} dives</span></div><p>{user.is_active ? 'View · Edit · Delete' : 'Binding retained · Access blocked'}</p><button className="account-button" disabled={busy} onClick={() => void stage(binding.diver_id, false)}>Preview removal</button></div>)}{data && !data.total && <div className="studio-collection unlinked"><small>NO OWNERSHIP LINKS</small><strong>Connect a diver collection</strong><p>Use the directory below to preview the access this will grant.</p></div>}<div className="studio-collection public"><small>SIGNED-IN PUBLIC VIEWING</small><strong>Shared public dives</strong><p>{user.is_active ? 'Viewing allowed · Ownership required to manage' : 'Access blocked while account is disabled'}</p></div></div></div>{data && data.total > 6 && <div className="account-inline-save"><button className="account-button" disabled={!offset} onClick={() => setOffset(Math.max(0,offset-6))}>Previous collections</button><span>{offset+1}–{Math.min(offset+6,data.total)} of {data.total}</span><button className="account-button" disabled={offset+6>=data.total} onClick={() => setOffset(offset+6)}>Next collections</button></div>}</article>
    {staged && <article ref={tray} className="account-panel studio-preview" aria-label="Ownership change preview" tabIndex={-1}><div className="account-panel-heading"><Link2 size={18}/><h2>{staged.proposed_bound ? 'Grant' : 'Remove'} ownership · {staged.display_name}</h2></div><p className="account-muted">Impact across {staged.dive_count} dives in this collection. These are live counts at the time of the preview.</p><div className="studio-impact">{(['view','manage'] as const).map(key => <div key={key}><span>{key === 'view' ? 'Viewing access' : 'Editing & deletion'}</span><strong>{staged.before[key]} <ArrowRight size={16}/> {staged.after[key]} <small>dives</small></strong></div>)}</div><p className="account-muted">{staged.other_accounts} other account link(s) stay unchanged. {staged.public_dives} public dive(s) remain viewable while this account is active. Dive records and videos remain stored.</p>{!staged.account_active && <p className="account-warning">This account is disabled. The binding changes, but access stays blocked until it is restored.</p>}<div className="account-inline-save"><button className="account-button" disabled={busy} onClick={() => setStaged(null)}>Discard preview</button><button className="account-button primary" disabled={busy || staged.currently_bound === staged.proposed_bound} onClick={() => setConfirm(true)}>Review & confirm</button></div></article>}
    <div className="studio-columns"><div><AccountInvestigation refreshToken={revision} accountId={user.user_id} onResolve={id => void stage(id,true)}/><article className="account-panel"><div className="account-panel-heading"><ShieldCheck size={18}/><h2>Effective permissions</h2></div><div className="studio-capability"><strong>Workspace administration</strong><span>{user.is_active && user.is_admin ? 'Allowed' : 'Denied'}</span><small>Administrator role + active account</small></div><div className="studio-capability"><strong>Dive management</strong><span>{data?.manageable_dives ?? '…'} dives</span><small>Explicit ownership, plus unassigned dives for administrators</small></div><div className="studio-capability"><strong>Public viewing</strong><span>{user.is_active ? 'Allowed' : 'Denied'}</span><small>Signed-in viewing does not grant edit or delete access</small></div></article></div><article className="account-panel"><div className="account-panel-heading"><Link2 size={18}/><h2>Binding directory</h2></div><p className="account-muted">Search all divers, then review the exact access impact before changing ownership.</p><label className="account-search">Find a diver<input type="search" value={query} onChange={e => { setQuery(e.target.value); setDirectoryPage(0) }} placeholder="Name, canonical name or ID"/></label>{filtered.slice(directoryPage*10,directoryPage*10+10).map(d => <div className="account-binding" key={d.diver_id}><div className="account-binding-identity"><strong>{d.display_name}</strong><small>#{d.diver_id} · {linked.has(d.diver_id) ? 'Linked · Owner' : 'No ownership link'}{!d.active ? ' · Inactive diver' : ''}</small></div><button className="account-button" disabled={busy || !data} onClick={() => void stage(d.diver_id,!linked.has(d.diver_id))}>{linked.has(d.diver_id) ? 'Preview removal' : 'Preview grant'}</button></div>)}{data && !filtered.length && <p className="account-muted">No divers match your search.</p>}{filtered.length > 10 && <div className="account-inline-save"><button className="account-button" disabled={!directoryPage} onClick={() => setDirectoryPage(p=>p-1)}>Previous divers</button><span>{directoryPage*10+1}–{Math.min(directoryPage*10+10,filtered.length)} of {filtered.length}</span><button className="account-button" disabled={(directoryPage+1)*10>=filtered.length} onClick={() => setDirectoryPage(p=>p+1)}>Next divers</button></div>}</article></div>
    {confirm && staged && <AccountActionDialog title={`${staged.proposed_bound ? 'Grant' : 'Remove'} ownership for ${staged.display_name}?`} busy={busy} onCancel={() => setConfirm(false)} onConfirm={() => void apply()}><p>Viewing: {staged.before.view} → {staged.after.view} dives. Management: {staged.before.manage} → {staged.after.manage} dives. Other account links and stored dives are preserved.</p>{error && <p role="alert" className="account-alert">{error}</p>}</AccountActionDialog>}
  </>
}
