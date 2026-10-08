import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import AvatarManager from './AvatarManager'
import { removeAvatar, uploadAvatar, saveAvatarStyle } from '../services/communityApi'

vi.mock('../services/communityApi', () => ({ removeAvatar: vi.fn(), uploadAvatar: vi.fn(), saveAvatarStyle: vi.fn() }))
const member = { user_id: 1, display_name: 'Alice', handle: 'alice_dive', bio: 'Dive together', avatar_url: '/photo?v=1', avatar_hud: 'reticle' as const }

it('persists a HUD choice and keeps the old selection on failure', async () => {
  const onChange = vi.fn()
  vi.mocked(saveAvatarStyle).mockResolvedValueOnce({ ...member, avatar_hud: 'depth' }).mockRejectedValueOnce(new Error('offline'))
  render(<AvatarManager member={member} onChange={onChange} />)
  fireEvent.click(screen.getByRole('button', { name: 'Depth' }))
  await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ avatar_hud: 'depth' })))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Depth' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Orbit' }))
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Depth' })).toHaveAttribute('aria-pressed', 'true')
})

it('removes a photo while retaining profile fields and rejects an oversized file before upload', async () => {
  const onChange = vi.fn()
  vi.mocked(removeAvatar).mockResolvedValue(undefined)
  render(<AvatarManager member={member} onChange={onChange} />)
  fireEvent.click(screen.getByRole('button', { name: /Remove photo/ }))
  await waitFor(() => expect(onChange).toHaveBeenCalledWith({ ...member, avatar_url: null }))
  await waitFor(() => expect(screen.getByLabelText('Profile photo')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Profile photo'), { target: { files: [new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' })] } })
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(uploadAvatar).not.toHaveBeenCalled()
})

it('ignores a pending photo response after switching accounts', async () => {
  let finish!: (value: typeof member) => void
  vi.mocked(uploadAvatar).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const onChange = vi.fn()
  const { rerender } = render(<AvatarManager member={member} onChange={onChange} />)
  fireEvent.change(screen.getByLabelText('Profile photo'), { target: { files: [new File(['photo'], 'new.png', { type: 'image/png' })] } })
  await waitFor(() => expect(screen.getByLabelText('Profile photo')).toBeDisabled())
  rerender(<AvatarManager member={{ ...member, user_id: 2, display_name: 'Bob', avatar_url: null }} onChange={onChange} />)
  finish({ ...member, avatar_url: '/photo?v=2' })
  await waitFor(() => expect(screen.getByLabelText('Profile photo')).toBeEnabled())
  expect(onChange).not.toHaveBeenCalled()
})
