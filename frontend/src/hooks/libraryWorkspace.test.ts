import { beforeEach, expect, it } from 'vitest'
import type { AuthUser } from '../contexts/AuthContext'
import { readLibraryWorkspace, saveLibraryWorkspace } from './libraryWorkspace'
const user = { user_id: 7, role: 'diver', is_admin: false, divers: [] } as unknown as AuthUser
beforeEach(() => sessionStorage.clear())
it('replaces an old filtered workspace with the reset empty workspace', () => {
  saveLibraryWorkspace(user, new URLSearchParams('q=103C'), 800)
  saveLibraryWorkspace(user, new URLSearchParams(), 120)
  const restored = readLibraryWorkspace(user)!
  expect(restored.params.toString()).toBe('')
  expect(restored.scrollY).toBe(120)
})
