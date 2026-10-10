import { beforeEach, expect, it, vi } from 'vitest'
import { saveDownloadBatch } from './clipDownloads'
import { clearLibraryCache, loadLibraryCache, readLibraryCache } from './libraryCache'

beforeEach(() => { clearLibraryCache(); vi.stubGlobal('fetch', vi.fn()) })
it('collects every manifest page and invalidates a recently cached library', async () => {
  await loadLibraryCache('owner', async () => ({ dives: [], divers: [] }))
  expect(readLibraryCache('owner')).not.toBeNull()
  vi.mocked(fetch)
    .mockResolvedValueOnce(Response.json({ clips: [{ id: 1, name: 'one.mp4', url: '/api/v1/dives/1/download' }], next_offset: 500 }))
    .mockResolvedValueOnce(Response.json({ clips: [{ id: 2, name: 'two.mp4', url: '/api/v1/dives/2/download' }], next_offset: null }))
  const clips = await saveDownloadBatch('batch', 7)
  expect(clips.map(clip => clip.id)).toEqual([1, 2])
  expect(vi.mocked(fetch).mock.calls.map(call => call[0])).toEqual([
    '/api/v1/deposits/batches/batch/save-download?diver_id=7&offset=0',
    '/api/v1/deposits/batches/batch/save-download?diver_id=7&offset=500',
  ])
  expect(readLibraryCache('owner')).toBeNull()
})
it('retains the existing library when acceptance is denied', async () => {
  await loadLibraryCache('owner', async () => ({ dives: [], divers: [] }))
  vi.mocked(fetch).mockResolvedValue(Response.json({}, { status: 404 }))
  await expect(saveDownloadBatch('batch', 7)).rejects.toThrow('Could not save clips')
  expect(readLibraryCache('owner')).not.toBeNull()
})
