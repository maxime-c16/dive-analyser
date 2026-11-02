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
import { clearLibraryCache } from '../services/libraryCache'

// Cold lazy-route imports transformed by Vitest can take well over 5s on the
// shared 2-CPU server while the gate runs next to production: every test
// that opens a lazy route below waits with this shared budget instead of the
// 1s default.
const LAZY_ROUTE_WAIT = 20_000

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
  dive_datetime: options.dive_datetime as string ?? new Date(Date.UTC(2026, 6, 1, 10, 0, 0, 0) - id * 61_000).toISOString(),
  session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', position: code.slice(-1),
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

/** Seeds the per-account workspace memory directly (same key as the hook). */
const saveWorkspace = (params: string, scrollY: number, resume?: { anchor: number | null; pages: number }) => {
  const key = `dive-library-view:v1:${JSON.stringify([mockUser!.user_id, mockUser!.role, mockUser!.is_admin, ['1:OWNER']])}`
  sessionStorage.setItem(key, JSON.stringify({ p: params, y: scrollY, ...(resume ? { d: resume } : {}) }))
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
  expect(backDive.codes.length).toBeLessThanOrEqual(1024)
  expect(backDive.codes).toContain('201C')
  expect(backDive.codes).not.toContain('303C')

  // French wording resolves without accents and matches the same families.
  const arriere = nameSearchCodes('arrière')
  expect(arriere.status).toBe('match')
  expect(arriere.codes).toContain('203C')
  expect(arriere.codes).not.toContain('303C')

  // Longer figure wording narrows further (position C only).
  const backDiveTuck = nameSearchCodes('BACK DIVE TUCK')
  expect(backDiveTuck.codes).toContain('201C')
  expect(backDiveTuck.codes).not.toContain('201B')

  expect(nameSearchCodes('smack')).toEqual({ status: 'unused', codes: [] })
  // A rotation-family word alone is too broad for a bounded code list.
  expect(nameSearchCodes('somersaults')).toEqual({ status: 'unsupported', codes: [] })
})

it('sends the derived codes to the API and keeps caption matches alongside them', async () => {
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  const search = screen.getByRole('textbox', { name: 'Search dives' })
  // Deferred rendering (useDeferredValue) lands late on busy runners; the
  // call itself is what is being asserted, so keep a generous window.
  await userEvent.type(search, 'back dive')
  // Read the live call list INSIDE the poll: a snapshot taken before the
  // wait cannot see the calls the deferred render (`useDeferredValue`)
  // fires still later — that stale-array form is what timed out in CI.
  // The causal assertion (the API receives the derived behaviour codes)
  // stays unchanged; 3 s of real-time polling only re-reads fresh calls.
  await waitFor(() => {
    const libraryCalls = vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/dives/library')
    expect(libraryCalls.some(([, config]) => (config as { params: Record<string, string> }).params?.code_filter !== undefined)).toBe(true)
  }, { timeout: 3000 })
  // The client filter mirrors the API's OR-composition: the caption-less
  // named dive stays visible too; the plain caption-less 103B drops out.
  await waitFor(() => expect(screen.queryByRole('button', { name: /Open 201C attempt/ })).not.toBeNull())
  expect(screen.queryAllByRole('button', { name: /Open 103B attempt/ })).toHaveLength(1)
})

it('falls back to phrase search when no figure word is present', async () => {
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  await userEvent.type(screen.getByRole('textbox', { name: 'Search dives' }), 'smack')
  await waitFor(() => {
    const nextCalls = vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/dives/library')
    const last = nextCalls[nextCalls.length - 1] as unknown as [string, { params: Record<string, string> }]
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
  expect(calls[calls.length - 1][1].params?.date_from).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00$/)
  await userEvent.click(screen.getByRole('button', { name: /Reset filters/ }))
  expect(window.location.search).not.toContain('period')
})

// ---- Cross-rubrique workspace memory ----

// ---- Cross-rubrique workspace memory ----

it('restores filters, view and period when returning to a bare Library URL', async () => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    // The period is honored by the API in production (date_from) and screened
    // again by the client; give the fixture rows that stay inside it.
    return Promise.resolve({ data: {
      items: [
        dive(1, '103B', 1, { dive_datetime: new Date(Date.now() - 86_400_000).toISOString() }),
        dive(3, '103B', 1, { dive_datetime: new Date(Date.now() - 86_400_000).toISOString(), raw_caption: 'practice notes' }),
      ],
      next_cursor: null,
    } })
  })
  const view = renderAt('/dives?scope=all&q=103B&view=list&period=30d')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  view.unmount()

  renderAt('/dives')
  expect(await screen.findByRole('textbox', { name: 'Search dives' })).toHaveValue('103B')
  expect(screen.getByRole('button', { name: 'List view' })).toHaveAttribute('aria-pressed', 'true')
  const restored = new URLSearchParams(window.location.search)
  expect(restored.get('q')).toBe('103B')
  expect(restored.get('scope')).toBe('all')
  expect(restored.get('view')).toBe('list')
  expect(restored.get('period')).toBe('30d')
  const calls = vi.mocked(api.get).mock.calls.filter(([url]) => url === '/api/v1/dives/library') as unknown as LibraryCall[]
  expect(calls[0][1].params?.code_prefix).toBe('103B')
  expect(calls[0][1].params?.date_from).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00$/)
})

