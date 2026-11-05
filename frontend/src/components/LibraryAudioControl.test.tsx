import { createRef } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import LibraryAudioControl from './LibraryAudioControl'
import PreparedVideo from './PreparedVideo'
import { acquirePlaybackVideo, resetPreparedPlayback } from '../utils/preparedPlayback'
import { getLibraryAudioMuted, setLibraryAudioMuted } from '../utils/libraryAudioPreference'

afterEach(() => { setLibraryAudioMuted(false); resetPreparedPlayback(); vi.restoreAllMocks() })
function prepared(uuid: string) {
  const videoRef = createRef<HTMLVideoElement>()
  const soundRef = createRef<HTMLVideoElement>()
  const video = acquirePlaybackVideo(uuid)
  Object.defineProperty(video, 'readyState', { configurable: true, value: 4 })
  const props = { videoUuid: uuid, videoRef, soundRef, src: '/ready.mp4', className: 'clip-video', label: uuid,
    onVideoChange: () => {}, onLoadedMetadata: () => {}, onCanPlay: () => { void videoRef.current?.play() },
    onPlay: () => {}, onPause: () => {}, onError: () => {} }
  return { video, props }
}

it('applies a visible pre-entry mute before the first autoplay and keeps it across clip adoption and cleanup', () => {
  render(<LibraryAudioControl />)
  fireEvent.click(screen.getByRole('button', { name: 'Mute videos' }))
  expect(screen.getByRole('button', { name: 'Turn video sound on' })).toHaveTextContent('Muted')
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function(this: HTMLMediaElement) {
    expect(this.muted).toBe(true)
    return Promise.resolve()
  })
  const first = prepared('first')
  const view = render(<PreparedVideo {...first.props} />)
  expect(play).toHaveBeenCalledTimes(1)
  const next = prepared('next')
  view.rerender(<PreparedVideo {...next.props} />)
  expect(play).toHaveBeenCalledTimes(2)
  expect(first.video.getAttribute('src')).toBeNull()
  view.unmount()
  expect(next.video.getAttribute('src')).toBeNull()
  expect(getLibraryAudioMuted()).toBe(true)
  const reopened = prepared('reopened')
  render(<PreparedVideo {...reopened.props} />)
  expect(play).toHaveBeenCalledTimes(3)
})

it('preserves sound-on autoplay by default and applies an explicit sound-on choice to the active clip', () => {
  render(<LibraryAudioControl />)
  const first = prepared('default')
  const play = vi.spyOn(first.video, 'play').mockImplementation(() => {
    expect(first.video.muted).toBe(false)
    return Promise.resolve()
  })
  render(<PreparedVideo {...first.props} />)
  expect(play).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: 'Mute videos' }))
  expect(first.video.muted).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Turn video sound on' }))
  expect(first.video.muted).toBe(false)
})

it('keeps the user choice for this session when persistent storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage unavailable') })
  render(<LibraryAudioControl />)
  fireEvent.click(screen.getByRole('button', { name: 'Mute videos' }))
  const clip = prepared('private-storage')
  render(<PreparedVideo {...clip.props} />)
  expect(clip.video.muted).toBe(true)
  expect(getLibraryAudioMuted()).toBe(true)
  act(() => setLibraryAudioMuted(false))
  expect(clip.video.muted).toBe(false)
})
