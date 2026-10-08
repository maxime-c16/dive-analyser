import { fireEvent, render } from '@testing-library/react'
import { expect, it } from 'vitest'
import MemberAvatar from './MemberAvatar'

it('falls back on a broken photo and retries a replacement URL', () => {
  const { container, rerender } = render(<MemberAvatar member={{ display_name: 'Maxime Cauchy', avatar_url: '/photo?v=1', avatar_hud: 'depth' }} />)
  expect(container.querySelector('[data-hud="depth"]')).toBeTruthy()
  fireEvent.error(container.querySelector('img')!)
  expect(container.textContent).toBe('MC')
  rerender(<MemberAvatar member={{ display_name: 'Maxime Cauchy', avatar_url: '/photo?v=2', avatar_hud: 'orbit' }} />)
  expect(container.querySelector('img')).toHaveAttribute('src', '/photo?v=2')
  expect(container.querySelector('[data-hud="orbit"]')).toBeTruthy()
})