it('never restores over an explicit Library URL or a clip deep link', async () => {
  const view = renderAt('/dives?scope=all&q=103B&view=list')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  view.unmount()

  renderAt('/dives?scope=all')
  expect(await screen.findByRole('textbox', { name: 'Search dives' })).toHaveValue('')
  expect(await screen.findAllByRole('button', { name: /Open .* attempt/ })).toHaveLength(3)
  expect(window.location.search).toBe('?scope=all')

  const clipEntry = renderAt('/dives?clip=2')
  // The clip stage lazy-loads (see LAZY_ROUTE_WAIT): under CI load its
  // settle can outlive the default 1 s wait — wait for the dialog with the
  // same shared budget.
  expect(await screen.findByRole('dialog', {}, { timeout: LAZY_ROUTE_WAIT })).toBeInTheDocument()
  expect((clipEntry.container.querySelector('input[data-dives-search]') as HTMLInputElement).value).toBe('')
  clipEntry.unmount()
})

it('keeps the remembered workspace private to each account', async () => {
  const view = renderAt('/dives?scope=all&q=103B&view=list')
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

  saveWorkspace('scope=all', 6000)
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  await waitFor(() => expect(scrollSpy).toHaveBeenCalled())
  expect(scrollSpy.mock.calls[0][1]).toBe(4000 - (Number.isFinite(window.innerHeight) ? window.innerHeight : 0) || 0)
  scrollSpy.mockRestore()
  if (originalHeight) Object.defineProperty(document.documentElement, 'scrollHeight', originalHeight!)
})

it('consumes the restored scroll anchor only on the restored page’s own rows', async () => {
  const originalHeight = Object.getOwnPropertyDescriptor(document.documentElement, 'scrollHeight')
  Object.defineProperty(document.documentElement, 'scrollHeight', { configurable: true, value: 4000 })
  const events: string[] = []
  vi.mocked(api.get).mockImplementation((url: string, config?: { params?: Record<string, string> }) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    events.push('library')
    return Promise.resolve({ data: { items: [dive(1, '103B', 1), dive(2, '201C', 1)], next_cursor: null } })
  })
  const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => { events.push('scroll') })

  saveWorkspace('scope=all', 6000)
  renderAt('/dives')
  // The restored page (scope=all) must exist BEFORE the anchor is consumed:
  // scrolling it against the stale bare-key cache (or nothing) would break
  // the restoration entirely.
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  await waitFor(() => expect(events).toContain('scroll'))
  const firstScroll = events.indexOf('scroll')
  expect(events.indexOf('library')).toBeGreaterThanOrEqual(0)
  expect(firstScroll).toBeGreaterThan(events.indexOf('library'))
  expect(scrollSpy.mock.calls[0][1]).toBeLessThan(6000)
  scrollSpy.mockRestore()
  if (originalHeight) Object.defineProperty(document.documentElement, 'scrollHeight', originalHeight!)
})

it('reaches for the Library again after a presentation-only workspace restore', async () => {
  clearLibraryCache()
  saveWorkspace('view=list', 0)
  // No matching cache: a view/sort-only restore leaves the query keys
  // unchanged, so the load effect had stopped watching for the restored
  // URL — the page must still end up loaded, not spinning forever.
  renderAt('/dives')
  expect(await screen.findAllByRole('button', { name: /Open .* attempt/ }, { timeout: 5000 })).toHaveLength(3)
  expect(new URLSearchParams(window.location.search).get('view')).toBe('list')
  expect(screen.getByRole('button', { name: 'List view' })).toHaveAttribute('aria-pressed', 'true')
})

it('screens out-of-period rows from the list while the period page loads', async () => {
  renderAt('/dives')
  await screen.findAllByRole('button', { name: /Open .* attempt/ })
  // Selecting a period re-queries the API without a matching cache snapshot:
  // the old-period rows stay mounted (deliberate keep-mounted refresh), but
  // they must stop being visible — the client filter mirrors date_from.
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Period' }), 'Past 3 months')
  await waitFor(() => expect(window.location.search).toBe('?period=90d'))
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: /Open .* attempt/ })).not.toBeInTheDocument(),
  )
  expect(screen.queryByText(/Something went wrong|could not/)).toBeNull()
})

it('keeps a period deep link from opening an attempt the period excludes', async () => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    if (url === '/api/v1/dives/3') return Promise.resolve({ data: dive(3, '103B', 1) })
    return Promise.resolve({ data: { items: [], next_cursor: null } })
  })
  // dive(3) carries a July date, outside the 90-day window: the direct-link
  // resolver may resolve it, but the period-bound list must never show —
  // much less open — it.
  renderAt('/dives?period=90d&clip=3')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(window.location.search).toBe('?period=90d'))
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

