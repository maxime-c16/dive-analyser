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
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}});vi.mocked(api.post).mockResolvedValue({data:session});vi.mocked(api.get).mockResolvedValue({data:[{id:1,name:'Adultes',club_id:2,club:'Club test'}]})})
it('exchanges the fragment once without autoplay',async()=>{const {container}=render(<StrictMode>{page()}</StrictMode>);await screen.findByRole('button',{name:'Lire IMG.MOV'});expect(api.post).toHaveBeenCalledTimes(1);expect(container.querySelector('video')).toBeNull()})
it('rejects missing secrets before making a request',async()=>{render(page('/share/session/7'));expect(await screen.findByRole('alert')).toHaveTextContent('invalide');expect(api.post).not.toHaveBeenCalled()})
it('revoked links are unavailable',async()=>{vi.mocked(api.post).mockRejectedValue(new Error('404'));render(page());expect(await screen.findByRole('alert')).toHaveTextContent('indisponible')})
it('locked download opens onboarding with club then group and default email opt-in',async()=>{render(page());fireEvent.click(await screen.findByRole('button',{name:/Tout télécharger/}));await screen.findByRole('option',{name:'Club test'});expect(screen.getByRole('checkbox')).toBeChecked();fireEvent.change(screen.getByLabelText('Club'),{target:{value:'2'}});fireEvent.change(screen.getByLabelText('Groupe'),{target:{value:'1'}});fireEvent.change(screen.getByLabelText('Nom'),{target:{value:'Alex'}});fireEvent.change(screen.getByLabelText('E-mail'),{target:{value:'alex@example.test'}});fireEvent.change(screen.getByLabelText('Mot de passe'),{target:{value:'long-test-password'}});vi.mocked(api.post).mockResolvedValue({data:{path:'/sessions/shared/9'}});fireEvent.submit(screen.getByRole('button',{name:'Créer mon compte'}).closest('form')!);await waitFor(()=>expect(api.post).toHaveBeenLastCalledWith('/api/v1/shared-dives/sessions/7/signup',{display_name:'Alex',email:'alex@example.test',password:'long-test-password',group_id:1,email_enabled:true}));expect(await screen.findByText(/Vous recevrez/)).toBeInTheDocument()})
