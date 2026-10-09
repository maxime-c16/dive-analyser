import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACHIEVEMENTS_CHECK_EVENT, installAchievementProbe } from './achievementsApi'

describe('installAchievementProbe', () => {
  const original = window.fetch
  const checks = vi.fn()

  beforeEach(() => {
    vi.useFakeTimers()
    window.fetch = vi.fn(async () => ({ ok: true, status: 200 }) as Response) as typeof fetch
    window.addEventListener(ACHIEVEMENTS_CHECK_EVENT, checks)
    installAchievementProbe()
  })
  afterEach(() => {
    window.removeEventListener(ACHIEVEMENTS_CHECK_EVENT, checks)
    checks.mockClear()
    vi.useRealTimers()
  })

  it('asks for one debounced check after successful writes only', async () => {
    await window.fetch('/api/v1/dives/3/comments', { method: 'POST' })
    await window.fetch('/api/v1/dives/3/like', { method: 'PUT' })
    await window.fetch('/api/v1/dives', { method: 'GET' })
    await window.fetch('/api/v1/auth/login', { method: 'POST' })
    await window.fetch('/api/v1/messages/conversations/2/receipts', { method: 'POST' })
    await window.fetch('/api/v1/users/me/achievements/seen', { method: 'POST' })
    await window.fetch('/elsewhere', { method: 'POST' })
    expect(checks).not.toHaveBeenCalled()
    vi.advanceTimersByTime(500)
    expect(checks).toHaveBeenCalledTimes(1)
  })

  it('does nothing for failed writes and installs only once', async () => {
    const wrapped = window.fetch
    installAchievementProbe()
    expect(window.fetch).toBe(wrapped)
    expect(original).not.toBe(wrapped)
  })
})
