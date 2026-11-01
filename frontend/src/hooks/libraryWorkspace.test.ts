import { beforeEach, expect, it } from 'vitest'
import type { AuthUser } from '../contexts/AuthContext'
import { MAX_RESUME_PAGES, readLibraryWorkspace, saveLibraryWorkspace } from './libraryWorkspace'
import { libraryKey } from '../services/libraryCache'

const user = { user_id: 7, role: 'diver', is_admin: false, divers: [] } as unknown as AuthUser
beforeEach(() => sessionStorage.clear())

const storedKey = () => `dive-library-view:v1:${libraryKey(user)}`
it('replaces an old filtered workspace with the reset empty workspace', () => {
  saveLibraryWorkspace(user, new URLSearchParams('q=103C'), 800)
  saveLibraryWorkspace(user, new URLSearchParams(), 120)
  const restored = readLibraryWorkspace(user)!
  expect(restored.params.toString()).toBe('')
  expect(restored.scrollY).toBe(120)
  // Depth hints stay absent unless a paginated depth was actually loaded.
  expect(restored.resume).toBeNull()
})

it('stores only a bounded anchor+pages depth hint, never rows', () => {
  saveLibraryWorkspace(user, new URLSearchParams('q=103C'), 400, { anchor: 4211, pages: 60 })
  const stored = JSON.parse(sessionStorage.getItem(storedKey())!) as { d: unknown }
  // Nothing unlimited: pages clamp to the reprise cap and the object is two numbers.
  const bounded = JSON.parse(JSON.stringify(stored.d)) as { anchor: number; pages: number }
  expect(Object.keys(bounded).sort()).toEqual(['anchor', 'pages'])
  const restored = readLibraryWorkspace(user)!
  expect(restored.resume).toEqual({ anchor: 4211, pages: MAX_RESUME_PAGES })
})

it('drops depth hints below one page and repairs corrupted ones', () => {
  saveLibraryWorkspace(user, new URLSearchParams(), 10, { anchor: null, pages: 0 })
  expect(readLibraryWorkspace(user)!.resume).toBeNull()
  sessionStorage.setItem(storedKey(), JSON.stringify({ p: '', y: 0, d: { pages: 'x', anchor: 4211 } }))
  expect(readLibraryWorkspace(user)!.resume).toBeNull()
  sessionStorage.setItem(storedKey(), JSON.stringify({ p: '', y: 0, d: { pages: 3 } }))
  expect(readLibraryWorkspace(user)!.resume).toEqual({ anchor: null, pages: 3 })
})
