import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import SharedSession from './SharedSession'
import { api } from '../services/api'
const auth = vi.hoisted(() => ({ checking: false, user: null as { user_id: number } | null, refresh: vi.fn() }))
vi.mock('../contexts/AuthContext',()=>({useAuth:()=>auth}))
vi.mock('../services/api',()=>({api:{get:vi.fn(),post:vi.fn(),put:vi.fn(),delete:vi.fn()}}))
const token='s'.repeat(43)
const video={id:3,filename:'IMG.MOV',can_share:false,video_url:'/guest/play'}
const session={session_id:9,date:'2026-10-17',videos:[video],video_count:1,total_duration:1936,total_bytes:3338404955}
const page=(path=`/share/session/7#${token}`)=><MemoryRouter initialEntries={[path]}><Routes><Route path="/share/session/:shareId" element={<SharedSession/>}/></Routes></MemoryRouter>
async function openDownloadAccess() {
 fireEvent.click(await screen.findByRole('button',{name:/Sign in to download/}))
 return screen.getByRole('dialog',{name:'Download recordings'})
}
async function createAccount() {
 const access=await openDownloadAccess()
 fireEvent.click(within(access).getByRole('button',{name:'Create an account'}))
}
beforeEach(()=>{auth.checking=false;auth.user=null;vi.clearAllMocks();vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}});vi.mocked(api.post).mockResolvedValue({data:session});vi.mocked(api.get).mockImplementation((url)=>Promise.resolve({data:String(url).includes('/groups')?{items:[{id:1,name:'Adultes',club_id:2,club:'Club test'}],next_after:null}:String(url).includes('/clubs')?{items:[{club_id:2,club:'Club test'}],next_after:null}:[{id:1,name:'Adultes',club_id:2,club:'Club test'}]}))})
it('exchanges the fragment once without autoplay',async()=>{const {container}=render(<StrictMode>{page()}</StrictMode>);await screen.findByRole('button',{name:'Watch IMG.MOV'});expect(api.post).toHaveBeenCalledTimes(1);expect(container.querySelector('video')).toBeNull()})
it('rejects missing secrets before making a request',async()=>{render(page('/share/session/7'));expect(await screen.findByRole('alert')).toHaveTextContent('invalid');expect(api.post).not.toHaveBeenCalled()})
it('revoked links are unavailable',async()=>{vi.mocked(api.post).mockRejectedValue(new Error('404'));render(page());expect(await screen.findByRole('alert')).toHaveTextContent('unavailable')})
it('uses separate account, club, group and email screens with opt-in enabled',async()=>{
 render(page())
 await createAccount()
 expect(await screen.findByRole('heading',{name:'Create my account'})).toBeInTheDocument()
 expect(screen.queryByRole('combobox')).toBeNull()
 fireEvent.change(screen.getByLabelText('Name'),{target:{value:'Alex'}})
 fireEvent.change(screen.getByLabelText('Email'),{target:{value:'alex@example.test'}})
 fireEvent.change(screen.getByLabelText('Password'),{target:{value:'long-test-password'}})
 fireEvent.submit(screen.getByRole('button',{name:'Continue'}).closest('form')!)
 await screen.findByRole('option',{name:'Club test'})
 expect(screen.getByRole('heading',{name:'My club'})).toBeInTheDocument()
 expect(screen.queryByLabelText('Name')).toBeNull()
 fireEvent.change(screen.getByLabelText('Club'),{target:{value:'2'}})
 fireEvent.submit(screen.getByRole('button',{name:'Continue'}).closest('form')!)
 expect(screen.getByRole('heading',{name:'My group'})).toBeInTheDocument()
 expect(screen.queryByLabelText('Club')).toBeNull()
 await screen.findByRole('option',{name:'Adultes'})
 fireEvent.change(screen.getByLabelText('Group'),{target:{value:'1'}})
 vi.mocked(api.post).mockResolvedValue({data:{path:'/sessions/shared/9'}})
 fireEvent.submit(screen.getByRole('button',{name:'Create my account'}).closest('form')!)
 await waitFor(()=>expect(api.post).toHaveBeenLastCalledWith('/api/v1/shared-dives/sessions/7/signup',{display_name:'Alex',email:'alex@example.test',password:'long-test-password',group_id:1,email_enabled:true}))
 expect(await screen.findByRole('heading',{name:'Upcoming sessions'})).toBeInTheDocument()
 expect(screen.getByRole('checkbox',{name:'Email me about sessions for my group'})).toBeChecked()
 expect(screen.queryByLabelText('Password')).toBeNull()
})
it('follows paged group lists',async()=>{
  vi.mocked(api.get).mockImplementation((async (url:string,config?:{params?:Record<string,unknown>})=>{
    if (url.includes('/clubs')) return { data: { items: [{ club_id: 2, club: 'Club test' }, { club_id: 3, club: 'Club two' }], next_after: null } }
    if(!url.includes('/groups'))return {data:[]}
    if(!config?.params?.after_id)return {data:{items:[{id:1,name:'A',club_id:2,club:'Club test'}],next_after:{club:'Club test',group:'A',id:1}}}
    return {data:{items:[{id:2,name:'B',club_id:3,club:'Club two'}],next_after:null}}}) as typeof api.get)
  render(page())
  await createAccount()
  fireEvent.change(screen.getByLabelText('Name'),{target:{value:'Alex'}})
  fireEvent.change(screen.getByLabelText('Email'),{target:{value:'alex@example.test'}})
  fireEvent.change(screen.getByLabelText('Password'),{target:{value:'long-test-password'}})
  fireEvent.submit(screen.getByRole('button',{name:'Continue'}).closest('form')!)
  expect(await screen.findByRole('option',{name:'Club test'})).toBeInTheDocument()
  expect(screen.getByRole('option',{name:'Club two'})).toBeInTheDocument()
})
it('loads more clubs on demand instead of the whole catalog',async()=>{
  vi.mocked(api.get).mockImplementation(((url:string,config?:{params?:Record<string,unknown>})=>{
    if(url.includes('/clubs'))return Promise.resolve(!config?.params?.after_id?{data:{items:[{club_id:2,club:'Club test'}],next_after:{club:'Club test',id:2}}}:{data:{items:[{club_id:3,club:'Club two'}],next_after:null}})
    if(url.includes('/groups'))return Promise.resolve({data:{items:[],next_after:null}})
    return Promise.resolve({data:[]})}) as typeof api.get)
  render(page())
  await createAccount()
  fireEvent.change(screen.getByLabelText('Name'),{target:{value:'Alex'}})
  fireEvent.change(screen.getByLabelText('Email'),{target:{value:'alex@example.test'}})
  fireEvent.change(screen.getByLabelText('Password'),{target:{value:'long-test-password'}})
  fireEvent.submit(screen.getByRole('button',{name:'Continue'}).closest('form')!)
  expect(await screen.findByRole('option',{name:'Club test'})).toBeInTheDocument()
  expect(screen.queryByRole('option',{name:'Club two'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'Show more clubs'}))
  expect(await screen.findByRole('option',{name:'Club two'})).toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'Show more clubs'})).toBeNull()
})
it('cancels pending club requests on unmount',async()=>{
  const signals:AbortSignal[]=[]
  vi.mocked(api.get).mockImplementation(((_url:string,config?:{signal?:AbortSignal})=>{
    if(config?.signal)signals.push(config.signal)
    return new Promise(()=>{})}) as typeof api.get)
  const {unmount}=render(page())
  await createAccount()
  await waitFor(()=>expect(signals.length).toBeGreaterThan(0))
  unmount()
  expect(signals.every(signal=>signal.aborted)).toBe(true)
})
it('offers the existing-account login with the same panel and no signup fields',async()=>{
 render(page());fireEvent.click(await screen.findByRole('button',{name:'Sign in'}))
 expect(screen.getByRole('heading',{name:'Sign in'})).toBeInTheDocument()
 expect(screen.getByLabelText('Email')).toBeInTheDocument()
 expect(screen.queryByLabelText('Name')).toBeNull()
 expect(screen.queryByRole('combobox')).toBeNull()
})
it('preserves account values when going back from club selection',async()=>{
 render(page());await createAccount()
 fireEvent.change(screen.getByLabelText('Name'),{target:{value:'Alex'}})
 fireEvent.submit(screen.getByRole('button',{name:'Continue'}).closest('form')!)
 fireEvent.click(screen.getByRole('button',{name:'Back'}))
 expect(screen.getByLabelText('Name')).toHaveValue('Alex')
})

