import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import TechniqueTrackChart from './TechniqueTrackChart'
import { api } from '../../services/api'
import '../../i18n'

vi.mock('../../services/api', () => ({ api: { post: vi.fn() } }))

it('restarts a paged period after an end-date edit and can browse all history', async () => {
  const post = vi.mocked(api.post)
  const base = '/api/v1/technique-history/1/2'
  const context = { code: '201C' }
  const period = { id: 13, label: 'Look forward', start_at: '2024-11-26T00:00:00', end_at: null, uncertain_until: null }
  const row = { point_key: 'cursor', occurred_at: '2025-11-04T00:00:00', median: 7, episode_id: 13 }
  post.mockResolvedValue({ data: { items: [row], boundaries: [period], next: 'cursor', range: { start: row.occurred_at, end: row.occurred_at } } })
  const props = { base, context, selected: period.id, onSelect: vi.fn() }
  const view = render(<TechniqueTrackChart {...props} selection={period} revision={1} />)
  fireEvent.click(await screen.findByRole('button', { name: 'More history' }))
  await waitFor(() => expect(post).toHaveBeenLastCalledWith(`${base}/track-chart`, { ...context, after: 'cursor', episode_id: 13 }, expect.anything()))

  const edited = { ...period, end_at: '2025-03-28T00:00:00' }
  post.mockResolvedValue({ data: { items: [], boundaries: [], next: null, range: null } })
  view.rerender(<TechniqueTrackChart {...props} selection={edited} revision={2} />)
  expect(screen.getByText('26 Nov 2024 – 28 Mar 2025')).toBeInTheDocument()
  await screen.findByText('No rated dives in this period.')
  expect(post).toHaveBeenLastCalledWith(`${base}/track-chart`, { ...context, after: '', episode_id: 13 }, expect.anything())
  expect(screen.queryByRole('button', { name: 'More history' })).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'All periods' }))
  await waitFor(() => expect(post).toHaveBeenLastCalledWith(`${base}/track-chart`, { ...context, after: '' }, expect.anything()))
  fireEvent.click(screen.getByRole('button', { name: 'This period' }))
  await waitFor(() => expect(post).toHaveBeenLastCalledWith(`${base}/track-chart`, { ...context, after: '', episode_id: 13 }, expect.anything()))
})
