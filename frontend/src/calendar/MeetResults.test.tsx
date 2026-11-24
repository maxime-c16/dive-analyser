import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import MeetResults from './MeetResults'
import { calendarApi, CalendarError, type MeetResultsPage } from './api'

vi.mock('./api', async (original) => ({...await original<typeof import('./api')>(), calendarApi: {
  event: vi.fn(), results: vi.fn(), previewResults: vi.fn(), saveResults: vi.fn(), deleteResults: vi.fn(),
  meetAccounts: vi.fn(), setResultLink: vi.fn(), clearResultLink: vi.fn(),
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
        guest: false, is_me: false, account: null, link_source: null, linkable: null, dives: [dive('201B', 34.2, 34.2), dive('304C', 36.1, 70.3, 4)]},
    ]},
    {id: 2, title: 'Elite - Messieurs - HV', board: 'HV', entries: [
      {id: 20, rank: null, diver_name: 'Dan DEMO', birth_year: null, club_name: 'Club Z', total: 0, status: 'withdrawn',
        guest: true, is_me: false, account: null, link_source: null, linkable: null, dives: []},
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
  const dan = screen.getByText('Dan DEMO').closest('.meet-entry-row') as HTMLElement
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
    events: [{title: 'E', board: '3m', entries: 3}], entry_count: 3, dive_count: 6, warnings: [{kind: 'line_ignored' as const, line: 9}], warnings_truncated: true, replaces: false, linked_count: 2})
  vi.mocked(calendarApi.saveResults).mockResolvedValue({...page, can_import: true})
  const {container} = view()
  await screen.findByRole('button', {name: /Importer les résultats/})
  const file = new File(['%PDF-1.4'], 'idf.pdf', {type: 'application/pdf'})
  fireEvent.change(container.querySelector('input[type=file]')!, {target: {files: [file]}})
  expect(await screen.findByText('1 épreuve · 3 plongeurs · 6 plongeons')).toBeInTheDocument()
  expect(screen.getByText(/hors des dates/)).toBeInTheDocument()
  expect(screen.getByText('1 ligne à vérifier')).toBeInTheDocument()
  expect(screen.getByText('Ligne 9 : non reconnue, ignorée')).toBeInTheDocument()
  expect(screen.getByText('D’autres lignes à vérifier ne sont pas listées.')).toBeInTheDocument()
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
    entry_count: 1, dive_count: dives, warnings: [], warnings_truncated: false, replaces: false, linked_count: 0})
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
  expect(await screen.findByText('1 épreuve · 1 plongeur · 2 plongeons')).toBeInTheDocument()
  releaseFirst(preview(99))
  await new Promise((r) => setTimeout(r, 0))
  expect(screen.queryByText(/99 plongeons/)).toBeNull()
  expect(screen.getByText('new.pdf')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
})

it('lets an administrator relink a person, forbid a link or return to automatic', async () => {
  const women = page.results!.events[0]
  const anna = {...women.entries[0], link_source: 'auto' as const, linkable: true,
    account: {user_id: 4, display_name: 'Anna', avatar_url: null, avatar_hud: 'reticle' as const}}
  vi.mocked(calendarApi.results).mockResolvedValue({...page, can_manage_links: true,
    results: {...page.results!, events: [{...women, entries: [anna]}]}})
  vi.mocked(calendarApi.meetAccounts).mockResolvedValue({items: [
    {user_id: 9, display_name: 'Nana', avatar_url: null, avatar_hud: 'orbit', diver_names: ['ANNA T']}]})
  vi.mocked(calendarApi.setResultLink).mockResolvedValue(undefined)
  view()
  fireEvent.click(await screen.findByRole('button', {name: /Anna TESTA/}))
  expect(screen.getByText('auto')).toBeInTheDocument()
  expect(screen.queryByRole('button', {name: 'Revenir à l’automatique'})).toBeNull()

  fireEvent.click(screen.getByRole('button', {name: 'Relier à un compte'}))
  fireEvent.change(screen.getByRole('searchbox'), {target: {value: 'nan'}})
  fireEvent.click(await screen.findByRole('button', {name: /Nana/}, {timeout: 2000}))
  await waitFor(() => expect(calendarApi.setResultLink).toHaveBeenCalledWith(10, 9))
  await waitFor(() => expect(calendarApi.results).toHaveBeenCalledTimes(2))  // reloads: links change in every meet

  // The row stays open across the reload.
  fireEvent.click(await screen.findByRole('button', {name: 'Ne jamais relier'}))
  await waitFor(() => expect(calendarApi.setResultLink).toHaveBeenLastCalledWith(10, null))
})

