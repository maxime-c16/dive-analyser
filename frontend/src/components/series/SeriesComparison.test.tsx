import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import SeriesComparison from './SeriesComparison'
import { seriesApi } from '../../services/seriesApi'
import { api } from '../../services/api'

vi.mock('../../services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
vi.mock('../../services/seriesApi', async original => ({ ...await original<typeof import('../../services/seriesApi')>(), seriesApi: { clips: vi.fn() } }))
const clip = (id: number, mean_score: number | null) => ({ id, video_uuid: `clip-${id}`, mean_score, rating_count: mean_score == null ? 0 : 1, date: '2026-10-22', url: `/dives?clip=${id}` })
const main = { code: '101B', dd: 1.5, clip_id: null, clip: clip(1, 7) }
const alternative = { code: '103B', dd: 2, clip_id: null, clip: clip(2, 6) }
const previews = { 'clip-1': { playback_url: '/one.mp4' }, 'clip-2': { playback_url: '/two.mp4' } }
beforeEach(async () => {
  vi.clearAllMocks(); vi.unstubAllGlobals()
  await i18n.changeLanguage('fr')
  vi.mocked(seriesApi.clips).mockImplementation(async code => code === '101B' ? [main.clip, clip(3, 8)] : [alternative.clip])
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.mocked(api.get).mockResolvedValue({ data: { status: 'ready', preview_url: '/three.mp4' } })
})
it('compares estimates, changes the selected clip and keeps playback independent', async () => {
  const onUse = vi.fn()
  const { unmount } = render(<StrictMode><SeriesComparison main={main} alternative={alternative} height="3m" policy="best" previews={previews} onClose={vi.fn()} onUse={onUse} /></StrictMode>)
  expect(screen.getByLabelText('Vidéo 101B')).toHaveAttribute('src', '/one.mp4')
  const points = screen.getByRole('row', { name: /Points estimés/ })
  expect(points).toHaveTextContent('31,5'); expect(points).toHaveTextContent('36'); expect(points).toHaveTextContent('+4,5')
  fireEvent.play(screen.getByLabelText('Vidéo 101B'))
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled()
  await waitFor(() => expect(screen.getByLabelText('Clip 101B').children).toHaveLength(2))
  await userEvent.selectOptions(screen.getByLabelText('Clip 101B'), '3')
  await screen.findByLabelText('Vidéo 101B')
  expect(within(points).getAllByText('36')).toHaveLength(2)
  await userEvent.click(screen.getByRole('button', { name: 'Utiliser 103B' }))
  expect(onUse).toHaveBeenCalledWith(expect.objectContaining({ clip_id: 3 }), expect.objectContaining({ code: '103B' }))
  unmount()
  expect(HTMLMediaElement.prototype.load).toHaveBeenCalled()
})
it('shows missing estimates and pauses videos when switching mobile tabs', async () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
  render(<SeriesComparison main={main} alternative={{ ...alternative, clip: clip(2, null) }} height="3m" policy="recent" previews={previews} onClose={vi.fn()} onUse={vi.fn()} />)
  expect(screen.getByRole('row', { name: /Points estimés/ })).toHaveTextContent('—')
  await userEvent.click(screen.getByRole('tab', { name: 'Alternative · 103B' }))
  expect(screen.getByRole('tabpanel', { name: 'Alternative · 103B' })).toBeVisible()
  expect(screen.getByRole('tab', { name: 'Alternative · 103B' })).toHaveAttribute('aria-selected', 'true')
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled()
})
