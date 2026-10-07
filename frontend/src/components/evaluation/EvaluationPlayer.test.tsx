import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import EvaluationPlayer from './EvaluationPlayer'
import { getEvaluationMediaStatus, prepareEvaluationMedia } from '../../services/evaluationApi'
vi.mock('../../services/evaluationApi', async importOriginal => ({
  ...await importOriginal<typeof import('../../services/evaluationApi')>(),
  getEvaluationMediaStatus: vi.fn(), prepareEvaluationMedia: vi.fn(),
}))
beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
it('keeps initial playback and quality switching on the automatic transport', async () => {
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready', rendition: 'proxy_720p', poster_url: null, playback_url: '/api/v1/evaluations/automatic/7/media/play', available_renditions: ['original', 'proxy_720p'] })
  const { container } = render(<EvaluationPlayer requestId={7} automatic />)
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toBe('/api/v1/evaluations/automatic/7/media/play?rendition=proxy_720p'))
  expect(getEvaluationMediaStatus).toHaveBeenCalledWith(7, true)
  fireEvent.click(screen.getByRole('button', { name: /quality/i }))
  expect(container.querySelector('video')?.getAttribute('src')).toBe('/api/v1/evaluations/automatic/7/media/play?rendition=original')
  expect(prepareEvaluationMedia).not.toHaveBeenCalled()
})
it('warms the current automatic proxy through the automatic preparation endpoint', async () => {
  const status = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'proxy_360p', poster_url: null, playback_url: '/api/v1/evaluations/automatic/7/media/play', available_renditions: ['proxy_360p'] }
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue(status)
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...status, created_jobs: [], reused_jobs: [] })
  render(<EvaluationPlayer requestId={7} automatic />)
  await waitFor(() => expect(prepareEvaluationMedia).toHaveBeenCalledWith(7, true))
})
