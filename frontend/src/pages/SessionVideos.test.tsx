import SessionGallery from '../components/session-video/SessionGallery'
import type { SharedTrainingSession } from '../services/sessionVideosApi'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SessionVideoPage from './SessionVideos'
import { api } from '../services/api'
vi.mock('../services/api',()=>({api:{get:vi.fn(),post:vi.fn(),patch:vi.fn(),delete:vi.fn()}}))
const video={id:3,session_id:9,filename:'IMG.MOV',recorded_at:null,recorded_date:'2026-10-17',duration_seconds:1936,size_bytes:3338404955,codec_string:'hvc1.2.4.L123.B0',width:1920,height:1080,fps:60,bit_rate:1000000,can_share:true}
const session={session_id:9,date:'2026-10-17',videos:[video],video_count:1,total_duration:1936,total_bytes:3338404955}
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('fetch',vi.fn(async (url:string)=>Response.json({url:'https://media.example.test/'+url.split('/').slice(-3)[0]+'.mov'})));vi.mocked(api.post).mockResolvedValue({data:null});vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}})
 Object.defineProperty(navigator,'mediaCapabilities',{value:{decodingInfo:async()=>({supported:true})},configurable:true})
 vi.mocked(api.get).mockImplementation(async url=>({data:url==='/api/v1/shared-sessions'?{items:[session]}:url==='/api/v1/session-videos/3'?video:url==='/api/v1/shared-sessions/9/shares'?{active_count:0}:session}))
})
afterEach(()=>{vi.unstubAllGlobals()})
const page=()=>render(<MemoryRouter initialEntries={['/sessions/shared/9']}><Routes><Route path="/sessions/shared/:sessionId" element={<SessionVideoPage/>}/></Routes></MemoryRouter>)
it('shows the single download before the poster and only opens playback on request', async () => {
 const {container}=page()
 const play=await screen.findByRole('button',{name:'Watch IMG.MOV'})
 const download=screen.getByRole('button',{name:'Download video 3.3 GB'})
 expect(download.compareDocumentPosition(play) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
 expect(container.querySelector('video')).toBeNull()
 expect(screen.getByRole('button',{name:'Share session'})).toBeInTheDocument()
 fireEvent.click(play)
 const viewer=screen.getByRole('dialog',{name:'IMG.MOV'})
 await waitFor(()=>expect(viewer.querySelector('video')).toHaveAttribute('preload','none'))
 expect(screen.queryByRole('button',{name:'Watch IMG.MOV'})).toBeNull()
 expect(within(viewer).getByRole('button',{name:'Download IMG.MOV · 3.3 GB'})).toBeInTheDocument()
 expect(within(viewer).queryByRole('button',{name:'Next recording'})).toBeNull()
 const media=viewer.querySelector('video')!
 const pause=vi.spyOn(media,'pause')
 fireEvent.keyDown(document,{key:'Escape'})
 await waitFor(()=>expect(play).toHaveFocus())
 expect(pause).toHaveBeenCalled()
 expect(media).not.toHaveAttribute('src')
})
it('owner can hide and move a video',async()=>{vi.mocked(api.patch).mockResolvedValue({data:{}});render(<MemoryRouter><SessionGallery session={session as SharedTrainingSession} reload={vi.fn()}/></MemoryRouter>);fireEvent.click(await screen.findByRole('button',{name:'Session settings'}));fireEvent.click(screen.getByRole('button',{name:'Hide'}));await waitFor(()=>expect(api.patch).toHaveBeenCalledWith('/api/v1/session-videos/3',{hidden:true}));fireEvent.change(screen.getByLabelText('Destination date'),{target:{value:'2026-10-20'}});fireEvent.click(screen.getByRole('button',{name:'Move'}));await waitFor(()=>expect(api.patch).toHaveBeenCalledWith('/api/v1/session-videos/3',{date:'2026-10-20'}))})
it('friends see no owner settings',async()=>{vi.mocked(api.get).mockResolvedValue({data:{...session,videos:[{...video,can_share:false}]}});page();await screen.findByRole('button',{name:'Watch IMG.MOV'});expect(screen.queryByRole('button',{name:'Session settings'})).toBeNull()})

it('lists each recording with its own download and a separate bulk download',async()=>{
 vi.mocked(api.get).mockImplementation(async url=>({data:url==='/api/v1/shared-sessions/9/shares'?{active_count:0}:{...session,video_count:2,videos:[video,{...video,id:4,filename:'SECOND.MOV'}]}}))
 const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this: HTMLAnchorElement) {
   expect(this.getAttribute('href')).toBe('https://media.example.test/4.mov')
   expect(this).not.toHaveAttribute('download')
 })
 page()
 const list=await screen.findByRole('list')
 expect(within(list).getAllByRole('listitem')).toHaveLength(2)
 fireEvent.click(within(list).getByRole('button',{name:'Download SECOND.MOV · 3.3 GB'}))
 await waitFor(()=>expect(click).toHaveBeenCalledTimes(1))
 expect(screen.getByRole('button',{name:/Download all/})).toBeInTheDocument()
})

