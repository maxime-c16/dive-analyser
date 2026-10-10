import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import DownloadDiveButton from './DownloadDiveButton'
import { startClipDownload } from '../../services/clipDownloads'
vi.mock('../../services/clipDownloads', async original => ({ ...await original<typeof import('../../services/clipDownloads')>(), startClipDownload: vi.fn() }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn())
  Object.defineProperty(navigator, 'share', { configurable: true, value: vi.fn().mockResolvedValue(undefined) })
  Object.defineProperty(navigator, 'canShare', { configurable: true, value: vi.fn().mockReturnValue(true) })
})
it('requests a browser download and offers another attempt', async () => {
  render(<DownloadDiveButton id={9} />)
  fireEvent.click(screen.getByRole('button', { name: 'Download video' }))
  expect(startClipDownload).toHaveBeenCalledWith({ id: 9, name: 'dive-9.mp4', url: '/api/v1/dives/9/download' })
  fireEvent.click(screen.getByRole('button', { name: 'Download again' }))
  expect(startClipDownload).toHaveBeenCalledTimes(2)
})
it('prepares a same-origin file and shares only on the next explicit click', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, headers: new Headers({ 'content-disposition': 'attachment; filename="dive-2026-10-10-9.mov"' }), blob: async () => new Blob(['video'], { type: 'video/quicktime' }) } as Response)
  render(<DownloadDiveButton id={9} />)
  fireEvent.click(screen.getByRole('button', { name: 'Download video' }))
  fireEvent.click(screen.getByRole('button', { name: 'Prepare video for Photos / sharing' }))
  await screen.findByRole('button', { name: 'Save to Photos / share' })
  expect(fetch).toHaveBeenCalledWith('/api/v1/dives/9/download?for_share=true', { credentials: 'same-origin' })
  expect(navigator.share).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Save to Photos / share' }))
  await waitFor(() => expect(navigator.share).toHaveBeenCalledTimes(1))
  expect(vi.mocked(navigator.share).mock.calls[0][0]?.files?.[0].name).toBe('dive-2026-10-10-9.mov')
})
it('keeps normal downloading available when file sharing fails', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: false } as Response)
  render(<DownloadDiveButton id={9} />)
  fireEvent.click(screen.getByRole('button', { name: 'Download video' }))
  fireEvent.click(screen.getByRole('button', { name: 'Prepare video for Photos / sharing' }))
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Download again' })).toBeEnabled()
})
