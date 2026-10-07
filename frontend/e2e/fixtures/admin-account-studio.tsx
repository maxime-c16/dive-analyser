import React from 'react'
import { createRoot } from 'react-dom/client'
import { AccountWorkspace, securitySections } from '../../src/pages/AdminAccount'
import AccountSecurity from '../../src/components/AccountSecurity'
if (!import.meta.env.DEV) throw new Error('Development review only')
// Real production components with synthetic transport; no requests reach an account API.
let account = { user_id: 42, display_name: 'Camille Moreau', email: 'camille.moreau@example.test', role: 'friend', is_admin: false, is_active: true, live_sessions: 2, created_at: '2026-04-12T08:30:00Z', diver_ids: [10], diver_binding_total: 1 }
let bindings = [10]
let sessions = [{ session_id: 101, created_at: '2026-10-07T08:00:00Z', expires_at: '2026-10-14T08:00:00Z', last_used_at: '2026-10-07T12:00:00Z' }, { session_id: 102, created_at: '2026-10-06T08:00:00Z', expires_at: '2026-10-13T08:00:00Z', last_used_at: '2026-10-06T16:00:00Z' }]
const divers = [{ diver_id: 10, display_name: 'Camille · Training', canonical_name: 'camille-training', active: true, bound_to_user: true }, { diver_id: 11, display_name: 'Camille · Competition', canonical_name: 'camille-competition', active: true, bound_to_user: false }]
let events = [{ event_id: 1, event_type: 'ownership_granted', actor: 'admin:7', diver_id: 10 as number | null, created_at: '2026-10-06T10:00:00Z', details: {} }]
function event(type: string, diverId: number | null = null) { events.unshift({ event_id: events.length + 1, event_type: type, actor: 'admin:7', diver_id: diverId, created_at: new Date().toISOString(), details: {} }) }
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin), method = init?.method ?? 'GET'
  const id = Number(url.searchParams.get('diver_id')), bound = url.searchParams.get('bound') === 'true'
  if (url.pathname.endsWith('/binding-preview')) {
    const total = id === 10 ? 148 : 24, publicCount = id === 10 ? 12 : 4, current = bindings.includes(id)
    const impact = (linked: boolean) => ({ view: account.is_active ? linked ? total : publicCount : 0, manage: account.is_active && linked ? total : 0 })
    return Response.json({ user_id: 42, diver_id: id, display_name: divers.find(d=>d.diver_id===id)?.display_name, currently_bound: current, proposed_bound: bound, account_active: account.is_active, dive_count: total, public_dives: publicCount, other_accounts: 1, before: impact(current), after: impact(bound) })
  }
  if (url.pathname.endsWith('/access-studio')) return Response.json({ bindings: bindings.map(id => ({ diver_id: id, display_name: divers.find(d=>d.diver_id===id)!.display_name, dive_count: id===10 ? 148 : 24 })), total: bindings.length, viewable_dives: account.is_active ? bindings.includes(11) ? 172 : 152 : 0, manageable_dives: account.is_active ? bindings.includes(11) ? 172 : 148 : 0 })
  if (url.pathname.endsWith('/access-check')) {
    const linked = bindings.includes(11), active = account.is_active
    return Response.json({ user_id: 42, dive_id: Number(url.searchParams.get('dive_id')), diver_id: 11, visibility: 'private', account_active: active, can_view: active && linked, can_manage: active && linked, video_authorized: active && linked, explanation: !active ? 'Account is disabled.' : linked ? 'Explicit diver ownership allows viewing and management.' : 'Private dive access requires an explicit ownership binding to this diver.', checked_at: new Date().toISOString(), scope: 'Authorization only; video readiness and provider availability are not checked.' })
  }
  if (url.pathname.endsWith('/history')) { const filter = url.searchParams.get('event_type'); const filtered = events.filter(e=>!filter || filter===e.event_type); return Response.json({ events: filtered, total: filtered.length }) }
  if (method==='POST' && url.pathname.endsWith('/divers')) { const id = JSON.parse(String(init?.body)).diver_id; if (!bindings.includes(id)) bindings.push(id); event('ownership_granted',id) }
  if (method==='DELETE' && url.pathname.includes('/divers/')) { const id = Number(url.pathname.split('/').pop()); bindings=bindings.filter(b=>b!==id); event('ownership_revoked',id) }
  if (method==='DELETE' && url.pathname.includes('/sessions/')) { sessions=sessions.filter(s=>s.session_id!==Number(url.pathname.split('/').pop())); event('session_revoked') }
  if (method==='POST' && /revoke-sessions|reset-password/.test(url.pathname)) { sessions=[]; event(url.pathname.endsWith('reset-password') ? 'password_reset' : 'session_revoked') }
  if (method==='PATCH') { const body=JSON.parse(String(init?.body)); if (body.is_active===false || body.role && body.role !== (account.is_admin ? 'administrator' : 'diver')) sessions=[]; account={...account,...body,is_admin: body.role ? body.role==='administrator' : account.is_admin}; event(body.is_active !== undefined ? body.is_active ? 'user_enabled' : 'user_disabled' : 'user_updated') }
  account={...account,diver_ids:bindings,diver_binding_total:bindings.length,live_sessions:sessions.length}
  if (url.pathname.endsWith('/sessions')) return Response.json({ sessions, total:sessions.length })
  if (url.pathname.endsWith('/admin/divers')) return Response.json({ divers,total:divers.length })
  return Response.json(account)
}
function Review() {
  const [section,setSection] = React.useState(new URLSearchParams(location.search).get('section') ?? 'overview')
  React.useEffect(()=>{ const pop=()=>setSection(new URLSearchParams(location.search).get('section') ?? 'overview'); window.addEventListener('popstate',pop); return ()=>window.removeEventListener('popstate',pop) },[])
  return <><div style={{padding:'12px 20px',color:'#91a2af',font:'12px system-ui'}}>Production Studio components · Synthetic accounts · Safe to test · Dive #700 demonstrates resolution</div><AccountWorkspace accountId={42} currentUserId={7} section={section} extraSections={securitySections} onSection={value=>{history.pushState({},'',`?section=${value}`);setSection(value)}} onBack={()=>location.assign('./admin-account-review.html?layout=access')} renderExtra={(value,user,refresh)=><AccountSecurity key={value} accountId={user.user_id} section={value} self={false} onRefresh={refresh}/>} /></>
}
createRoot(document.getElementById('root')!).render(<Review/> )