it('deduplicates pagination and prevents concurrent load-more requests', async () => {
 let resolve!: (value: unknown) => void
 const pending = new Promise(r => { resolve = r })
 vi.mocked(api.get).mockImplementation(url => url === '/api/v1/shared-sessions/9' ? pending as any : Promise.resolve({data:{active_count:0}}))
 render(<MemoryRouter><SessionGallery session={{...session,video_count:2,next_video_id:3} as SharedTrainingSession}/></MemoryRouter>)
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
 const {rerender}=render(<MemoryRouter><SessionGallery session={{...session,video_count:2,next_video_id:3} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:'Load more recordings'}))
 rerender(<MemoryRouter><SessionGallery session={{...session,session_id:10,videos:[{...video,id:8,filename:'NEW.MOV'}]} as SharedTrainingSession}/></MemoryRouter>)
 resolve({data:{...session,videos:[{...video,id:4,filename:'OLD.MOV'}],next_video_id:null}})
 await waitFor(()=>expect(screen.getByRole('button',{name:'Watch NEW.MOV'})).toBeInTheDocument())
 expect(screen.queryByRole('button',{name:'Play OLD.MOV'})).toBeNull()
})

it('navigates recordings and returns keyboard focus when closing the player', async () => {
 render(<MemoryRouter><SessionGallery session={{...session,video_count:2,videos:[video,{...video,id:4,filename:'SECOND.MOV'}]} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:'Play IMG.MOV'}))
 await waitFor(()=>expect(screen.getByRole('dialog').querySelector('video')).not.toBeNull())
 expect(screen.getByRole('button',{name:'Previous recording'})).toBeDisabled()
 fireEvent.click(screen.getByRole('button',{name:'Next recording'}))
 expect(screen.getByRole('heading',{name:'SECOND.MOV'})).toHaveFocus()
 fireEvent.click(screen.getByRole('button',{name:'Close player'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'Play IMG.MOV'})).toHaveFocus())
})

it('can advance the viewer across a page boundary', async () => {
 const second={...video,id:4,filename:'SECOND.MOV'}
 vi.mocked(api.get).mockImplementation(async url=>({data:url==='/api/v1/shared-sessions/9'
   ? {...session,videos:[video,second,second],next_video_id:null}
   : {active_count:0}}))
 render(<MemoryRouter><SessionGallery session={{...session,video_count:2,next_video_id:3} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:'Play IMG.MOV'}))
 fireEvent.click(screen.getByRole('button',{name:'Next recording'}))
 expect(await screen.findByRole('dialog',{name:'SECOND.MOV'})).toBeInTheDocument()
 expect(screen.getByRole('button',{name:'Next recording'})).toBeDisabled()
 expect(api.get).toHaveBeenCalledWith('/api/v1/shared-sessions/9',{params:{after:3},signal:expect.any(AbortSignal)})
 fireEvent.click(screen.getByRole('button',{name:'Close player'}))
 expect(screen.getAllByRole('button',{name:'Play SECOND.MOV'})).toHaveLength(1)
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
 await waitFor(()=>expect(click).toHaveBeenCalledTimes(1))
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
 expect(await screen.findByRole('button',{name:'Watch IMG.MOV'})).toBeInTheDocument()
})

it('keeps the rejected download in the session and hands no error body to the browser', async () => {
 vi.mocked(fetch).mockResolvedValueOnce(new Response('{}',{status:404}))
 const click = vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{})
 page()
 fireEvent.click(await screen.findByRole('button',{name:'Download video 3.3 GB'}))
 expect(await screen.findByRole('alert')).toHaveTextContent('This file could not be downloaded')
 expect(fetch).toHaveBeenCalledWith('/api/v1/session-videos/3/download/prepare',{
   redirect:'error',credentials:'same-origin',signal:expect.any(AbortSignal),
 })
 expect(click).not.toHaveBeenCalled()
})

