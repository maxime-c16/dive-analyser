import { createRef } from 'react'
import { act, fireEvent, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import PreparedVideo, { fullyBuffered } from './PreparedVideo'
import { resetPreparedPlayback, preparePlaybackWindow } from '../utils/preparedPlayback'
afterEach(resetPreparedPlayback)
const buffered = (ranges: number[][]) => ({ length: ranges.length, start: (i: number) => ranges[i][0], end: (i: number) => ranges[i][1] })
function set(video: HTMLVideoElement, values: Record<string, unknown>) {
  for (const [key, value] of Object.entries(values)) Object.defineProperty(video, key, { configurable: true, value })
}
function setup() {
  const videoRef = createRef<HTMLVideoElement>()
  const changed = vi.fn()
  const props = { videoUuid: 'progressive', videoRef, soundRef: createRef<HTMLVideoElement>(), src: '/preview.mp4', originalSrc: '/original.mov', className: 'clip-video', label: 'Dive', onVideoChange: changed, onLoadedMetadata: vi.fn(), onCanPlay: vi.fn(), onPlay: vi.fn(), onPause: vi.fn(), onError: vi.fn() }
  const view = render(<PreparedVideo {...props} />)
  const preview = videoRef.current!
  set(preview, { paused: false, readyState: 4, duration: 10 })
  preview.currentTime = 2
  fireEvent.playing(preview)
  const original = view.container.querySelector('video[aria-hidden]') as HTMLVideoElement
  set(original, { readyState: 4, duration: 10, paused: false, buffered: buffered([[0, 10]]) })
  let frame!: VideoFrameRequestCallback
  original.requestVideoFrameCallback = vi.fn(callback => { frame = callback; return 1 })
  original.cancelVideoFrameCallback = vi.fn()
  return { ...view, props, preview, original, videoRef, changed, frame: () => frame }
}
it('keeps the preview visible until the whole original is buffered and a matching frame presents', async () => {
  const view = setup()
  set(view.original, { buffered: buffered([[0, 5]]) })
  fireEvent.progress(view.original)
  expect(view.videoRef.current).toBe(view.preview)
  expect(view.changed).not.toHaveBeenCalled()
  set(view.original, { buffered: buffered([[0, 10]]) })
  fireEvent.progress(view.original)
  await act(async () => {})
  expect(view.original.requestVideoFrameCallback).toHaveBeenCalledOnce()
  expect(view.videoRef.current).toBe(view.preview)
  await act(async () => { view.frame()(0, {} as VideoFrameCallbackMetadata) })
  expect(view.videoRef.current).toBe(view.original)
  expect(view.original.currentTime).toBe(2)
  expect(view.original.muted).toBe(true)
  expect(view.props.soundRef.current).toBe(view.preview)
  expect(view.preview.paused).toBe(false)
  expect(view.changed).toHaveBeenCalledOnce()
  expect(view.preview).toHaveAttribute('aria-hidden', 'true')
})
it('does not replace an intentionally paused preview, even if HQ becomes ready', async () => {
  const view = setup()
  set(view.preview, { paused: true })
  fireEvent.progress(view.original)
  await act(async () => {})
  expect(view.original.requestVideoFrameCallback).not.toHaveBeenCalled()
  expect(view.videoRef.current).toBe(view.preview)
})
it('cancels the hidden original and ignores a late presentation callback on navigation', async () => {
  const view = setup()
  fireEvent.progress(view.original)
  await act(async () => {})
  const callback = view.frame()
  view.unmount()
  expect(view.original.getAttribute('src')).toBeNull()
  expect(view.original.cancelVideoFrameCallback).toHaveBeenCalledWith(1)
  await act(async () => { callback(0, {} as VideoFrameCallbackMetadata) })
  expect(view.changed).not.toHaveBeenCalled()
})
it('does not upgrade across an unbuffered gap or an unknown duration', () => {
  const video = document.createElement('video')
  set(video, { duration: 10, buffered: buffered([[0, 4], [5, 10]]) })
  expect(fullyBuffered(video)).toBe(false)
  set(video, { duration: Infinity })
  expect(fullyBuffered(video)).toBe(false)
})
it('keeps AAC continuous: clock drift changes only the muted HQ speed', async () => {
  const view = setup()
  fireEvent.progress(view.original)
  await act(async () => {})
  await act(async () => { view.frame()(0, {} as VideoFrameCallbackMetadata) })
  view.original.currentTime = 2.3
  fireEvent.timeUpdate(view.original)
  expect(view.preview.currentTime).toBe(2)
  expect(view.preview.playbackRate).toBe(1)
  expect(view.original.playbackRate).toBe(0.97)
  fireEvent.rateChange(view.original)
  expect(view.preview.playbackRate).toBe(1)
  // An intentional speed change still drives both transports.
  view.original.playbackRate = 2
  fireEvent.rateChange(view.original)
  expect(view.preview.playbackRate).toBe(2)
  // An explicit seek moves sound; a native loop boundary does not.
  view.original.currentTime = 4
  fireEvent.seeked(view.original)
  expect(view.preview.currentTime).toBe(4)
  view.preview.currentTime = 9.95
  view.original.currentTime = 0
  fireEvent.seeked(view.original)
  expect(view.preview.currentTime).toBe(9.95)
})
it('stops the selected HQ transfer as well as the preview when authorization resets', async () => {
  const view = setup()
  expect(view.original.getAttribute('src')).toBe('/original.mov')
  act(() => resetPreparedPlayback())
  expect(view.original.getAttribute('src')).toBeNull()
  expect(view.preview.getAttribute('src')).toBeNull()
})

it('reuses the loaded HQ immediately when returning to a retained dive', async () => {
  const view = setup()
  preparePlaybackWindow(['progressive', 'neighbor'])
  fireEvent.progress(view.original)
  await act(async () => {})
  await act(async () => { view.frame()(0, {} as VideoFrameCallbackMetadata) })
  view.unmount()
  expect(view.original.getAttribute('src')).toBe('/original.mov')
  const reopened = render(<PreparedVideo {...view.props} />)
  expect(view.videoRef.current).toBe(view.original)
  expect(view.props.soundRef.current).toBe(view.preview)
  expect(view.original).not.toHaveAttribute('aria-hidden')
  expect(view.preview).toHaveAttribute('aria-hidden', 'true')
  expect(reopened.container.querySelector('video:not([aria-hidden])')).toBe(view.original)
})

it('re-aligns and presents HQ after a delayed frame without another media event', async () => {
  const view = setup()
  let retry!: FrameRequestCallback
  const compositor = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { retry = callback; return 7 })
  try {
    fireEvent.progress(view.original)
    await act(async () => {})
    view.preview.currentTime = 2.4
    await act(async () => { view.frame()(0, {} as VideoFrameCallbackMetadata) })
    expect(view.videoRef.current).toBe(view.preview)
    expect(compositor).toHaveBeenCalledOnce()
    // No new progress, seeked or canplaythrough event is required.
    await act(async () => { retry(0) })
    expect(view.original.currentTime).toBe(2.4)
    expect(view.original.requestVideoFrameCallback).toHaveBeenCalledTimes(2)
    await act(async () => { view.frame()(0, {} as VideoFrameCallbackMetadata) })
    expect(view.videoRef.current).toBe(view.original)
    expect(view.preview.currentTime).toBe(2.4)
  } finally { compositor.mockRestore() }
})

it('retries a frame deferred by a preview seek on the next playback tick', async () => {
  const view = setup()
  fireEvent.progress(view.original)
  await act(async () => {})
  set(view.preview, { seeking: true })
  await act(async () => { view.frame()(0, {} as VideoFrameCallbackMetadata) })
  expect(view.videoRef.current).toBe(view.preview)
  set(view.preview, { seeking: false })
  fireEvent.timeUpdate(view.preview)
  await act(async () => {})
  expect(view.original.requestVideoFrameCallback).toHaveBeenCalledTimes(2)
  await act(async () => { view.frame()(0, {} as VideoFrameCallbackMetadata) })
  expect(view.videoRef.current).toBe(view.original)
})
