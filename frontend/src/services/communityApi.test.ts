import { afterEach, expect, it, vi } from 'vitest'
import { uploadAvatar } from './communityApi'

afterEach(() => { vi.restoreAllMocks() })

it('sends the avatar as raw image bytes so the server can limit it before parsing', async () => {
  const file = new File(['image bytes'], 'avatar.png', { type: 'image/png' })
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({ user_id: 1, avatar_url: '/avatar' }) } as Response)
  await uploadAvatar(file)
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/users/me/avatar', {
    credentials: 'same-origin', method: 'PUT', headers: { 'Content-Type': 'image/png' }, body: file,
  })
})
