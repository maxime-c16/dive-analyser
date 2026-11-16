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
it('opens the player only on tap, with one download and no repeated current thumbnail',async()=>{const {container}=page();await screen.findByRole('button',{name:'Play IMG.MOV'});expect(container.querySelector('video')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'Play IMG.MOV'}));await waitFor(()=>expect(container.querySelector('video')).toHaveAttribute('preload','none'));expect(screen.queryByRole('button',{name:'Play IMG.MOV'})).toBeNull();expect(screen.getAllByRole('button',{name:/Download ·/})).toHaveLength(1);expect(screen.queryByText(/Download all/)).toBeNull();expect(screen.getByRole('button',{name:'Share session'})).toBeInTheDocument()})
it('owner can hide and move a video',async()=>{vi.mocked(api.patch).mockResolvedValue({data:{}});render(<MemoryRouter><SessionGallery session={session as SharedTrainingSession} reload={vi.fn()}/></MemoryRouter>);fireEvent.click(await screen.findByRole('button',{name:'Session settings'}));fireEvent.click(screen.getByRole('button',{name:'Hide'}));await waitFor(()=>expect(api.patch).toHaveBeenCalledWith('/api/v1/session-videos/3',{hidden:true}));fireEvent.change(screen.getByLabelText('Destination date'),{target:{value:'2026-10-20'}});fireEvent.click(screen.getByRole('button',{name:'Move'}));await waitFor(()=>expect(api.patch).toHaveBeenCalledWith('/api/v1/session-videos/3',{date:'2026-10-20'}))})
it('friends see no owner settings',async()=>{vi.mocked(api.get).mockResolvedValue({data:{...session,videos:[{...video,can_share:false}]}});page();await screen.findByRole('button',{name:'Play IMG.MOV'});expect(screen.queryByRole('button',{name:'Session settings'})).toBeNull()})

it('keeps other recordings reachable while hiding the playing thumbnail',async()=>{
 vi.mocked(api.get).mockImplementation(async url=>({data:url==='/api/v1/shared-sessions/9/shares'?{active_count:0}:{...session,video_count:2,videos:[video,{...video,id:4,filename:'SECOND.MOV'}]}}))
 const {container}=page()
 fireEvent.click(await screen.findByRole('button',{name:'Play IMG.MOV'}))
 await waitFor(()=>expect(container.querySelector('video')).not.toBeNull())
 expect(screen.queryByRole('button',{name:'Play IMG.MOV'})).toBeNull()
 expect(screen.getByRole('button',{name:'Play SECOND.MOV'})).toBeInTheDocument()
 expect(screen.getByRole('button',{name:/Download all/})).toBeInTheDocument()
})

it('deduplicates pagination and prevents concurrent load-more requests', async () => {
 let resolve!: (value: unknown) => void
 const pending = new Promise(r => { resolve = r })
 vi.mocked(api.get).mockImplementation(url => url === '/api/v1/shared-sessions/9' ? pending as any : Promise.resolve({data:{active_count:0}}))
 render(<MemoryRouter><SessionGallery session={{...session,next_video_id:3} as SharedTrainingSession}/></MemoryRouter>)
 const more = screen.getByRole('button',{name:'Load more recordings'})
 fireEvent.click(more); fireEvent.click(more)
 expect(vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/shared-sessions/9')).toHaveLength(1)
 resolve({data:{...session,videos:[video,{...video,id:4,filename:'SECOND.MOV'}],next_video_id:null}})
 await screen.findByRole('button',{name:'Play SECOND.MOV'})
 expect(screen.getAllByRole('button',{name:'Play IMG.MOV'})).toHaveLength(1)
 expect(screen.queryByRole('button',{name:'Load more recordings'})).toBeNull()
})

it('ignores an old page response after switching sessions', async () => {
 let resolve!: (value: unknown) => void
 vi.mocked(api.get).mockImplementation(() => new Promise(r => {resolve=r}))
 const {rerender}=render(<MemoryRouter><SessionGallery session={{...session,next_video_id:3} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:'Load more recordings'}))
 rerender(<MemoryRouter><SessionGallery session={{...session,session_id:10,videos:[{...video,id:8,filename:'NEW.MOV'}]} as SharedTrainingSession}/></MemoryRouter>)
 resolve({data:{...session,videos:[{...video,id:4,filename:'OLD.MOV'}],next_video_id:null}})
 await waitFor(()=>expect(screen.getByRole('button',{name:'Play NEW.MOV'})).toBeInTheDocument())
 expect(screen.queryByRole('button',{name:'Play OLD.MOV'})).toBeNull()
})

it('navigates recordings and returns keyboard focus when closing the player', async () => {
 const {container}=render(<MemoryRouter><SessionGallery session={{...session,video_count:2,videos:[video,{...video,id:4,filename:'SECOND.MOV'}]} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:'Play IMG.MOV'}))
 await waitFor(()=>expect(container.querySelector('video')).not.toBeNull())
 expect(screen.getByRole('button',{name:'Previous recording'})).toBeDisabled()
 fireEvent.click(screen.getByRole('button',{name:'Next recording'}))
 expect(screen.getByRole('heading',{name:'SECOND.MOV'})).toHaveFocus()
 fireEvent.click(screen.getByRole('button',{name:'Close player'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'Play SECOND.MOV'})).toHaveFocus())
})

it('requires a second deliberate action before deleting a recording', async () => {
 render(<MemoryRouter><SessionGallery session={session as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:'Session settings'}))
 fireEvent.click(screen.getByRole('button',{name:'Delete'}))
 expect(api.patch).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Cancel'}))
 expect(screen.queryByRole('group',{name:'Delete this recording?'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'Delete'}))
 fireEvent.click(screen.getByRole('button',{name:'Delete'}))
 await waitFor(()=>expect(api.patch).toHaveBeenCalledWith('/api/v1/session-videos/3',{delete:true}))
})

it('stops scheduling downloads when the gallery is left', async () => {
 const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{})
 const {unmount}=render(<MemoryRouter><SessionGallery session={{...session,video_count:2,videos:[video,{...video,id:4}]} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:/Download all/}))
 expect(click).toHaveBeenCalledTimes(1)
 unmount()
 await new Promise(resolve=>setTimeout(resolve,1050))
 expect(click).toHaveBeenCalledTimes(1)
 click.mockRestore()
})

it('offers a working retry after a session request fails', async () => {
 vi.mocked(api.get).mockRejectedValueOnce(new Error('Offline'))
 page()
 expect(await screen.findByRole('alert')).toHaveTextContent('This session video is unavailable.')
 fireEvent.click(screen.getByRole('button',{name:'Try again'}))
 expect(await screen.findByRole('button',{name:'Play IMG.MOV'})).toBeInTheDocument()
})
