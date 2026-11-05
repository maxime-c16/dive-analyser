import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import JudgeRoom from './JudgeRoom'
import { roomRequest, type Room } from '../services/judgeRoomApi'
import '../i18n'
vi.mock('../contexts/AuthContext', () => ({useAuth:()=>({user:{user_id:1,display_name:'maxime'}})}))
vi.mock('../components/judge-room/useRoomPreload', () => ({default:()=>({})}))
vi.mock('../services/judgeRoomApi', () => ({roomRequest:vi.fn()}))
let message: ((event: {data:string})=>void) | undefined
class Socket {
  static OPEN=1; readyState=1; onclose=null; send=vi.fn(); close=vi.fn()
  set onmessage(callback: typeof message) { message=callback }
}
const base: Room={code:'TEST',host:'me',me:'me',phase:'results',mode:'classic',source:'code',players:[{id:'me',name:'maxime',points:0}],playlist:[],index:0,game_id:'g1',ready:[],scoring_starts:0,starts:0,closes:Date.now()/1000+20,server_time:Date.now()/1000,voted:[],my_answer:null,has_ballot:false,skipped:[],my_score:null,is_mole:false,mole:null,result:null}
function mount(room: Room) {
  vi.mocked(roomRequest).mockResolvedValue(room)
  return render(<MemoryRouter initialEntries={['/room/TEST']}><Routes><Route path='/room/:code' element={<JudgeRoom/>}/></Routes></MemoryRouter>)
}
beforeEach(()=>{vi.clearAllMocks();message=undefined;vi.stubGlobal('WebSocket',Socket)})
afterEach(()=>{vi.unstubAllGlobals()})
it('keeps the ranking but does not award score-based titles to an unscored player',async()=>{
  mount({...base})
  await screen.findByText('Game over')
  expect(screen.getByText('maxime')).toBeInTheDocument()
  expect(screen.queryByText('Eagle eye')).not.toBeInTheDocument()
  expect(screen.queryByText('The harshest')).not.toBeInTheDocument()
})
it('requires a deliberate mole choice, shows a deadline and confirms the persisted ballot',async()=>{
  mount({...base,phase:'mole'})
  const vote=await screen.findByRole('button',{name:'Vote'})
  expect(vote).toBeDisabled()
  expect(screen.getByText(/\d+s$/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'Nobody'}))
  expect(vote).toBeEnabled()
  vi.mocked(roomRequest).mockResolvedValueOnce({...base,phase:'mole',has_ballot:true,server_time:base.server_time+1})
  fireEvent.click(vote)
  expect(await screen.findByRole('button',{name:'Vote submitted'})).toBeDisabled()
  await act(async()=>message?.({data:JSON.stringify({...base,mode:'mole',has_ballot:true,server_time:base.server_time+2})}))
  expect(await screen.findByText('Correct vote')).toBeInTheDocument()
})
it('ignores an older socket snapshot arriving after the ballot response',async()=>{
  mount({...base,phase:'mole',has_ballot:true})
  await screen.findByRole('button',{name:'Vote submitted'})
  await waitFor(()=>expect(message).toBeDefined())
  await act(async()=>message?.({data:JSON.stringify({...base,phase:'mole',has_ballot:false,server_time:base.server_time-1})}))
  expect(screen.getByRole('button',{name:'Vote submitted'})).toBeDisabled()
})

it('keeps both room slots muted when Start primes playback after a deliberate mute', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function(this:HTMLMediaElement) {
    expect(this.muted).toBe(true)
    return Promise.resolve()
  })
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(()=>{})
  const {container}=mount({...base,phase:'lobby',playlist:[{id:1,dive_code:'112B',height:'1m',poster_url:'',playback_url:'/room-media'}] as Room['playlist']})
  try {
    const mute = await screen.findByRole('button',{name:'Mute sound'})
    expect([...container.querySelectorAll('video')].every(v=>!v.muted)).toBe(true)
    fireEvent.click(mute)
    expect(screen.getByRole('button',{name:'Turn sound on'})).toBeInTheDocument()
    expect([...container.querySelectorAll('video')].every(v=>v.muted)).toBe(true)
    fireEvent.click(screen.getByRole('button',{name:'Start'}))
    await waitFor(()=>expect(play).toHaveBeenCalledTimes(2))
    expect([...container.querySelectorAll('video')].every(v=>v.muted)).toBe(true)
  } finally { play.mockRestore();pause.mockRestore() }
})