it('aborts batch pagination on stop and resumes without re-sending the first file', async () => {
 let pendingSignal: AbortSignal | undefined
 vi.mocked(api.get).mockImplementation((url,config)=>{
   if(url.endsWith('/shares')) return Promise.resolve({data:{active_count:0}})
   if (!pendingSignal) {
     pendingSignal = config?.signal as AbortSignal
     return new Promise(()=>{})
   }
   return Promise.resolve({data:{...session,videos:[{...video,id:4}],next_video_id:null}})
 })
 vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{})
 render(<MemoryRouter><SessionGallery session={{...session,video_count:2,next_video_id:3} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:/Download all/}))
 await waitFor(()=>expect(pendingSignal).toBeDefined())
 fireEvent.click(screen.getByRole('button',{name:'Stop downloads'}))
 expect(pendingSignal?.aborted).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'Download the remaining video'}))
 await screen.findByRole('button',{name:/Download all/})
 expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual([
   '/api/v1/session-videos/3/download/prepare',
   '/api/v1/session-videos/4/download/prepare',
 ])
})

it('offers a visible download in the player when the original cannot be read', async () => {
 Object.defineProperty(navigator,'mediaCapabilities',{value:{decodingInfo:async()=>({supported:false})},configurable:true})
 page()
 fireEvent.click(await screen.findByRole('button',{name:'Watch IMG.MOV'}))
 const viewer = screen.getByRole('dialog',{name:'IMG.MOV'})
 expect(await within(viewer).findByText('This video doesn’t play here')).toBeInTheDocument()
 expect(within(viewer).getByRole('button',{name:'Download video · 3.3 GB'})).toBeVisible()
})

it('clears a viewer pagination error when returning to a loaded recording', async () => {
 const second = {...video,id:4,filename:'SECOND.MOV'}
 vi.mocked(api.get).mockImplementation(async url=>{
   if (url.endsWith('/shares')) return { data:{active_count:0} }
   throw new Error('Offline')
 })
 render(<MemoryRouter><SessionGallery session={{...session,videos:[video,second],video_count:3,next_video_id:4} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:'Play SECOND.MOV'}))
 fireEvent.click(screen.getByRole('button',{name:'Next recording'}))
 expect(await screen.findByRole('alert')).toHaveTextContent('Could not load recordings')
 fireEvent.click(screen.getByRole('button',{name:'Previous recording'}))
 expect(screen.queryByRole('alert')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'Close player'}))
 expect(screen.queryByRole('alert')).toBeNull()
})

it('continues a batch past a failed file and marks only that file for retry', async () => {
 const items=[video,{...video,id:4,filename:'MISSING.MOV'},{...video,id:5,filename:'THIRD.MOV'}]
 vi.mocked(fetch).mockImplementation(async input=>String(input).includes('/4/')
   ? new Response('{}',{status:503}) : Response.json({url:'https://media.example.test/'+String(input).split('/').slice(-3)[0]+'.mov'}))
 const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{})
 render(<MemoryRouter><SessionGallery session={{...session,video_count:3,videos:items} as SharedTrainingSession}/></MemoryRouter>)
 fireEvent.click(screen.getByRole('button',{name:/Download all/}))
 expect(await screen.findByRole('alert',{}, {timeout:5000})).toHaveTextContent('1 file could not be downloaded')
 expect(click).toHaveBeenCalledTimes(2)
 expect(screen.getByRole('button',{ name:/Retry download of MISSING.MOV/ })).toBeInTheDocument()
 expect(screen.getByRole('button',{ name:/Download THIRD.MOV/ })).toBeInTheDocument()
})

it('reports the late failure in the gallery when the download started in the viewer', async () => {
 let fail!: (value: Response) => void
 vi.mocked(fetch).mockImplementationOnce(()=>new Promise(resolve=>{fail=resolve}))
 page()
 fireEvent.click(await screen.findByRole('button',{name:'Watch IMG.MOV'}))
 const download=screen.getByRole('button',{name:'Download IMG.MOV · 3.3 GB'})
 fireEvent.click(download)
 expect(download).toHaveAttribute('aria-busy','true')
 fireEvent.click(screen.getByRole('button',{name:'Close player'}))
 fail(new Response('{}',{status:503}))
 expect(await screen.findByRole('alert')).toHaveTextContent('This file could not be downloaded')
})
