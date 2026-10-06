import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import FederateDiveControl from './FederateDiveControl'
import { api } from '../../services/api'
import type { Attempt } from '../../utils/attemptPresentation'

vi.mock('../../services/api', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }))

const attempt: Attempt = {
  id: 7,
  dive_code: '101B',
  performance: 'G',
  performance_numeric: 3,
  height: '3m',
  dive_datetime: '2026-10-04T10:00:00',
  session_id: 1,
  is_lineup: false,
  is_sync: false,
  platform_type: 'springboard',
  official_dd: 1.5,
  visibility: 'public',
  can_manage: true,
  federate_enabled: false,
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('FederateDiveControl (Option 1)', () => {
  it('shows the no-history warning and per-dive opt-in state', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        enabled_global: true,
        federate_enabled: false,
        visibility: 'public',
        eligible: false,
        reason: 'per_dive_opt_in_off',
        preview: { text: '101B · 3m', includes_video: false },
      },
    } as never)
    render(<FederateDiveControl attempt={attempt} onUpdate={vi.fn()} />)
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/v1/dives/7/fediverse'))
    expect(screen.getByText(/never publishes past dives/i)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /allow fediverse/i })).toHaveAttribute('aria-checked', 'false')
  })

  it('blocks private dives without hover', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        enabled_global: true,
        federate_enabled: false,
        visibility: 'private',
        eligible: false,
        reason: 'dive_is_private',
        preview: { text: '', includes_video: false },
      },
    } as never)
    render(<FederateDiveControl attempt={{ ...attempt, visibility: 'private' }} onUpdate={vi.fn()} />)
    await waitFor(() => expect(screen.getByText(/only public dives can be federated/i)).toBeInTheDocument())
    expect(screen.getByRole('switch', { name: /allow fediverse/i })).toBeDisabled()
  })

  it('copies poster+caption text when eligible and never mentions video links', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        enabled_global: true,
        federate_enabled: true,
        visibility: 'public',
        eligible: true,
        reason: 'eligible',
        preview: { text: '101B · 3m\nNice dive', includes_video: false },
      },
    } as never)
    vi.mocked(api.post).mockResolvedValue({ data: { text: '101B · 3m\nNice dive' } } as never)
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<FederateDiveControl attempt={{ ...attempt, federate_enabled: true }} onUpdate={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /copy cross-post/i })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /copy cross-post/i }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('101B · 3m\nNice dive'))
    expect(screen.getByText(/do not paste a share link/i)).toBeInTheDocument()
  })
})