it('moves between event tabs with the arrow keys (one tab stop)', async () => {
  view()
  const first = await screen.findByRole('tab', {name: 'Elite - Dames - 3m'})
  const second = screen.getByRole('tab', {name: 'Elite - Messieurs - HV'})
  expect(first).toHaveAttribute('tabindex', '0')
  expect(second).toHaveAttribute('tabindex', '-1')
  expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', first.id)
  fireEvent.keyDown(first, {key: 'ArrowRight'})
  await waitFor(() => expect(screen.getByRole('tab', {name: 'Elite - Messieurs - HV'})).toHaveAttribute('aria-selected', 'true'))
  expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', second.id)
  fireEvent.keyDown(second, {key: 'ArrowRight'})  // wraps around
  await waitFor(() => expect(screen.getByRole('tab', {name: 'Elite - Dames - 3m'})).toHaveAttribute('aria-selected', 'true'))
})

it('never leaves a stale account selectable and shows empty and failed searches', async () => {
  const women = page.results!.events[0]
  vi.mocked(calendarApi.results).mockResolvedValue({...page, can_manage_links: true,
    results: {...page.results!, events: [{...women, entries: [{...women.entries[0], linkable: true, link_source: null}]}]}})
  vi.mocked(calendarApi.meetAccounts)
    .mockResolvedValueOnce({items: [{user_id: 9, display_name: 'Nana', avatar_url: null, avatar_hud: 'orbit', diver_names: []}]})
    .mockResolvedValueOnce({items: []})
    .mockRejectedValueOnce(new Error('offline'))
  view()
  fireEvent.click(await screen.findByRole('button', {name: /Anna TESTA/}))
  fireEvent.click(screen.getByRole('button', {name: 'Relier à un compte'}))
  const box = screen.getByRole('searchbox')
  fireEvent.change(box, {target: {value: 'nan'}})
  expect(await screen.findByRole('button', {name: /Nana/}, {timeout: 2000})).toBeInTheDocument()
  fireEvent.change(box, {target: {value: 'nanx'}})
  expect(screen.queryByRole('button', {name: /Nana/})).toBeNull()  // gone at once, before the next answer
  expect(await screen.findByText('Aucun compte ne correspond', {}, {timeout: 2000})).toBeInTheDocument()
  fireEvent.change(box, {target: {value: 'nany'}})
  expect(await screen.findByText('La recherche a échoué. Réessayez.', {}, {timeout: 2000})).toBeInTheDocument()
})

it('keeps Discard disabled while a save is in flight', async () => {
  vi.mocked(calendarApi.results).mockResolvedValue({can_import: true, available: false, results: null})
  vi.mocked(calendarApi.previewResults).mockResolvedValue({meet_date: null, date_matches: null, events: [],
    entry_count: 1, dive_count: 1, warnings: [], warnings_truncated: false, replaces: false, linked_count: 0})
  vi.mocked(calendarApi.saveResults).mockImplementation(() => new Promise(() => undefined))
  const {container} = view()
  await screen.findByRole('button', {name: /Importer les résultats/})
  fireEvent.change(container.querySelector('input[type=file]')!, {target: {files: [new File(['%PDF'], 'a.pdf')]}})
  fireEvent.click(await screen.findByRole('button', {name: 'Enregistrer les résultats'}))
  expect(screen.getByRole('button', {name: 'Abandonner'})).toBeDisabled()
})

it('returns a manually linked person to automatic matching', async () => {
  const women = page.results!.events[0]
  vi.mocked(calendarApi.results).mockResolvedValue({...page, can_manage_links: true,
    results: {...page.results!, events: [{...women, entries: [{...women.entries[0], linkable: true, link_source: 'admin', account: null}]}]}})
  vi.mocked(calendarApi.clearResultLink).mockResolvedValue(undefined)
  view()
  fireEvent.click(await screen.findByRole('button', {name: /Anna TESTA/}))
  expect(screen.getByText('Jamais relié')).toBeInTheDocument()
  expect(screen.queryByRole('button', {name: 'Ne jamais relier'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name: 'Revenir à l’automatique'}))
  await waitFor(() => expect(calendarApi.clearResultLink).toHaveBeenCalledWith(10))
})

