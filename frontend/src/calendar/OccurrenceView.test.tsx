import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import OccurrenceView from './OccurrenceView'
import { calendarApi } from './api'

vi.mock('./api', async (original) => ({...await original<typeof import('./api')>(), calendarApi: {
  occurrence: vi.fn(), event: vi.fn(), setAbsence: vi.fn(), dives: vi.fn(),
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
