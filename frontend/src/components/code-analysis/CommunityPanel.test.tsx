import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import CommunityPanel, { type CommunityRow } from './CommunityPanel'
import type { CommunityMember } from '../../services/codeCommunityApi'

const me: CommunityRow = { key: 'me', name: 'Maxime', avatar: { display_name: 'Maxime' }, count: 40, median: 4.5, q1: 2, q3: 7, series: [4, 4.5, 5] }
const member = (diver_id: number, name: string, median: number, account: CommunityMember['account'] = null): CommunityMember => ({
  diver_id, name, account, attempt_count: 12, scored_count: 12, median, q1: median - 1, q3: median + 1,
  last_attempt_at: '2026-10-01T10:00:00', series: [median - 1, median, median],
  best: { id: diver_id * 100, dive_code: '101C', performance: 'P', height: '1m', dive_datetime: '2026-05-21T10:00:00', session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', position: 'C', video_uuid: null } as never,
})
const members = [member(7, 'FANNY', 6, { user_id: 15, display_name: 'Fouiny', avatar_url: null }), member(9, 'LEO', 3.5)]

function setWide(wide: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({ matches: wide && query.includes('700'), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() })) as never
}
afterEach(() => { delete (window as { matchMedia?: unknown }).matchMedia })

function renderPanel(props: Partial<React.ComponentProps<typeof CommunityPanel>> = {}) {
  const onWatch = vi.fn(), onAnalysis = vi.fn()
  render(<MemoryRouter><CommunityPanel me={me} members={members} hidden={2} height="" onWatch={onWatch} onAnalysis={onAnalysis} {...props} /></MemoryRouter>)
  return { onWatch, onAnalysis }
}

it('ranks you among the divers and turns a tapped row into the comparison on phones', async () => {
  setWide(false)
  const { onWatch, onAnalysis } = renderPanel()
  const rows = screen.getAllByText(/^(Fouiny|You|Leo)$/).map(node => node.textContent)
  expect(rows).toEqual(['Fouiny', 'You', 'Leo'])
  expect(screen.getByText('+2 divers with fewer than 3 graded attempts')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /Compare with Fouiny/ }))
  expect(screen.queryByRole('button', { name: /Compare with Leo/ })).toBeNull()
  expect(screen.getByText('vs 4.5 for you')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Profile' })).toHaveAttribute('href', '/users/15')
  await userEvent.click(screen.getByRole('button', { name: /Watch/ }))
  expect(onWatch).toHaveBeenCalledWith(members[0], 700)
  await userEvent.click(screen.getByRole('button', { name: 'Full analysis' }))
  expect(onAnalysis).toHaveBeenCalledWith(members[0])

  await userEvent.click(screen.getByRole('button', { name: 'Ranking' }))
  expect(screen.getByRole('button', { name: /Compare with Leo/ })).toBeInTheDocument()
})

it('shows the ranking and the comparison side by side on wide screens, starting on the diver just above you', async () => {
  setWide(true)
  renderPanel()
  expect(screen.queryByRole('button', { name: 'Ranking' })).toBeNull()
  expect(screen.getByRole('button', { name: /Compare with Fouiny/ })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: /Compare with Leo/ }))
  expect(screen.getByRole('button', { name: /Compare with Leo/ })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByRole('link', { name: 'Profile' })).toBeNull()
})

it('labels the height the comparison is restricted to', () => {
  setWide(false)
  renderPanel({ height: '3m' })
  expect(screen.getByText(/^3m · median/)).toBeInTheDocument()
})