it('does not offer to expand a row with nothing behind it', async () => {
  view()
  fireEvent.click(await screen.findByRole('tab', {name: 'Elite - Messieurs - HV'}))
  expect(screen.queryByRole('button', {name: /Dan DEMO/})).toBeNull()
  expect(screen.getByText('Dan DEMO')).toBeInTheDocument()
})

it('shows warning numbers in the reader\'s locale', async () => {
  vi.mocked(calendarApi.results).mockResolvedValue({can_import: true, available: false, results: null})
  vi.mocked(calendarApi.previewResults).mockResolvedValue({meet_date: null, date_matches: null, events: [],
    entry_count: 1, dive_count: 1, warnings: [{kind: 'total_mismatch', diver: 'Ann A', dive: 2, printed: '120.50', expected: '119.5'}],
    warnings_truncated: false, replaces: false, linked_count: 0})
  const {container} = view()
  await screen.findByRole('button', {name: /Importer les résultats/})
  fireEvent.change(container.querySelector('input[type=file]')!, {target: {files: [new File(['%PDF'], 'a.pdf')]}})
  expect(await screen.findByText('Ann A, plongeon 2 : total 120,50 imprimé, 119,50 attendu')).toBeInTheDocument()
})

it('shows a single event by title, a dash for no total, and the import panel after the ranking', async () => {
  const women = page.results!.events[0]
  vi.mocked(calendarApi.results).mockResolvedValue({...page, can_import: true, results: {...page.results!, events: [
    {...women, entries: [...women.entries, {...women.entries[0], id: 11, rank: null, diver_name: 'Eva VIDE', total: null, dives: []}]}]}})
  const {container} = view()
  expect(await screen.findByRole('heading', {name: 'Elite - Dames - 3m'})).toBeInTheDocument()
  expect(screen.queryByRole('tablist')).toBeNull()
  expect(screen.queryByRole('tabpanel')).toBeNull()
  const eva = screen.getByText('Eva VIDE').closest('.meet-entry-row') as HTMLElement
  expect(eva.querySelector('.meet-total')).toHaveTextContent('–')
  const board = container.querySelector('.meet-board')!
  const panel = container.querySelector('.meet-import')!
  expect(board.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('tells admins when a tied account was deactivated and lists previewed events', async () => {
  const women = page.results!.events[0]
  vi.mocked(calendarApi.results).mockResolvedValue({...page, can_manage_links: true, results: {...page.results!, events: [
    {...women, entries: [{...women.entries[0], linkable: true, link_source: 'admin', account: null, account_inactive: true}]}]}})
  view()
  fireEvent.click(await screen.findByRole('button', {name: /Anna TESTA/}))
  expect(screen.getByText('Compte désactivé')).toBeInTheDocument()
  expect(screen.queryByText('Jamais relié')).toBeNull()
  expect(screen.getByRole('button', {name: 'Ne jamais relier'})).toBeInTheDocument()
  expect(screen.getByText('S’applique à toutes les compétitions.')).toBeInTheDocument()
})

it('lists the events found and clears a failed save on discard', async () => {
  vi.mocked(calendarApi.results).mockResolvedValue({can_import: true, available: false, results: null})
  vi.mocked(calendarApi.previewResults).mockResolvedValue({meet_date: null, date_matches: null,
    events: [{title: 'Elite - Dames - 3m', board: '3m', entries: 3}], entry_count: 3, dive_count: 6,
    warnings: [], warnings_truncated: false, replaces: false, linked_count: 0})
  vi.mocked(calendarApi.saveResults).mockRejectedValueOnce(new CalendarError(500, 'http_500', ''))
  const {container} = view()
  await screen.findByRole('button', {name: /Importer les résultats/})
  fireEvent.change(container.querySelector('input[type=file]')!, {target: {files: [new File(['%PDF'], 'a.pdf')]}})
  expect(await screen.findByText('Elite - Dames - 3m')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'Enregistrer les résultats'}))
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'Abandonner'}))
  expect(screen.queryByRole('alert')).toBeNull()
})
