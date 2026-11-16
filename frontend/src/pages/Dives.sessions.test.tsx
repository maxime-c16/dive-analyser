import {render,screen} from '@testing-library/react'
import {BrowserRouter} from 'react-router-dom'
import {beforeEach,it,expect,vi} from 'vitest'
import Dives from './Dives'
import {api} from '../services/api'
vi.mock('../contexts/AuthContext',()=>({useAuth:()=>({user:{user_id:5,role:'friend',divers:[],features:{shared_sessions:true}}}),isFriend:()=>true}))
vi.mock('../services/api',()=>({api:{get:vi.fn()}}))
vi.mock('../services/mediaApi',()=>({getMediaStatus:vi.fn().mockResolvedValue({poster_url:null,playback_url:null})}))
beforeEach(()=>{window.history.replaceState(null,'','/dives?scope=all');vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}})
vi.mocked(api.get).mockImplementation(async(url)=>({data:url==='/api/v1/shared-sessions'?{items:[{session_id:9,date:'2026-10-17',videos:[],video_count:2,total_duration:3600,total_bytes:10}],next_cursor:null}:url==='/api/v1/divers'?[]:[{id:1,dive_code:'103B',height:'1m',dive_datetime:'2026-10-17T10:00:00',performance:'G',performance_numeric:3,platform_type:'springboard'}]}))})
it('keeps session cards in the normal feed without a dedicated filter, including old filter URLs',async()=>{
 window.history.replaceState(null,'','/dives?scope=all&kind=sessions')
 render(<BrowserRouter><Dives/></BrowserRouter>)
 expect(await screen.findByRole('link',{name:'Training session · 2 videos'})).toBeInTheDocument()
 expect(await screen.findByRole('button',{name:/Open 103B attempt/})).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'Sessions'})).toBeNull()
})
it('renders sessions in list view too',async()=>{
 window.history.replaceState(null,'','/dives?scope=all&view=list')
 render(<BrowserRouter><Dives/></BrowserRouter>)
 const link=await screen.findByRole('link',{name:'Training session · 2 videos'})
 const attempt=await screen.findByRole('button',{name:/Open 103B attempt/})
 expect(link.compareDocumentPosition(attempt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
it('hides full recordings while a text search is active, in both views',async()=>{
 for(const view of ['','&view=list']){
  window.history.replaceState(null,'',`/dives?scope=all&q=103B${view}`)
  const page=render(<BrowserRouter><Dives/></BrowserRouter>)
  expect(await screen.findByRole('button',{name:/Open 103B attempt/})).toBeInTheDocument()
  expect(screen.queryByRole('link',{name:'Training session · 2 videos'})).toBeNull()
  page.unmount()
 }
})
it('hides full recordings when a dive-specific filter is active',async()=>{
 // A matching dive stays visible while its session card goes away.
 window.history.replaceState(null,'','/dives?scope=all&performance=G')
 render(<BrowserRouter><Dives/></BrowserRouter>)
 expect(await screen.findByRole('button',{name:/Open 103B attempt/})).toBeInTheDocument()
 expect(screen.queryByRole('link',{name:'Training session · 2 videos'})).toBeNull()
})
it('shows a consistent empty state when filters hide both sessions and dives',async()=>{
 window.history.replaceState(null,'','/dives?scope=all&height=10m')
 render(<BrowserRouter><Dives/></BrowserRouter>)
 // NB: the loader also carries role="status", so wait for the empty-state
 // copy itself (the spinner unmounts and would fail a node-identity check).
 expect(await screen.findByText('No attempts match this search.',{},{timeout:5000})).toBeInTheDocument()
 expect(screen.queryByRole('link',{name:'Training session · 2 videos'})).toBeNull()
 expect(screen.queryByRole('button',{name:/Open .* attempt/})).toBeNull()
})
it('applies the period window to sessions in both views',async()=>{
 const today=new Date().toISOString().slice(0,10)
 const old=new Date(Date.now()-400*86400000).toISOString().slice(0,10)
 vi.mocked(api.get).mockImplementation(async(url)=>({data:url==='/api/v1/shared-sessions'
  ?{items:[
   {session_id:11,date:today,videos:[],video_count:2,total_duration:3600,total_bytes:10},
   {session_id:12,date:old,videos:[],video_count:3,total_duration:3600,total_bytes:10},
  ],next_cursor:null}
  :url==='/api/v1/divers'?[]:[{id:1,dive_code:'103B',height:'1m',dive_datetime:`${today}T10:00:00`,performance:'G',performance_numeric:3,platform_type:'springboard'}]}))
 for(const view of ['','&view=list']){
  window.history.replaceState(null,'',`/dives?scope=all&period=30d${view}`)
  const page=render(<BrowserRouter><Dives/></BrowserRouter>)
  expect(await screen.findByRole('link',{name:'Training session · 2 videos'})).toBeInTheDocument()
  expect(screen.queryByRole('link',{name:'Training session · 3 videos'})).toBeNull()
  page.unmount()
 }
})
