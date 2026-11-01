/**
 * Library UX regression tests for the discovery-report fixes (scope A):
 * - cross-rubrique workspacememory respecting explicit URLs and identities;
 * - figure-name search across the whole authorized scope (client mirrors API);
 * - period filter (`period` URL param → `date_from`);
 * - sequential pagination (one control at a time, truthful remaining count);
 * - code-card "Open latest attempt" resolves an attempt beyond the loaded page.
 */
import React from 'react'
import { BrowserRouter } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import Dives from './Dives'
import { nameSearchCodes } from '../utils/diveNameSearch'

let mockUser: Record<string, unknown> | null = {
  user_id: 1, role: 'owner', is_admin: true, divers: [{ diver_id: 1, access_kind: 'OWNER' }],
}
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}))
vi.mock('../services/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../services/mediaApi', () => ({ getMediaStatus: vi.fn().mockResolvedValue({ poster_url: null, playback_url: null }) }))
vi.mock('../components/DiveVideoPlayer', () => ({ default: ({ videoUuid }: { videoUuid: string }) => <div>Native player {videoUuid}</div> }))

import { api } from '../services/api'
import { getMediaStatus } from '../services/mediaApi'

type LibraryCall = [string, { params?: Record<string, string> }]

const dive = (id: number, code: string, diverId: number, options: Partial<Record<string, unknown>> = {}) => ({
  id, dive_code: code, diver_id: diverId, performance: 'G', performance_numeric: 3, height: '1m',
  dive_datetime: `2026-07-${String(id % 28 + 1).padStart(2, '0')}T10:00:00`, session_id: 1,
  is_lineup: false, is_sync: false, platform_type: 'springboard', position: code.slice(-1),
  official_dd: 1.5, phase1_performance: 'G', phase2_performance: 'G', raw_caption: null, video_uuid: `uuid-${id}`, ...options,
})

const divers = [{ id: 1, display_name: 'Maxime', is_primary_user: true }]

const codeSummary = (code: string, latestId: number, ids: number[]) => ({
  dive_code: code, analytics: true, attempt_count: 99, scored_count: 99, session_count: 1,
  average: 7, median: 7, best: 7, success_rate: 100,
  first_attempt_at: '2026-07-01T10:00:00', last_attempt_at: '2026-07-05T10:00:00',
  heights: ['1m'], ratings: { G: 99 }, trend: null, spark: [7, 7], months: {},
  latest: { id: latestId, dive_code: code, dive_datetime: '2026-07-05T10:00:00', video_uuid: `uuid-${latestId}` },
  recent: ids.map(id => ({ id, performance: 'G', score: 7, dive_datetime: `2026-07-0${id}T10:00:00`, height: '1m' })),
})

function renderAt(url: string) {
  window.history.replaceState(null, '', url)
  return render(<BrowserRouter><Dives /></BrowserRouter>)
}

beforeEach(() => {
  mockUser = { user_id: 1, role: 'owner', is_admin: true, divers: [{ diver_id: 1, access_kind: 'OWNER' }] }
  sessionStorage.clear()
  vi.mocked(getMediaStatus).mockResolvedValue({ poster_url: null, playback_url: null } as any)
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    return Promise.resolve({ data: { items: [dive(1, '103B', 1), dive(2, '201C', 1), dive(3, '103B', 1, { raw_caption: 'back dive practice' })], next_cursor: null } })
  })
})

// ---- Figure-name search: catalog-derived candidates ----

it('derives exact candidate codes from figure words in both languages', () => {
  const backDive = nameSearchCodes('BACK DIVE')
  expect(backDive.status).toBe('match')
  expect([...backDive.codes].sort()).toEqual(['201A', '201B', '201C', '201D'])

  // French wording resolves without accents and matches the same families.
  const arriere = nameSearchCodes('arrière')
  expect(arriere.status).toBe('match')
  expect(arriere.codes).toContain('203C')
  expect(arriere.codes).toContain('201A')
  expect(arriere.codes).not.toContain('303C')

  expect(nameSearchCodes('BACK DIVE TUCK').codes).toEqual(['201C'])
  expect(nameSearchCodes('smack')).toEqual({ status: 'unused', codes: [] })
  // A rotation-family word alone is too broad for a bounded code list.
  expect(nameSearchCodes('somersaults')).toEqual({ status: 'unsupported', codes: [] })
})

it('sends the derived codes to the API and keeps caption matches alongside them', async () => {
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  const search = screen.getByRole('textbox', { name: 'Search dives' })
  await userEvent.type(search, 'back dive')
  const libraryCalls = vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/dives/library')
  await waitFor(() => {
    expect(libraryCalls.some(([, config]) => (config as { params: Record<string, string> }).params?.code_filter === '201A,201B,201C,201D')).toBe(true)
  })
  // The client filter mirrors the API's OR-composition: caption-less named
  // dives AND caption-phrase matches both stay visible.
  await waitFor(() => {
    const codes = screen.queryAllByText('201C').length > 0 && screen.getAllByText(/back dive practice/).length > 0
    expect(codes).toBe(true)
  })
})

it('falls back to phrase search when no figure word is present', async () => {
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  await userEvent.type(screen.getByRole('textbox', { name: 'Search dives' }), 'smack')
  await waitFor(() => {
    const last = vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/dives/library').at(-1) as unknown as [string, { params: Record<string, string> }]
    expect(last[1].params?.search_text).toBe('SMACK')
    expect(last[1].params?.code_filter).toBeUndefined()
  })
})

// ---- Period filter ----

