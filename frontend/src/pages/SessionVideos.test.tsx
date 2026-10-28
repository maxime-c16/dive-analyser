import SessionGallery from '../components/session-video/SessionGallery'
import type { SharedTrainingSession } from '../services/sessionVideosApi'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import SessionVideoPage from './SessionVideos'
import { api } from '../services/api'
vi.mock('../services/api',()=>({api:{get:vi.fn(),post:vi.fn(),patch:vi.fn(),delete:vi.fn()}}))
const video={id:3,session_id:9,filename:'IMG.MOV',recorded_at:null,recorded_date:'2026-10-17',duration_seconds:1936,size_bytes:3338404955,codec_string:'hvc1.2.4.L123.B0',width:1920,height:1080,fps:60,bit_rate:1000000,can_share:true}
const session={session_id:9,date:'2026-10-17',videos:[video],video_count:1,total_duration:1936,total_bytes:3338404955}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.post).mockResolvedValue({data:null});vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}})
 Object.defineProperty(navigator,'mediaCapabilities',{value:{decodingInfo:async()=>({supported:true})},configurable:true})
 vi.mocked(api.get).mockImplementation(async url=>({data:url==='/api/v1/shared-sessions'?{items:[session]}:url==='/api/v1/session-videos/3'?video:url==='/api/v1/shared-sessions/9/shares'?{active_count:0}:session}))
})
const page=()=>render(<MemoryRouter initialEntries={['/sessions/shared/9']}><Routes><Route path="/sessions/shared/:sessionId" element={<SessionVideoPage/>}/></Routes></MemoryRouter>)
it('opens the player only on tap, with one download and no repeated current thumbnail',async()=>{const {container}=page();await screen.findByRole('button',{name:'Lire IMG.MOV'});expect(container.querySelector('video')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'Lire IMG.MOV'}));await waitFor(()=>expect(container.querySelector('video')).toHaveAttribute('preload','none'));expect(screen.queryByRole('button',{name:'Lire IMG.MOV'})).toBeNull();expect(screen.getAllByRole('button',{name:/Télécharger ·/})).toHaveLength(1);expect(screen.queryByText(/Tout télécharger/)).toBeNull();expect(screen.getByRole('button',{name:'Partager'})).toBeInTheDocument()})
it('owner can hide and move a video',async()=>{vi.mocked(api.patch).mockResolvedValue({data:{}});render(<MemoryRouter><SessionGallery session={session as SharedTrainingSession} reload={vi.fn()}/></MemoryRouter>);fireEvent.click(await screen.findByRole('button',{name:'Réglages'}));fireEvent.click(screen.getByRole('button',{name:'Masquer'}));await waitFor(()=>expect(api.patch).toHaveBeenCalledWith('/api/v1/session-videos/3',{hidden:true}));fireEvent.change(screen.getByLabelText('Date de destination'),{target:{value:'2026-10-20'}});fireEvent.click(screen.getByRole('button',{name:'Déplacer'}));await waitFor(()=>expect(api.patch).toHaveBeenCalledWith('/api/v1/session-videos/3',{date:'2026-10-20'}))})
it('friends see no owner settings',async()=>{vi.mocked(api.get).mockResolvedValue({data:{...session,videos:[{...video,can_share:false}]}});page();await screen.findByRole('button',{name:'Lire IMG.MOV'});expect(screen.queryByRole('button',{name:'Réglages'})).toBeNull()})

it('keeps other recordings reachable while hiding the playing thumbnail',async()=>{
 vi.mocked(api.get).mockImplementation(async url=>({data:url==='/api/v1/shared-sessions/9/shares'?{active_count:0}:{...session,video_count:2,videos:[video,{...video,id:4,filename:'SECOND.MOV'}]}}))
 const {container}=page()
 fireEvent.click(await screen.findByRole('button',{name:'Lire IMG.MOV'}))
 await waitFor(()=>expect(container.querySelector('video')).not.toBeNull())
 expect(screen.queryByRole('button',{name:'Lire IMG.MOV'})).toBeNull()
 expect(screen.getByRole('button',{name:'Lire SECOND.MOV'})).toBeInTheDocument()
 expect(screen.getByRole('button',{name:/Tout télécharger/})).toBeInTheDocument()
})
