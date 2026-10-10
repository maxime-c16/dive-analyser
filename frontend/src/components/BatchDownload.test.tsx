import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import BatchDownload from './BatchDownload'
import { saveDownloadBatch, startClipDownload } from '../services/clipDownloads'
vi.mock('../services/clipDownloads', () => ({ saveDownloadBatch: vi.fn(), startClipDownload: vi.fn() }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(saveDownloadBatch).mockResolvedValue([{ id: 9, name: 'dive-9.mp4', url: '/api/v1/dives/9/download' }])
})
it('accepts before requesting downloads and retains a direct retry link', async () => {
  render(<React.StrictMode><MemoryRouter><BatchDownload batchId="b" diverId={7} /></MemoryRouter></React.StrictMode>)
  expect(await screen.findByText('Clips saved to your library')).toBeInTheDocument()
  expect(saveDownloadBatch).toHaveBeenCalledTimes(1)
  expect(saveDownloadBatch).toHaveBeenCalledWith('b', 7)
  expect(startClipDownload).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('link', { name: 'dive-9.mp4' })).toHaveAttribute('href', '/api/v1/dives/9/download')
})
it('never downloads when acceptance fails', async () => {
  vi.mocked(saveDownloadBatch).mockRejectedValue(new Error('Denied'))
  render(<MemoryRouter><BatchDownload batchId="b" diverId={7} /></MemoryRouter>)
  await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  expect(startClipDownload).not.toHaveBeenCalled()
})
it('keeps saved clips and direct links when automatic dispatch is unavailable', async () => {
  vi.mocked(startClipDownload).mockImplementation(() => { throw new Error('Browser unavailable') })
  render(<MemoryRouter><BatchDownload batchId="b" diverId={7} /></MemoryRouter>)
  expect(await screen.findByText('Clips saved to your library')).toBeInTheDocument()
  expect(await screen.findByRole('alert')).toHaveTextContent('Automatic downloading is unavailable')
  expect(screen.getByRole('link', { name: 'dive-9.mp4' })).toBeInTheDocument()
})
