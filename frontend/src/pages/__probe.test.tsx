import React from 'react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { user_id: 1, role: 'owner', is_admin: true, divers: [{ diver_id: 1, access_kind: 'OWNER' }] } }) }))
vi.mock('../services/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../services/mediaApi', () => ({ getMediaStatus: vi.fn().mockResolvedValue({ poster_url: null, playback_url: null }) }))
vi.mock('../components/DiveVideoPlayer', () => ({ default: ({ videoUuid }: { videoUuid: string }) => <div>player {videoUuid}</div> }))
import { api } from '../services/api'
import Dives from './Dives'

const dive = (id: number) => ({ id, dive_code: '103B', diver_id: 1, performance: 'G', performance_numeric: 3, height: '1m', dive_datetime: `2026-07-${String(id % 28 + 1).padStart(2, '0')}T10:00:00`, session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', position: 'B', official_dd: 1.5, raw_caption: null, video_uuid: `uuid-${id}` })

const countCards = () => document.querySelectorAll('button[data-attempt-id].group').length

it('probe phases dom counts', async () => {
  const calls: string[] = []
  vi.mocked(api.get).mockImplementation(async (url: string, config?: { params?: { cursor?: string } }) => {
    calls.push(`${url}|${config?.params?.cursor ?? ''}`)
    if (url === '/api/v1/divers') return { data: [] }
    return { data: config?.params?.cursor
      ? { items: Array.from({ length: 60 }, (_, i) => dive(61 + i)), next_cursor: null }
      : { items: Array.from({ length: 60 }, (_, i) => dive(i + 1)), next_cursor: 'p2' } }
  })
  window.history.replaceState(null, '', '/dives')
  render(<BrowserRouter><Dives /></BrowserRouter>)
  await waitFor(() => expect(countCards()).toBe(48))
  console.log('AFTER_LOAD', countCards())
  await userEvent.click(await screen.findByRole('button', { name: /more attempts/ }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Load more dives' })).not.toBeNull())
  console.log('AFTER_SHOWMORE', countCards())
  await userEvent.click(screen.getByRole('button', { name: 'Load more dives' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Load more dives' })).toBeNull())
  console.log('AFTER_LOADMORE', countCards(), 'QDOM1', document.querySelectorAll('button[data-attempt-id="1"].group').length)
  expect(true).toBe(true)
}, 30000)
