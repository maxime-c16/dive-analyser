import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import MeetResults from './MeetResults'
import { calendarApi, CalendarError, type MeetResultsPage } from './api'

vi.mock('./api', async (original) => ({...await original<typeof import('./api')>(), calendarApi: {
  event: vi.fn(), results: vi.fn(), previewResults: vi.fn(), saveResults: vi.fn(), deleteResults: vi.fn(),
}}))
vi.mock('./useStrings', async original => {
  const module = await original<typeof import('./useStrings')>()
  const {strings} = await import('./strings')
  return {...module, useCalendarStrings: () => ({t: strings.fr, lang: 'fr'})}
})

const dive = (code: string, points: number, total: number, penalty: number | null = null) => ({
  dive_code: code, height: 3, dd: 2.1, judges: [6, 6.5, 6], cumul: 18.5, points, running_total: total, penalty})
const page: MeetResultsPage = {can_import: false, available: true, results: {
  source_name: 'idf.pdf', meet_date: '2026-11-22', imported_at: '2026-11-23T10:00:00Z', events: [
    {id: 1, title: 'Elite - Dames - 3m', board: '3m', entries: [
      {id: 10, rank: 1, diver_name: 'Anna TESTA', birth_year: 2001, club_name: 'Club Alpha', total: 70.3, status: null,
        guest: false, is_me: false, account: null, dives: [dive('201B', 34.2, 34.2), dive('304C', 36.1, 70.3, 4)]},
    ]},
    {id: 2, title: 'Elite - Messieurs - HV', board: 'HV', entries: [
      {id: 20, rank: null, diver_name: 'Dan DEMO', birth_year: null, club_name: 'Club Z', total: 0, status: 'withdrawn',
        guest: true, is_me: false, account: null, dives: []},
    ]},
  ]}}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(calendarApi.event).mockResolvedValue({id: 5, title: 'Championnats IDF'} as never)
  vi.mocked(calendarApi.results).mockResolvedValue(page)
})

const view = () => render(<MemoryRouter><MeetResults eventId={5}/></MemoryRouter>)

it('shows each event ranking as printed, with dives, penalties and exit states', async () => {
  view()
  expect(await screen.findByRole('heading', {name: 'Championnats IDF'})).toBeInTheDocument()
  expect(screen.getByText('dimanche 22 novembre 2026')).toBeInTheDocument()
  const anna = screen.getByRole('button', {name: /Anna TESTA/})
  expect(within(anna).getByText('70,30')).toBeInTheDocument()
  fireEvent.click(anna)
  expect(anna).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText('304C')).toBeInTheDocument()
  expect(screen.getByText('Bras')).toBeInTheDocument()
  expect(screen.queryByText(/Importer/)).toBeNull()

  fireEvent.click(screen.getByRole('tab', {name: 'Elite - Messieurs - HV'}))
  expect(screen.getByRole('tab', {name: 'Elite - Messieurs - HV'})).toHaveAttribute('aria-selected', 'true')
  const dan = screen.getByRole('button', {name: /Dan DEMO/})
  expect(within(dan).getByText('Abandon')).toBeInTheDocument()
  expect(within(dan).getByText('Invité·e')).toBeInTheDocument()
})

it('opens on the viewer\'s own event, highlights their row and links the account profile', async () => {
  const men = page.results!.events[1]
  const me = {...men.entries[0], id: 21, rank: 1, diver_name: 'Max MOI', status: null, guest: false, total: 150, is_me: true,
    account: {user_id: 3, display_name: 'max', avatar_url: null, avatar_hud: 'reticle' as const}}
  vi.mocked(calendarApi.results).mockResolvedValue({...page, results: {...page.results!, events: [
    page.results!.events[0], {...men, entries: [me, ...men.entries]}]}})
  view()
  const row = await screen.findByRole('button', {name: /Max MOI/})
  expect(screen.getByRole('tab', {name: 'Elite - Messieurs - HV'})).toHaveAttribute('aria-selected', 'true')
  expect(row.closest('li')).toHaveClass('is-me')
  fireEvent.click(row)
  expect(screen.getByRole('link', {name: 'max'})).toHaveAttribute('href', '/users/3')
})

it('previews a PDF before saving and reports a sheet dated outside the event', async () => {
  vi.mocked(calendarApi.results).mockResolvedValue({can_import: true, available: false, results: null})
  vi.mocked(calendarApi.previewResults).mockResolvedValue({meet_date: '2026-11-22', date_matches: false,
    events: [{title: 'E', board: '3m', entries: 3}], entry_count: 3, dive_count: 6, warnings: ['Line 9: x'], replaces: false, linked_count: 2})
  vi.mocked(calendarApi.saveResults).mockResolvedValue({...page, can_import: true})
  const {container} = view()
  await screen.findByRole('button', {name: /Importer les résultats/})
  const file = new File(['%PDF-1.4'], 'idf.pdf', {type: 'application/pdf'})
  fireEvent.change(container.querySelector('input[type=file]')!, {target: {files: [file]}})
  expect(await screen.findByText('1 épreuves · 3 plongeurs · 6 plongeons')).toBeInTheDocument()
  expect(screen.getByText(/hors des dates/)).toBeInTheDocument()
  expect(screen.getByText('1 lignes à vérifier')).toBeInTheDocument()
  expect(screen.getByText('2 reliés à un compte')).toBeInTheDocument()
  expect(calendarApi.saveResults).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', {name: 'Enregistrer les résultats'}))
  await waitFor(() => expect(calendarApi.saveResults).toHaveBeenCalledWith(5, file))
  expect(await screen.findByRole('button', {name: /Anna TESTA/})).toBeInTheDocument()
  expect(screen.getByRole('button', {name: /Remplacer/})).toBeInTheDocument()
})

it('explains a rejected file and ignores a slower preview of an earlier pick', async () => {
  vi.mocked(calendarApi.results).mockResolvedValue({can_import: true, available: false, results: null})
  const preview = (dives: number) => ({meet_date: null, date_matches: null, events: [{title: 'E', board: '3m', entries: 1}],
    entry_count: 1, dive_count: dives, warnings: [] as string[], replaces: false, linked_count: 0})
  let releaseFirst: (v: ReturnType<typeof preview>) => void = () => undefined
  vi.mocked(calendarApi.previewResults)
    .mockRejectedValueOnce(new CalendarError(422, 'not_pdf', ''))
    .mockImplementationOnce(() => new Promise((resolve) => { releaseFirst = resolve }))
    .mockResolvedValueOnce(preview(2))
  const {container} = view()
  await screen.findByRole('button', {name: /Importer les résultats/})
  const input = container.querySelector('input[type=file]')!
  fireEvent.change(input, {target: {files: [new File(['x'], 'a.txt')]}})
  expect(await screen.findByRole('alert')).toHaveTextContent('Ce fichier n’est pas un PDF.')

  fireEvent.change(input, {target: {files: [new File(['%PDF'], 'old.pdf')]}})
  fireEvent.change(input, {target: {files: [new File(['%PDF'], 'new.pdf')]}})
  expect(await screen.findByText('1 épreuves · 1 plongeurs · 2 plongeons')).toBeInTheDocument()
  releaseFirst(preview(99))
  await new Promise((r) => setTimeout(r, 0))
  expect(screen.queryByText(/99 plongeons/)).toBeNull()
  expect(screen.getByText('new.pdf')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
})
