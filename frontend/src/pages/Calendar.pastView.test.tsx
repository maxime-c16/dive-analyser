/** Calendar past view (profil 11 C5): the "next three months" empty notice
 * never renders under past sessions the screen actually shows. */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import Calendar from './Calendar'

vi.mock('../calendar/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../calendar/api')>(),
  calendarApi: {
    me: vi.fn(), calendars: vi.fn(), occurrences: vi.fn(), setAbsence: vi.fn(),
  },
}))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { user_id: 1, display_name: 'Me', is_admin: false, email: 'x@x.x' } }),
}))
vi.mock('../navigation/mobileShellActions', () => ({ MobileShellActions: () => null }))

import { calendarApi } from '../calendar/api'

const event = { id: 2, title: 'Plongée champigny', status: 'published', event_type: 'training',
  audience: 'group', timezone: 'Europe/Paris', calendar_kind: 'group', resources: [], occurrences: [],
  description: '', can_edit: false, changes: [] }

const monthString = (offsetDays: number) => {
  const day = new Date(Date.now() + offsetDays * 86_400_000)
  return new Intl.DateTimeFormat('sv', { timeZone: 'Europe/Paris' }).format(day)
}

const occurrence = (localDate: string) => ({ id: 7, event, local_date: localDate,
  local_end_date: localDate, local_start: '12:00', local_end: '13:30', status: 'scheduled',
  can_report_absence: false, my_absence_reported: false, my_interest: null,
  changes: [], going: { interested: 0, maybe: 0, people: [] } } as never)

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(calendarApi.me).mockResolvedValue({ clubs: [] } as never)
  vi.mocked(calendarApi.calendars).mockResolvedValue({ items: [] } as never)
  vi.mocked(calendarApi.occurrences).mockImplementation(async (from: string, _to: string) => {
    const past = new Date(from).getTime() < Date.now() - 86_400_000
    return past ? [occurrence(monthString(-5))] : []
  })
})

function renderView(search: string) {
  return render(<MemoryRouter initialEntries={[`/calendar${search}`]}><Calendar /></MemoryRouter>)
}

it('never shows the next-three-months notice under visible past sessions', async () => {
  renderView('?past=1')
  expect(await screen.findByText('Plongée champigny')).toBeInTheDocument()
  expect(screen.queryByText('Nothing scheduled in the next three months.')).not.toBeInTheDocument()
  expect(screen.queryByText('Nothing recorded in the past three months.')).not.toBeInTheDocument()
})

it('names the past window honestly when it is empty too', async () => {
  vi.mocked(calendarApi.occurrences).mockResolvedValue([])
  renderView('?past=1')
  expect(await screen.findByText('Nothing recorded in the past three months.')).toBeInTheDocument()
})

it('handles a failed past window: retries and no empty claim until real data', async () => {
  const user = userEvent.setup()
  // Only the 90-day past window fails on its first call; the retried call
  // answers with a real (empty) array.
  let pastFails = true
  vi.mocked(calendarApi.occurrences).mockImplementation(async (from: string) => {
    if (new Date(from).getTime() <= Date.now() - 30 * 86_400_000) {
      if (pastFails) { pastFails = false; throw new Error('down') }
      return []
    }
    return []
  })
  renderView('?past=1')
  // The failing past request surfaces its own retryable error state (the
  // past-view banner carries a Retry of its own).
  expect(await screen.findByText('The calendar could not be loaded.')).toBeInTheDocument()
  expect(screen.queryByText('Nothing recorded in the past three months.')).not.toBeInTheDocument()
  // Retry: the next past call answers honestly with an empty array and the
  // claim is then truthful.
  await user.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(screen.getByText('Nothing recorded in the past three months.')).toBeInTheDocument())
  expect(screen.queryByText('The calendar could not be loaded.')).not.toBeInTheDocument()
})


it('keeps the upcoming notice for the default upcoming view', async () => {
  renderView('')
  expect(await screen.findByText('Nothing scheduled in the next three months.')).toBeInTheDocument()
})