it('offers login at the download gate and restores focus if the guest dismisses it', async () => {
 render(page())
 let access = await openDownloadAccess()
 expect(within(access).getByRole('button',{name:'Sign in'})).toHaveFocus()
 fireEvent.keyDown(document,{key:'Escape'})
 await waitFor(()=>expect(screen.getByRole('button',{name:/Sign in to download/})).toHaveFocus())
 access = await openDownloadAccess()
 fireEvent.click(within(access).getByRole('button',{name:'Sign in'}))
 expect(screen.getByRole('heading',{name:'Sign in'})).toBeInTheDocument()
})

it('restores the guest download control inside the player after returning from sign-in', async () => {
 render(page())
 fireEvent.click(await screen.findByRole('button',{name:'Watch IMG.MOV'}))
 const player = screen.getByRole('dialog',{name:'IMG.MOV'})
 fireEvent.click(within(player).getByRole('button',{name:/Sign in to download IMG/}))
 const access = screen.getByRole('dialog',{name:'Download recordings'})
 fireEvent.click(within(access).getByRole('button',{name:'Sign in'}))
 expect(screen.getByRole('heading',{name:'Sign in'})).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'Back'}))
 const reopened = screen.getByRole('dialog',{name:'IMG.MOV'})
 expect(within(reopened).getByRole('button',{name:/Sign in to download IMG/})).toHaveFocus()
 expect(screen.queryByRole('dialog',{name:'Download recordings'})).toBeNull()
})

it('waits for authentication before visiting the shared link and does not visit twice on login', async () => {
 auth.checking=true
 const {rerender}=render(page())
 expect(api.post).not.toHaveBeenCalled()
 auth.checking=false
 auth.user={user_id:10}
 rerender(page())
 await waitFor(()=>expect(api.post).toHaveBeenCalledTimes(1))
})
