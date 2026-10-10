export type DownloadClip = { id: number; name: string; url: string }
let downloadSequence = 0

export function clipDownloadUrl(id: number): string {
  return `/api/v1/dives/${id}/download`
}

/** Browser-managed transfer: no video blobs, ZIP jobs or signed URLs in state. */
export function startClipDownload(clip: DownloadClip): void {
  const link = document.createElement('a')
  link.href = clip.url
  link.download = clip.name
  const frame = document.createElement('iframe')
  frame.name = `clip-download-${++downloadSequence}`
  frame.hidden = true
  frame.title = 'Video download'
  document.body.appendChild(frame)
  link.target = frame.name
  // Attachment responses transfer through the browser's download manager.
  setTimeout(() => frame.remove(), 300_000)
  link.referrerPolicy = 'no-referrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

export async function saveDownloadBatch(batchId: string, diverId: number): Promise<DownloadClip[]> {
  const clips: DownloadClip[] = []
  let offset: number | null = 0
  do {
    const response = await fetch(`/api/v1/deposits/batches/${encodeURIComponent(batchId)}/save-download?diver_id=${diverId}&offset=${offset}`, {
      method: 'POST', credentials: 'same-origin',
    })
    if (!response.ok) throw new Error('Could not save clips')
    // Acceptance commits before the manifest returns. Returning to a recently
    // visited library must fetch these newly accepted clips immediately.
    clearLibraryCache()
    clearIntentData()
    const data: { clips: DownloadClip[]; next_offset: number | null } = await response.json()
    clips.push(...data.clips)
    offset = data.next_offset
  } while (offset !== null)
  return clips
}
import { clearLibraryCache } from './libraryCache'
import { clearIntentData } from './intentCache'
