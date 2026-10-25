import { thumbHashToDataURL } from 'thumbhash'
export function placeholderUrl(hash?: string | null): string | undefined {
  if (!hash) return undefined
  try {
    const bytes = Uint8Array.from(atob(hash), c => c.charCodeAt(0))
    if (bytes.length < 5 || bytes.length > 100) return undefined
    return thumbHashToDataURL(bytes)
  } catch { return undefined }
}
