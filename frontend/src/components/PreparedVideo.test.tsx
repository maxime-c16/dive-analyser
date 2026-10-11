import { createRef } from 'react'
import { render, fireEvent } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import PreparedVideo from './PreparedVideo'
import { resetPreparedPlayback } from '../utils/preparedPlayback'
afterEach(resetPreparedPlayback)
function setup() {
  const videoRef = createRef<HTMLVideoElement>()
  const soundRef = createRef<HTMLVideoElement>()
  const ready = vi.fn()
  const props = { videoUuid: 'full-quality', videoRef, soundRef, src: '/original.mp4', originalSrc: '/original.mp4', className: 'clip-video', label: 'Dive', onVideoChange: vi.fn(), onLoadedMetadata: vi.fn(), onCanPlay: ready, onPlay: vi.fn(), onPause: vi.fn(), onError: vi.fn() }
  return { ...render(<PreparedVideo {...props} />), videoRef, soundRef, ready }
}
it('streams the full-quality source through one video and audio clock', () => {
  const view = setup()
  expect(view.container.querySelectorAll('video')).toHaveLength(1)
  expect(view.videoRef.current).toHaveAttribute('src', '/original.mp4')
  expect(view.soundRef.current).toBe(view.videoRef.current)
  fireEvent.canPlay(view.videoRef.current!)
  expect(view.ready).toHaveBeenCalledOnce()
})
it('clears the full-quality source when authorization resets', () => {
  const view = setup()
  resetPreparedPlayback()
  expect(view.videoRef.current).not.toHaveAttribute('src')
})
it('clears the decoder and source on navigation away', () => {
  const view = setup()
  const video = view.videoRef.current!
  view.unmount()
  expect(video.getAttribute('src')).toBeNull()
})
