import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import OccurrenceView from './OccurrenceView'
import { calendarApi } from './api'

vi.mock('./api', async (original) => ({...await original<typeof import('./api')>(), calendarApi: {
  occurrence: vi.fn(), event: vi.fn(), setAbsence: vi.fn(), setInterest: vi.fn(), dives: vi.fn(),
  results: vi.fn(), eventTrainingOpenings: vi.fn(), createTrainingOpening: vi.fn(), deleteTrainingOpening: vi.fn(),
}}))
vi.mock('./useStrings', async original => {
  const module = await original<typeof import('./useStrings')>()
  const {strings} = await import('./strings')
  return {...module, useCalendarStrings: () => ({t: strings.fr, lang: 'fr'})}
})
const event = {id: 2, title: 'Entraînement', status: 'published', event_type: 'training',
  audience: 'group', timezone: 'Europe/Paris', calendar_kind: 'group', resources: [], occurrences: [],
  description: '', can_edit: false, changes: []}
let absent = false
beforeEach(() => {
  vi.clearAllMocks(); absent = false
  vi.mocked(calendarApi.event).mockResolvedValue(event as never)
  vi.mocked(calendarApi.dives).mockResolvedValue({items: []})
  vi.mocked(calendarApi.occurrence).mockImplementation(async () => ({id: 7, event, local_date: '2026-10-17',
    local_end_date: '2026-10-17', local_start: '13:00', local_end: '15:00', status: 'scheduled',
    can_report_absence: true, my_absence_reported: absent, my_interest: 'maybe', shared_session_id: 9,
    changes: [], going: {interested: absent ? 2 : 3, maybe: 0, people: []}} as never))
  vi.mocked(calendarApi.setAbsence).mockImplementation(async (_, value) => {absent = value; return {} as never})
})
it('offers only absence and cancellation, preserving the filmed session link', async () => {
  render(<MemoryRouter><OccurrenceView occurrenceId={7} ctx={{me: [], calendars: [], refresh: vi.fn()}}/></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', {name: 'Je ne viens pas'}))
  await waitFor(() => expect(calendarApi.setAbsence).toHaveBeenCalledWith(7, true))
  fireEvent.click(await screen.findByRole('button', {name: 'Annuler mon absence'}))
  await waitFor(() => expect(calendarApi.setAbsence).toHaveBeenLastCalledWith(7, false))
  expect(await screen.findByRole('button', {name: 'Je ne viens pas'})).toHaveAttribute('aria-pressed', 'false')
  expect(screen.getByRole('link', {name: 'Voir la séance'})).toHaveAttribute('href', '/sessions/shared/9')
  expect(screen.queryByRole('button', {name: /peut-être|intéressé/i})).toBeNull()
})

it('shows opt-in join toggle on open-access sessions from another group', async () => {
  let interest: 'interested' | null = null
  vi.mocked(calendarApi.occurrence).mockImplementation(async () => ({id: 8, event, local_date: '2026-11-24',
    local_end_date: '2026-11-24', local_start: '19:00', local_end: '21:00', status: 'scheduled',
    can_report_absence: false, open_access: true, my_absence_reported: false, my_interest: interest,
    changes: [], going: {interested: interest ? 2 : 1, maybe: 0, people: []}} as never))
  vi.mocked(calendarApi.setInterest).mockImplementation(async (_, state) => {
    interest = state === 'interested' ? 'interested' : null
    return {} as never
  })
  render(<MemoryRouter><OccurrenceView occurrenceId={8} ctx={{me: [], calendars: [], refresh: vi.fn()}}/></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', {name: 'Je viens'}))
  await waitFor(() => expect(calendarApi.setInterest).toHaveBeenCalledWith(8, 'interested'))
  fireEvent.click(await screen.findByRole('button', {name: 'J’y vais'}))
  await waitFor(() => expect(calendarApi.setInterest).toHaveBeenLastCalledWith(8, null))
  expect(screen.queryByRole('button', {name: 'Je ne viens pas'})).toBeNull()
})

it('lets club publishers open training windows from a competition page', async () => {
  const compEvent = {...event, id: 20, title: 'Régionale Hiver', event_type: 'competition', calendar_kind: 'federal'}
  vi.mocked(calendarApi.event).mockResolvedValue(compEvent as never)
  vi.mocked(calendarApi.results).mockResolvedValue({available: false, can_import: false, results: null})
  vi.mocked(calendarApi.occurrence).mockResolvedValue({id: 21, event: compEvent, local_date: '2026-12-06',
    local_end_date: '2026-12-06', is_all_day: true, status: 'scheduled', can_report_absence: false,
    my_absence_reported: false, changes: [], going: {interested: 0, maybe: 0, people: []}} as never)
  let openings: unknown[] = []
  vi.mocked(calendarApi.eventTrainingOpenings).mockImplementation(async () => ({
    event_id: 20, default_starts_on: '2026-11-23', default_ends_on: '2026-12-05',
    clubs: [{club_id: 1, club_name: 'KCPM', groups: [{id: 2, club_id: 1, slug: 'confirmes', name: 'Confirmés'}], openings}],
  } as never))
  vi.mocked(calendarApi.createTrainingOpening).mockImplementation(async () => {
    openings = [{id: 99, club_id: 1, eligible_group_id: 2, eligible_group_name: 'Confirmés',
      competition_event_id: 20, competition_title: 'Régionale Hiver', label: null,
      starts_on: '2026-11-23', ends_on: '2026-12-05'}]
    return openings[0] as never
  })
  vi.mocked(calendarApi.deleteTrainingOpening).mockImplementation(async () => { openings = [] })

  render(<MemoryRouter><OccurrenceView occurrenceId={21} ctx={{me: [], calendars: [], refresh: vi.fn()}}/></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', {name: 'Ouvrir'}))
  await waitFor(() => expect(calendarApi.createTrainingOpening).toHaveBeenCalledWith(1, {
    eligible_group_id: 2, competition_event_id: 20, starts_on: '2026-11-23', ends_on: '2026-12-05',
  }))
  fireEvent.click(await screen.findByRole('button', {name: 'Retirer'}))
  await waitFor(() => expect(calendarApi.deleteTrainingOpening).toHaveBeenCalledWith(1, 99))
})
