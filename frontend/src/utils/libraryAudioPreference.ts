import { useSyncExternalStore } from 'react'

// A device preference, independent of account or media authorization.
const KEY = 'library-video-muted:v1'
const listeners = new Set<() => void>()
function readStored(): boolean {
  try { return typeof window !== 'undefined' && window.localStorage.getItem(KEY) === 'true' }
  catch { return false }
}
let muted = readStored()
export function getLibraryAudioMuted() { return muted }
export function setLibraryAudioMuted(next: boolean) {
  if (muted === next) return
  muted = next
  try { window.localStorage.setItem(KEY, String(next)) } catch { /* Keep this session's deliberate choice. */ }
  listeners.forEach(listener => listener())
}
function onStorage(event: StorageEvent) {
  if (event.key !== KEY && event.key !== null) return
  const next = readStored()
  if (next !== muted) { muted = next; listeners.forEach(listener => listener()) }
}
function subscribe(listener: () => void) {
  if (!listeners.size) window.addEventListener('storage', onStorage)
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
    if (!listeners.size) window.removeEventListener('storage', onStorage)
  }
}
export function useLibraryAudioMuted() {
  return useSyncExternalStore(subscribe, getLibraryAudioMuted, () => false)
}
