import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {beforeEach,expect,it,vi} from 'vitest'
import SignupReviews from './SignupReviews'
import {api} from '../../services/api'
vi.mock('../../services/api',()=>({api:{get:vi.fn(),post:vi.fn()}}))
const first={id:1,user_id:7,name:'Mat',email:'mat@example.test',candidate_name:'MAT'}
const second={id:2,user_id:8,name:'Lea',email:'lea@example.test',candidate_name:'LEA'}
beforeEach(()=>{vi.clearAllMocks()
  vi.mocked(api.get).mockImplementation((async (url:string,config?:{params?:Record<string,unknown>})=>{
    if(!config?.params?.after)return {data:{items:[first],next_after:1}}
    return {data:{items:[second],next_after:null}}}) as typeof api.get)
})
it('shows one bounded page with continuation instead of the whole queue',async()=>{
  render(<MemoryRouter><SignupReviews/></MemoryRouter>)
  expect(await screen.findByText('Mat · mat@example.test')).toBeInTheDocument()
  expect(screen.queryByText('Lea · lea@example.test')).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'Afficher plus'}))
  expect(await screen.findByText('Lea · lea@example.test')).toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'Afficher plus'})).toBeNull()
})
it('validates a review from the page',async()=>{
  vi.mocked(api.post).mockResolvedValue({data:{ok:true}})
  render(<MemoryRouter><SignupReviews/></MemoryRouter>)
  expect(await screen.findByText('Mat · mat@example.test')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'Valider'}))
  await waitFor(()=>expect(screen.queryByText('Mat · mat@example.test')).toBeNull())
  expect(api.post).toHaveBeenCalledWith('/api/v1/session-signup-reviews/1/accept')
})
