import { beforeEach, expect, it, vi } from 'vitest'
import { navPolicyFor, primaryTabFor, readTabContext, saveTabContext, withoutClip } from './mobileNavigation'
import { readMessageDraft, saveMessageDraft } from './messageDraft'
beforeEach(() => sessionStorage.clear())
it.each([['/dives','dives'], ['/dives/analysis/103B','dives'], ['/messages/12','messages'], ['/users/9','community'], ['/community','community'], ['/evaluations/','evaluations'], ['/admin',null], ['/account',null], ['/dives-other',null]])('maps %s to %s', (path, expected) => expect(primaryTabFor(path)).toBe(expected))
it.each([
  ['/dives',390,{},'visible'], ['/messages/12',390,{},'replaced'], ['/messages/12',768,{},'visible'], ['/dives',1023,{},'visible'], ['/dives',1024,{},'hidden'], ['/share/abc',390,{},'hidden'], ['/login',390,{},'hidden'], ['/dives',390,{ overlays: 2 },'hidden'], ['/evaluations',390,{ overlays: 1 },'hidden'], ['/account',390,{ editing: true },'hidden'], ['/admin/users/1',390,{ bottomAction: true },'replaced'], ['/dives',390,{ clip: true },'hidden'],
] as const)('policy %s %s %j = %s', (path,width,state,result) => expect(navPolicyFor(path,width,state)).toBe(result))
it('removes only the clip, preserving filters and encoding semantics', () => expect(withoutClip('/dives?q=103+B&clip=2&scope=all')).toBe('/dives?q=103+B&scope=all'))
it('keeps tab context per account and never restores a viewer', () => {
  saveTabContext(1,'dives',{ url:'/dives?q=103&clip=4',scroll:420 })
  expect(readTabContext(1,'dives')).toEqual({ url:'/dives?q=103',scroll:420 })
  expect(readTabContext(2,'dives')).toBeNull()
})
it.each(['{"url":"//evil.test/dives","scroll":1}', '{"url":"/account","scroll":1}', '{"url":"/dives","scroll":-1}', 'bad'])('rejects corrupt navigation context %s', value => {
  sessionStorage.setItem('mobile-nav:v1:1:dives',value)
  expect(readTabContext(1,'dives')).toBeNull()
})
it('keeps Unicode mention identity in drafts per account/conversation and clears after send', () => {
  const draft = { body:'Hi 🐬 @Fanny',mentions:[{ user_id:2,start:6,end:12 }] }
  saveMessageDraft(1,3,draft)
  expect(readMessageDraft(1,3)).toEqual(draft)
  expect(readMessageDraft(1,4).body).toBe(''); expect(readMessageDraft(2,3).body).toBe('')
  saveMessageDraft(1,3,{ body:'',mentions:[] }); expect(sessionStorage.getItem('message-draft:v1:1:3')).toBeNull()
})
it('drops invalid mention spans and tolerates unavailable storage', () => {
  sessionStorage.setItem('message-draft:v1:1:3', JSON.stringify({body:'hi',mentions:[{user_id:2,start:0,end:8},null]}))
  expect(readMessageDraft(1,3)).toEqual({body:'hi',mentions:[]})
  const spy = vi.spyOn(Object.getPrototypeOf(sessionStorage),'getItem').mockImplementation(() => { throw new Error('denied') })
  expect(readMessageDraft(1,3).body).toBe(''); expect(readTabContext(1,'dives')).toBeNull(); spy.mockRestore()
})
it('abandoning a failed draft clears its send identity', async () => {
  const {savePendingSend,readPendingSend}=await import('./messageDraft')
  savePendingSend(1,3,{value:'old',key:'retry'})
  saveMessageDraft(1,3,{body:'',mentions:[]})
  expect(readPendingSend(1,3)).toBeNull()
})
it('purges recovery data on sign out or confirmed expired session, keeping unrelated preferences',async()=>{
  const {clearNavigationSession}=await import('./sessionContext')
  sessionStorage.setItem('message-draft:v1:1:3','draft');sessionStorage.setItem('mobile-nav:v1:2:dives','context');sessionStorage.setItem('preference','dark')
  clearNavigationSession(1);expect(sessionStorage.getItem('message-draft:v1:1:3')).toBeNull();expect(sessionStorage.getItem('mobile-nav:v1:2:dives')).toBe('context')
  clearNavigationSession();expect(sessionStorage.getItem('mobile-nav:v1:2:dives')).toBeNull();expect(sessionStorage.getItem('preference')).toBe('dark')
})
