// Development-only navigation review. No backend, credentials or real accounts.
import './clubs-review-data'
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import Router from '../../src/router'
import { AuthProvider } from '../../src/contexts/AuthContext'
import { api } from '../../src/services/api'
import '../../src/index.css'
import i18n from '../../src/i18n'
import SyncStatusContext, { type SyncContextType } from '../../src/contexts/SyncStatusContext'
import SyncNotifications from '../../src/components/SyncNotifications'
import SyncErrorHandler from '../../src/components/SyncErrorHandler'
import { EVALUATION_FIXTURES } from '../../src/services/evaluationApi'
if (!import.meta.env.DEV) throw new Error('Review fixture is development-only')
const params = new URLSearchParams(location.search)
void i18n.changeLanguage(params.get('lang') === 'fr' ? 'fr' : 'en')
const admin = new URLSearchParams(location.search).get('role') !== 'diver'
const attempts = Array.from({ length: params.has('long') ? 90 : 3 }, (_,i) => i+1).map(id => ({ id, dive_code: '103B', height: '3m', performance: 'G', performance_numeric: 3, dive_datetime: '2026-10-03T10:00:00', session_id: 1, diver_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', official_dd: 1.6, video_uuid: null, notes: 'Local fixture', visibility: 'public' }))
const peer = { user_id: 900002, display_name: 'Fixture Fanny', handle: 'fanny', bio: 'Local fixture', avatar_url: null }
const member = { ...peer, is_admin: false, is_self: false, joined_at: '2026-10-01', divers: [] }
const conversations = [1,2].map(id => ({ id, kind: 'direct', members: [peer], updated_at: '2026-10-09', unread_count: 0 }))
let messages = Array.from({ length: 12 }, (_,i) => ({ id:i+1, conversation_id:1, sender_id:900002, client_id:`local-${i}`, body:`Local message ${i+1}`, mentions:[], created_at:'2026-10-09T10:00:00Z',dive:null,receipts:[],reactions:[] }))
const managedUser = { user_id:900002, display_name:'Fixture Fanny',email:'fixture-fanny@example.test',role:'friend',is_admin:false,is_active:true,live_sessions:0,created_at:'2026-10-01',diver_ids:[],diver_binding_total:0 }
const nativeFetch = window.fetch.bind(window)
window.fetch = async (input, init) => {
  const url = String(input)
  if (url.includes('/api/v1/admin/clubs')) return (window as any).clubsReviewFetch(url, init)
  // Calendar API calls reach the network so browser tests can fulfil them (page.route).
  if (url.startsWith('/api/v1/calendar') || url.startsWith('/api/v1/auth/signup-clubs')) return nativeFetch(input, init)
  if (url.endsWith('/auth/me')) return Response.json({ user_id: 900001, email: 'fixture@example.test', display_name: 'Local reviewer', role: 'owner', is_admin: admin, divers: [{ diver_id: 1, access_kind: 'OWNER' }], features: { calendar: params.get('calendar') !== 'off' } })
  if (url.includes('/updates')) return Response.json({ schema: 1, version: 'v0.0.0', frontend_sha: 'a'.repeat(40), notes: params.get('path')?.startsWith('/calendar') ? [] : [{ id: 'local-review', date: '2026-10-09', title: 'Navigation simplifiée', body: 'Données locales pour vérifier la navigation et les overlays.' }] })
  if (url.includes('/messages/conversations')) {
    if (url.endsWith('/receipts')) return new Response(null, { status:204 })
    if (/\/messages(?:\?|$)/.test(url)) {
      if (init?.method === 'POST') { const value = JSON.parse(String(init.body)); const message = { ...messages[0], ...value, id:100+messages.length, sender_id:900001 }; messages.push(message); return Response.json(message) }
      return Response.json({ items:messages,next_before:null })
    }
    if (/conversations\/\d+$/.test(url)) return Response.json(conversations[0])
    return Response.json({ items:conversations,next_before:null })
  }
  if (/\/admin\/users\/\d+$/.test(url)) return Response.json(managedUser)
  if (url.includes('/admin/users')) return Response.json({ users:[managedUser],total:1,limit:50,offset:0 })
  if (/\/users\/\d+\/dives/.test(url)) return Response.json({ items:attempts.map(a => ({...a,poster_url:null})),next_before:null })
  if (/\/users\/\d+\/activity/.test(url)) return Response.json({ items:[],next_before:null })
  if (/\/users\/\d+$/.test(url)) return Response.json(member)
  if (url.includes('/users?')) return Response.json({ items:Array.from({length:params.has('long') ? 30 : 1},(_,i) => ({...peer,user_id:900002+i})),next_after:null })
  if (url.includes('/activity')) return Response.json({ items:[],next_before:null })
  return Response.json({ items: [], unread_count: params.has('unread') ? 12 : 0, total:0, next_before:null })
}
api.defaults.adapter = async config => {
  const url = config.url || ''
  let data: unknown = []
  if (url.endsWith('/dives/uploads') && params.has('holdUpload')) await new Promise<void>(resolve => Object.assign(window,{ finishReviewUpload:resolve }))
  if (url.endsWith('/dives/uploads')) data = { status: 'ready' }
  else if (url.endsWith('/dives/library')) data = { items: attempts, next_cursor: null }
  else if (/\/dives\/\d+$/.test(url)) data = attempts.find(a => a.id === Number(url.split('/').pop())) || attempts[0]
  else if (url.endsWith('/dives')) data = attempts
  else if (url.endsWith('/divers')) data = [{ id: 1, display_name: 'Fixture diver', is_primary_user: true }]
  else if (url.endsWith('/evaluations/overview')) data = { today:{date:'2026-10-18',resets_at:'2027-01-01T00:00:00Z',daily:{stack_id:1,daily:true,total:1,judged:1,skipped:0,remaining:0},resume:null,judged_today:1,votes:[]}, requests_pending:0,judged_total:1,judge:{compared:0,bias:null,streak:0} }
  else if (url.includes('/evaluations/') && url.endsWith('/queue')) data = { ...EVALUATION_FIXTURES.queueBatch, has_more:false, items:[EVALUATION_FIXTURES.queueBatch.items[0]] }
  else if (url.endsWith('/evaluations/sessions') || url.endsWith('/automatic/stacks')) data = { id:1,session_id:1,created_at:'2026-10-09' }
  else if (url.includes('/evaluations/')) data = { items:[],total:0,offset:0,limit:20 }
  else if (url.includes('/notifications')) data = { items: [], unread_count: 0 }
  else if (url.includes('/social')) data = { liked: false, like_count: 0, comment_count: 0 }
  else if (url.includes('/comments')) data = { items: [], next_before: null }
  else if (url.includes('/media/')) data = { status: 'missing', can_request: false, available_renditions: [] }
  return { data, status: 200, statusText: 'OK', headers: {}, config }
}
const router = createMemoryRouter([{ path: '*', element: <Router /> }], { initialEntries: [params.get('path') || '/dives'] })
Object.assign(window, { reviewRouter: router })
function Review() {
  const [notice, setNotice] = useState(false)
  Object.assign(window,{ showReviewSyncError:()=>setNotice(true) })
  const sync: SyncContextType = { isConnected:false,connectionError:null,clientId:'local',currentSync:notice ? { sync_id:'local',status:'error',total_videos:1,synced_count:0,error_count:1,progress_percent:0,duration_seconds:0 } : null,
    lastEvent:notice ? {type:'sync_error',sync_id:'local',timestamp:'2026-10-09T10:00:00Z',data:{error:'Local sync error'}} : null,
    recentMilestones:[],syncHistory:[],maxHistorySize:50,connect:()=>{},disconnect:()=>{},getStatus:()=>{},clearHistory:()=>{},removeMilestone:()=>{} }
  return <AuthProvider><SyncStatusContext.Provider value={sync}><RouterProvider router={router} /><SyncNotifications /><SyncErrorHandler /></SyncStatusContext.Provider></AuthProvider>
}
createRoot(document.getElementById('root')!).render(<Review />)
