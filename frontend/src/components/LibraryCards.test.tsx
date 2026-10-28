import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LibraryCardGrid } from './LibraryCards'
import type { Attempt } from '../utils/attemptPresentation'

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} })
})
afterEach(() => { vi.unstubAllGlobals() })

const attempt = (patch: Partial<Attempt>): Attempt => ({
  id: 1, dive_code: '5122D', performance: 'G', performance_numeric: 4, height: '1m',
  dive_datetime: '2026-10-18T17:23:00', session_id: 1, is_lineup: false, is_sync: false,
  platform_type: 'springboard', official_dd: 1.9, raw_caption: '5122D G', ...patch,
})

it('groups attempts by day and shows the full name, score and DD without rating pills', async () => {
  const onOpen = vi.fn()
  const attempts = [
    attempt({ id: 1 }),
    attempt({ id: 2, dive_code: '201C', raw_caption: '201C P DB', performance: 'P', official_dd: 1.5 }),
    attempt({ id: 3, dive_datetime: '2026-10-17T11:05:00', official_dd: null, is_sync: true }),
  ]
  render(<LibraryCardGrid attempts={attempts} onOpen={onOpen} />)

  const days = screen.getAllByRole('region')
  expect(days).toHaveLength(2)
  expect(within(days[0]).getAllByRole('button')).toHaveLength(2)
  expect(within(days[0]).getByText('2')).toBeInTheDocument()

  const first = within(days[0]).getAllByRole('button')[0]
  expect(first).toHaveTextContent('5122D')
  expect(first).toHaveTextContent('7.0')
  expect(first).toHaveTextContent("Forward somersault 1 twist free")
  expect(first).toHaveTextContent('1m · DD 1.9')
  expect(first).not.toHaveTextContent(/springboard|Good|\/ 10/)

  expect(within(days[0]).getAllByRole('button')[1]).toHaveTextContent('1m · DB · DD 1.5')
  expect(within(days[1]).getByRole('button')).toHaveTextContent('1m · SYNC')

  await userEvent.click(first)
  expect(onOpen).toHaveBeenCalledWith(attempts[0])
})

it('names the diver on community cards', () => {
  render(<LibraryCardGrid attempts={[attempt({ person_name: 'Alex' })]} onOpen={vi.fn()} showDiver />)
  expect(screen.getByRole('button', { name: /Open 5122D attempt .* · Alex/ })).toHaveTextContent('Alex')
})

it('mixes session cards into the same day as dive cards', async () => {
  const {MemoryRouter}=await import('react-router-dom')
  render(<MemoryRouter><LibraryCardGrid attempts={[attempt({})]} onOpen={vi.fn()} sessions={[{session_id:8,date:'2026-10-18',videos:[],video_count:3,total_duration:3600,total_bytes:100,has_more:false}]}/></MemoryRouter>)
  expect(screen.getAllByRole('region')).toHaveLength(1)
  expect(screen.getByRole('link',{name:'Séance · 3 vidéos'})).toHaveAttribute('href','/sessions/shared/8')
  expect(screen.getByText('1 h 00')).toBeInTheDocument()
})

it('counts a session-only day and uses singular video wording', async () => {
  const {MemoryRouter}=await import('react-router-dom')
  render(<MemoryRouter><LibraryCardGrid attempts={[]} onOpen={vi.fn()} sessions={[{session_id:9,date:'2026-10-17',videos:[],video_count:1,total_duration:600,total_bytes:10,has_more:false}]}/></MemoryRouter>)
  expect(screen.getByRole('link',{name:'Séance · 1 vidéo'})).toHaveTextContent('1 vidéo')
  expect(within(screen.getByRole('region')).getByText('1',{exact:true})).toBeInTheDocument()
  expect(screen.queryByText('0',{exact:true})).toBeNull()
})
