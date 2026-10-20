import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import useEvaluationVideoSource, { PREVIEW_DOWNLOAD_TIMEOUT_MS } from './useEvaluationVideoSource'

const createObjectURL = vi.fn((_blob: Blob) => 'blob:preview')
const revokeObjectURL = vi.fn()
beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL, revokeObjectURL }))
  vi.stubGlobal('fetch', vi.fn())
  createObjectURL.mockClear(); revokeObjectURL.mockClear()
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('buffers an authenticated preview before exposing its playable source and releases it on unmount', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { headers: { 'content-type': 'video/mp4' } }))
  const { result, unmount } = renderHook(() => useEvaluationVideoSource('/evaluation/play', 'proxy_720p'))
  expect(result.current.src).toBeUndefined()
  await waitFor(() => expect(result.current.src).toBe('blob:preview'))
  expect(fetch).toHaveBeenCalledWith('/evaluation/play', expect.objectContaining({ credentials: 'same-origin', signal: expect.any(AbortSignal) }))
  expect(createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob)
  unmount()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:preview')
})

it('streams originals without downloading the full file into memory', () => {
  const { result } = renderHook(() => useEvaluationVideoSource('/evaluation/original', 'original'))
  expect(result.current.src).toBe('/evaluation/original')
  expect(fetch).not.toHaveBeenCalled()
})

it('reports failed downloads instead of marking the video ready', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response('unavailable', { status: 503 }))
  const { result } = renderHook(() => useEvaluationVideoSource('/evaluation/play', 'proxy_720p'))
  await waitFor(() => expect(result.current.error?.message).toContain('503'))
  expect(result.current.src).toBeUndefined()
  expect(createObjectURL).not.toHaveBeenCalled()
})

it('streams previews above the memory limit', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response('large', { headers: { 'content-length': String(17 * 1024 * 1024) } }))
  const { result } = renderHook(() => useEvaluationVideoSource('/evaluation/play', 'proxy_720p'))
  await waitFor(() => expect(result.current.src).toBe('/evaluation/play'))
  expect(createObjectURL).not.toHaveBeenCalled()
})

it('aborts a pending transfer and ignores completion after the evaluation player leaves', async () => {
  let finish!: (response: Response) => void
  vi.mocked(fetch).mockReturnValue(new Promise(resolve => { finish = resolve }))
  const { unmount } = renderHook(() => useEvaluationVideoSource('/evaluation/play', 'proxy_720p'))
  const signal = vi.mocked(fetch).mock.calls[0][1]?.signal
  unmount()
  expect(signal?.aborted).toBe(true)
  await act(async () => { finish(new Response(new Uint8Array([1, 2, 3]))) })
  expect(createObjectURL).not.toHaveBeenCalled()
})

it.each(['headers', 'body'] as const)('bounds a stalled preview %s and ignores its late completion', async stage => {
  vi.useFakeTimers()
  let finish!: (response: Response) => void
  if (stage === 'headers') vi.mocked(fetch).mockReturnValue(new Promise(resolve => { finish = resolve }))
  else vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array([1])) } })))
  const { result } = renderHook(() => useEvaluationVideoSource('/evaluation/stalled', 'proxy_720p'))
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(result.current.src).toBeUndefined()
  await act(async () => { await vi.advanceTimersByTimeAsync(PREVIEW_DOWNLOAD_TIMEOUT_MS) })
  expect(result.current.error?.message).toContain('timed out')
  expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true)
  if (stage === 'headers') await act(async () => { finish(new Response(new Uint8Array([1, 2, 3]))) })
  expect(result.current.src).toBeUndefined()
  expect(createObjectURL).not.toHaveBeenCalled()
})
