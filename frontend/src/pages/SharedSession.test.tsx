import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import SharedSession from './SharedSession'
import { api } from '../services/api'
vi.mock('../services/api',()=>({api:{get:vi.fn(),post:vi.fn(),put:vi.fn(),delete:vi.fn()}}))
const token='s'.repeat(43)
const video={id:3,filename:'IMG.MOV',can_share:false,video_url:'/guest/play'}
const session={session_id:9,date:'2026-10-17',videos:[video],video_count:1,total_duration:1936,total_bytes:3338404955}
const page=(path=`/share/session/7#${token}`)=><MemoryRouter initialEntries={[path]}><Routes><Route path="/share/session/:shareId" element={<SharedSession/>}/></Routes></MemoryRouter>
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}});vi.mocked(api.post).mockResolvedValue({data:session});vi.mocked(api.get).mockImplementation((url)=>Promise.resolve({data:String(url).includes('/groups')?{items:[{id:1,name:'Adultes',club_id:2,club:'Club test'}],next_after:null}:String(url).includes('/clubs')?[{club_id:2,club:'Club test'}]:[{id:1,name:'Adultes',club_id:2,club:'Club test'}]}))})
it('exchanges the fragment once without autoplay',async()=>{const {container}=render(<StrictMode>{page()}</StrictMode>);await screen.findByRole('button',{name:'Lire IMG.MOV'});expect(api.post).toHaveBeenCalledTimes(1);expect(container.querySelector('video')).toBeNull()})
it('rejects missing secrets before making a request',async()=>{render(page('/share/session/7'));expect(await screen.findByRole('alert')).toHaveTextContent('invalide');expect(api.post).not.toHaveBeenCalled()})
it('revoked links are unavailable',async()=>{vi.mocked(api.post).mockRejectedValue(new Error('404'));render(page());expect(await screen.findByRole('alert')).toHaveTextContent('indisponible')})
it('uses separate account, club, group and email screens with opt-in enabled',async()=>{
 render(page())
 fireEvent.click(await screen.findByRole('button',{name:/Télécharger ·/}))
 expect(await screen.findByRole('heading',{name:'Créer mon compte'})).toBeInTheDocument()
 expect(screen.queryByRole('combobox')).toBeNull()
 fireEvent.change(screen.getByLabelText('Nom'),{target:{value:'Alex'}})
 fireEvent.change(screen.getByLabelText('E-mail'),{target:{value:'alex@example.test'}})
 fireEvent.change(screen.getByLabelText('Mot de passe'),{target:{value:'long-test-password'}})
 fireEvent.submit(screen.getByRole('button',{name:'Continuer'}).closest('form')!)
 await screen.findByRole('option',{name:'Club test'})
 expect(screen.getByRole('heading',{name:'Mon club'})).toBeInTheDocument()
 expect(screen.queryByLabelText('Nom')).toBeNull()
 fireEvent.change(screen.getByLabelText('Club'),{target:{value:'2'}})
 fireEvent.submit(screen.getByRole('button',{name:'Continuer'}).closest('form')!)
 expect(screen.getByRole('heading',{name:'Mon groupe'})).toBeInTheDocument()
 expect(screen.queryByLabelText('Club')).toBeNull()
 await screen.findByRole('option',{name:'Adultes'})
 fireEvent.change(screen.getByLabelText('Groupe'),{target:{value:'1'}})
 vi.mocked(api.post).mockResolvedValue({data:{path:'/sessions/shared/9'}})
 fireEvent.submit(screen.getByRole('button',{name:'Créer mon compte'}).closest('form')!)
 await waitFor(()=>expect(api.post).toHaveBeenLastCalledWith('/api/v1/shared-dives/sessions/7/signup',{display_name:'Alex',email:'alex@example.test',password:'long-test-password',group_id:1,email_enabled:true}))
 expect(await screen.findByRole('heading',{name:'Les prochaines séances'})).toBeInTheDocument()
 expect(screen.getByRole('checkbox',{name:'Recevoir un e-mail pour mon groupe'})).toBeChecked()
 expect(screen.queryByLabelText('Mot de passe')).toBeNull()
})
it('follows paged group lists',async()=>{
  vi.mocked(api.get).mockImplementation((async (url:string,config?:{params?:Record<string,unknown>})=>{
    if (url.includes('/clubs')) return { data: [{ club_id: 2, club: 'Club test' }, { club_id: 3, club: 'Club two' }] }
    if(!url.includes('/groups'))return {data:[]}
    if(!config?.params?.after_id)return {data:{items:[{id:1,name:'A',club_id:2,club:'Club test'}],next_after:{club:'Club test',group:'A',id:1}}}
    return {data:{items:[{id:2,name:'B',club_id:3,club:'Club two'}],next_after:null}}}) as typeof api.get)
  render(page())
  fireEvent.click(await screen.findByRole('button',{name:/Télécharger ·/}))
  fireEvent.change(screen.getByLabelText('Nom'),{target:{value:'Alex'}})
  fireEvent.change(screen.getByLabelText('E-mail'),{target:{value:'alex@example.test'}})
  fireEvent.change(screen.getByLabelText('Mot de passe'),{target:{value:'long-test-password'}})
  fireEvent.submit(screen.getByRole('button',{name:'Continuer'}).closest('form')!)
  expect(await screen.findByRole('option',{name:'Club test'})).toBeInTheDocument()
  expect(screen.getByRole('option',{name:'Club two'})).toBeInTheDocument()
})
it('offers the existing-account login with the same panel and no signup fields',async()=>{
 render(page());fireEvent.click(await screen.findByRole('button',{name:'Se connecter'}))
 expect(screen.getByRole('heading',{name:'Se connecter'})).toBeInTheDocument()
 expect(screen.getByLabelText('E-mail')).toBeInTheDocument()
 expect(screen.queryByLabelText('Nom')).toBeNull()
 expect(screen.queryByRole('combobox')).toBeNull()
})
it('preserves account values when going back from club selection',async()=>{
 render(page());fireEvent.click(await screen.findByRole('button',{name:/Télécharger ·/}))
 fireEvent.change(screen.getByLabelText('Nom'),{target:{value:'Alex'}})
 fireEvent.submit(screen.getByRole('button',{name:'Continuer'}).closest('form')!)
 fireEvent.click(screen.getByRole('button',{name:'Retour'}))
 expect(screen.getByLabelText('Nom')).toHaveValue('Alex')
})
