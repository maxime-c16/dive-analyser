import {render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {BrowserRouter} from 'react-router-dom'
import {beforeEach,it,expect,vi} from 'vitest'
import Dives from './Dives'
import {api} from '../services/api'
vi.mock('../contexts/AuthContext',()=>({useAuth:()=>({user:{user_id:5,role:'friend',divers:[],features:{shared_sessions:true}}}),isFriend:()=>true}))
vi.mock('../services/api',()=>({api:{get:vi.fn()}}))
vi.mock('../services/mediaApi',()=>({getMediaStatus:vi.fn().mockResolvedValue({poster_url:null,playback_url:null})}))
beforeEach(()=>{window.history.replaceState(null,'','/dives?scope=all');vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}})
vi.mocked(api.get).mockImplementation(async(url)=>({data:url==='/api/v1/shared-sessions'?{items:[{session_id:9,date:'2026-10-17',videos:[],video_count:2,total_duration:3600,total_bytes:10}],next_cursor:null}:url==='/api/v1/divers'?[]:[{id:1,dive_code:'103B',height:'1m',dive_datetime:'2026-10-17T10:00:00',performance:'G',performance_numeric:3,platform_type:'springboard'}]}))})
it('friends see session cards mixed with dives and can filter sessions through URL state',async()=>{render(<BrowserRouter><Dives/></BrowserRouter>);await screen.findByRole('link',{name:'Séance · 2 vidéos'});await screen.findByRole('button',{name:/Open 103B attempt/});await userEvent.click(screen.getByRole('button',{name:'Séances'}));expect(window.location.search).toContain('kind=sessions');expect(screen.getByRole('button',{name:'Séances'})).toHaveAttribute('aria-pressed','true');await waitFor(()=>expect(screen.queryByRole('button',{name:/Open 103B attempt/})).toBeNull());expect(screen.getByRole('link',{name:'Séance · 2 vidéos'})).toBeInTheDocument()})
