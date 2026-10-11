import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import Dives from './Dives';
import { api } from '../services/api';
import { clearLibraryCache } from '../services/libraryCache';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: {
  user_id: 1, role: 'owner', is_admin: true, divers: [{ diver_id: 1, access_kind: 'OWNER' }],
} }) }));
vi.mock('../services/api', () => ({ api: { get: vi.fn() } }));
afterEach(() => { clearLibraryCache(); vi.useRealTimers(); });
function page() { return render(<MemoryRouter initialEntries={['/dives']}><Dives /></MemoryRouter>); }
const attempt = { id: 1, dive_code: '103B', diver_id: 1, performance: 'G', height: '1m', dive_datetime: '2026-10-05T10:00:00', video_uuid: null, is_sync: false, position: 'B' };
function data() {
  vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/api/v1/dives/library' ? { items: [attempt], next_cursor: null } : [] }));
}
it('renders a cached Library immediately on return without any list or diver request', async () => {
  data();
  const first = page();
  await screen.findAllByText('103B');
  first.unmount();
  vi.mocked(api.get).mockClear();
  page();
  expect(screen.getAllByText('103B').length).toBeGreaterThan(0);
  expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
  expect(api.get).not.toHaveBeenCalled();
});
it('keeps saved dives visible and announces a failed background refresh', async () => {
  data();
  const first = page();
  await screen.findAllByText('103B');
  first.unmount();
  const now = Date.now();
  vi.spyOn(Date, 'now').mockReturnValue(now + 60_001);
  vi.mocked(api.get).mockRejectedValue(new Error('offline'));
  page();
  expect(screen.getAllByText('103B').length).toBeGreaterThan(0);
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Showing saved dives'));
  expect(screen.getAllByText('103B').length).toBeGreaterThan(0);
});

it('loads older server pages without duplicating rows', async () => {
  const older = { ...attempt, id: 2, dive_code: '104B' };
  vi.mocked(api.get).mockImplementation(async (url, config) => ({
    data: url === '/api/v1/dives/library'
      ? config?.params?.cursor ? { items: [attempt, older], next_cursor: null }
        : { items: [attempt], next_cursor: 'older-page' }
      : [],
  }));
  page();
  const button = await screen.findByRole('button', { name: 'Load more dives' });
  const { fireEvent } = await import('@testing-library/react');
  fireEvent.click(button);
  expect(await screen.findAllByText('104B')).not.toHaveLength(0);
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Load more dives' })).toBeNull());
  expect(vi.mocked(api.get).mock.calls.some(([url, config]) => url === '/api/v1/dives/library' && config?.params?.cursor === 'older-page')).toBe(true);
});