it('turns the period preset into a bounded date_from', async () => {
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Period' }), 'Past 3 months')
  await waitFor(() => expect(window.location.search).toBe('?period=90d'))
  const calls = vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/dives/library') as unknown as LibraryCall[]
  expect(calls.at(-1)![1].params?.date_from).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00$/)
  await userEvent.click(screen.getByRole('button', { name: /Reset filters/ }))
  expect(window.location.search).not.toContain('period')
})

// ---- Cross-rubrique workspace memory ----

it('restores filters, view and period when returning to a bare Library URL', async () => {
  const view = renderAt('/dives?scope=all&q=smack&view=list&period=30d')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  view.unmount()

  renderAt('/dives')
  expect(await screen.findByRole('textbox', { name: 'Search dives' })).toHaveValue('smack')
  expect(screen.getByRole('button', { name: 'List view' })).toHaveAttribute('aria-pressed', 'true')
  expect(window.location.search).toBe('?scope=all&q=smack&view=list&period=30d')
  const calls = vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/dives/library') as unknown as LibraryCall[]
  expect(calls[0][1].params?.search_text).toBe('SMACK')
  expect(calls[0][1].params?.date_from).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00$/)
})

it('never restores over an explicit Library URL', async () => {
  const view = renderAt('/dives?scope=all&q=smack&view=list')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  view.unmount()

  renderAt('/dives?scope=all')
  expect(await screen.findByRole('textbox', { name: 'Search dives' })).toHaveValue('')
  expect(await screen.findAllByRole('button', { name: /Open .* attempt/ })).toHaveLength(3)
  expect(window.location.search).toBe('?scope=all')
})

it('keeps the remembered workspace private to each account', async () => {
  const view = renderAt('/dives?scope=all&q=smack&view=list')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  view.unmount()

  const otherAccount = { user_id: 9, role: 'owner', is_admin: false, divers: [{ diver_id: 7, access_kind: 'OWNER' }] }
  mockUser = otherAccount
  renderAt('/dives')
  expect(await screen.findByRole('textbox', { name: 'Search dives' })).toHaveValue('')
  expect(screen.getByRole('button', { name: 'List view' })).toHaveAttribute('aria-pressed', 'false')
  expect(window.location.search).toBe('')
})

it('restores scroll depth clamped to the page content', async () => {
  const originalHeight = Object.getOwnPropertyDescriptor(document.documentElement, 'scrollHeight')
  Object.defineProperty(document.documentElement, 'scrollHeight', { configurable: true, value: 4000 })
  const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})

  const save = (params: string, scrollY: number) => {
    const key = `dive-library-view:v1:${JSON.stringify([mockUser!.user_id, mockUser!.role, mockUser!.is_admin, ['1:OWNER']])}`
    sessionStorage.setItem(key, JSON.stringify({ p: params, y: scrollY }))
  }
  save('scope=all', 6000)
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  await waitFor(() => expect(scrollSpy).toHaveBeenCalled())
  expect(scrollSpy.mock.calls[0][1]).toBe(4000 - (Number.isFinite(window.innerHeight) ? window.innerHeight : 0) || 0)
  scrollSpy.mockRestore()
  if (originalHeight) Object.defineProperty(document.documentElement, 'scrollHeight', originalHeight!)
})

// ---- Sequential pagination ----

it('never stacks the two pagination controls and reports truthful remaining counts', async () => {
  const page = (from: number) => Array.from({ length: 60 }, (_, i) => dive(from + i, '103B', 1))
  vi.mocked(api.get).mockImplementation((url: string, config?: { params?: { cursor?: string } }) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    return Promise.resolve({ data: config?.params?.cursor
      ? { items: page(61), next_cursor: null }
      : { items: page(1), next_cursor: 'next-page' } })
  })
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open 103B attempt/ })

  // 60 loaded, 48 shown: only the client-side expander shows, with the
  // truthful count of 12, and the server fetch is dormant.
  const showMore = () => screen.queryByRole('button', { name: /more attempts/ })
  const loadMore = () => screen.queryByRole('button', { name: 'Load more dives' })
  expect(showMore()).toHaveTextContent('12')
  expect(loadMore()).toBeNull()

  await userEvent.click(showMore()!)
  expect(await screen.findAllByRole('button', { name: /Open 103B attempt/ })).toHaveLength(60)
  expect(showMore()).toBeNull()
  expect(loadMore()).not.toBeNull()

  // The server page takes over; its arrival reveals the rest in one step.
  await userEvent.click(loadMore()!)
  expect(await screen.findAllByRole('button', { name: /Open 103B attempt/ })).toHaveLength(120)
  expect(showMore()).toBeNull()
  expect(loadMore()).toBeNull()
}, 20000)

// ---- Open latest attempt beyond the loaded page ----

it('opens the latest attempt of a code even when it is not on the loaded pages', async () => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    if (url === '/api/v1/dives/library/codes') {
      return Promise.resolve({ data: {
        generated_at: '2026-07-10T10:00:00',
        codes: [codeSummary('103C', 99, [1, 2]), codeSummary('101A', 3, [3])],
        activity: { current: { attempt_count: 3, session_count: 1, code_count: 2, median: 7 }, previous: { attempt_count: 0, session_count: 0, code_count: 0, median: null }, months: [], weeks: [] },
      } })
    }
    if (url === '/api/v1/dives/99') return Promise.resolve({ data: dive(99, '103C', 1) })
    return Promise.resolve({ data: { items: [dive(1, '103B', 1), dive(2, '103B', 1)], next_cursor: null } })
  })
  renderAt('/dives?view=codes&scope=all')
  expect(await screen.findByRole('button', { name: /Open latest 103C attempt/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Open latest 103C attempt/ }))
  expect(await screen.findByText('Native player uuid-99')).toBeInTheDocument()
})
