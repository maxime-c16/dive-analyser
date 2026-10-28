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
 expect(await screen.findByRole('link',{name:'Séance · 2 vidéos'})).toBeInTheDocument()
 expect(await screen.findByRole('button',{name:/Open 103B attempt/})).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'Séances'})).toBeNull()
})
it('renders sessions in list view too',async()=>{
 window.history.replaceState(null,'','/dives?scope=all&view=list')
 render(<BrowserRouter><Dives/></BrowserRouter>)
 const link=await screen.findByRole('link',{name:'Séance · 2 vidéos'})
 const attempt=await screen.findByRole('button',{name:/Open 103B attempt/})
 expect(link.compareDocumentPosition(attempt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