it('advances the manual Load-more cursor past the resumed depth', async () => {
  // Page cursors advance p2 → p3 → p4 during the saved-depth resume; a
  // later manual "Load more dives" must continue from the resume's deepest
  // cursor (p4) — re-hosting p2 would count and fetch rows already shown.
  vi.mocked(api.get).mockImplementation((url: string, config?: { params?: { cursor?: string } }) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    const cursor = config?.params?.cursor ?? null
    const page = (base: number, next: string | null) => ({
      data: { items: [dive(base, `${base}B`, 1), dive(base + 1, `${base + 1}B`, 1)], next_cursor: next },
    })
    if (!cursor) return Promise.resolve(page(1, 'p2'))
    if (cursor === 'p2') return Promise.resolve(page(101, 'p3'))
    if (cursor === 'p3') return Promise.resolve(page(201, 'p4'))
    return Promise.resolve(page(301, null))
  })
  const key = `dive-library-view:v1:${JSON.stringify([mockUser!.user_id, mockUser!.role, mockUser!.is_admin, ['1:OWNER']])}`
  sessionStorage.setItem(key, JSON.stringify({ p: 'scope=all', y: 0, d: { anchor: null, pages: 3 } }))
  renderAt('/dives')
  // The resume hosts pages 2 and 3 on top of page 1 (6 rows total).
  expect(await screen.findByRole('button', { name: /Open 202B attempt/ })).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: /Open .* attempt/ })).toHaveLength(6)
  // The manual control now anchors on p4: one click, one new page, no p2 redo.
  const loadMore = screen.getByRole('button', { name: 'Load more dives' })
  await userEvent.click(loadMore)
  expect(await screen.findByRole('button', { name: /Open 302B attempt/ })).toBeInTheDocument()
  const requests = (vi.mocked(api.get).mock.calls as unknown as Array<[string, { params?: { cursor?: string } }]>)
    .map(call => call[1]?.params?.cursor ?? null)
  expect(requests.filter(cursor => cursor === 'p2')).toHaveLength(1)
  expect(requests.filter(cursor => cursor === 'p3')).toHaveLength(1)
  expect(requests.filter(cursor => cursor === 'p4')).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: /Open .* attempt/ })).toHaveLength(8)
})

it('holds the scroll anchor until the resumed depth finished walking', async () => {
  // Regression (verdict finding, repeated): on a COLD restore, page 1 loads
  // (loading=false) WHILE the resume walk is still ahead — the old code
  // consumed and clamped the saved anchor against partial content, losing
  // the full-depth position. This test fails on the old code: between page
  // 1 (and page 2 while the walk proceeds) the anchor must stay unconsumed.
  const originalHeight = Object.getOwnPropertyDescriptor(document.documentElement, 'scrollHeight')
  Object.defineProperty(document.documentElement, 'scrollHeight', { configurable: true, value: 6000 })
  const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  clearLibraryCache()
  const gates: Record<string, (value: unknown) => void> = {}
  vi.mocked(api.get).mockImplementation((url: string, config?: { params?: { cursor?: string } }) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    const cursor = config?.params?.cursor ?? null
    const page = (base: number, next: string | null) => ({
      data: { items: [dive(base, `${base}B`, 1), dive(base + 1, `${base + 1}B`, 1)], next_cursor: next },
    })
    if (!cursor) return Promise.resolve(page(1, 'p2'))
    if (cursor === 'p2') return new Promise(resolve => { gates.p2 = resolve })
    if (cursor === 'p3') return new Promise(resolve => { gates.p3 = resolve })
    return Promise.resolve(page(301, null))
  })
  saveWorkspace('scope=all', 5000, { anchor: null, pages: 3 })
  renderAt('/dives')
  // Page 1 rows paint while the resume walk is STILL PENDING: the anchor is
  // not consumed yet (old code failed HERE with a clamped scrollTo).
  await screen.findByRole('button', { name: /Open 2B attempt/ })
  await waitFor(() => expect(gates.p2).toBeDefined())
  expect(scrollSpy).not.toHaveBeenCalled()
  // The walk progresses page 2 (p2 →): still nothing consumed.
  gates.p2!({ data: { items: [dive(101, '101B', 1), dive(102, '102B', 1)], next_cursor: 'p3' } })
  await screen.findByRole('button', { name: /Open 102B attempt/ })
  await waitFor(() => expect(gates.p3).not.toBeUndefined())
  expect(scrollSpy).not.toHaveBeenCalled()
  // The walk finishes: the FINAL restore clamps against the full depth.
  gates.p3!({ data: { items: [dive(201, '201B', 1), dive(202, '202B', 1)], next_cursor: null } })
  await screen.findByRole('button', { name: /Open 202B attempt/ })
  await waitFor(() => expect(scrollSpy).toHaveBeenCalled())
  // 6000 - innerHeight = 5232 max; the 5000 anchor sits inside it.
  expect(scrollSpy.mock.calls[0][1]).toBe(5000)
  scrollSpy.mockRestore()
  if (originalHeight) Object.defineProperty(document.documentElement, 'scrollHeight', originalHeight!)
})

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
