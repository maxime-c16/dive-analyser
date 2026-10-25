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
it('keeps a matching card mounted and clickable while server filters refresh', async () => {
  data();
  page();
  const original = await screen.findByRole('button', { name: /^Open 103B attempt/ });
  let finish!: (result: unknown) => void;
  const refresh = new Promise(resolve => { finish = resolve });
  vi.mocked(api.get).mockImplementation((url) => url === '/api/v1/dives/library' ? refresh as any : Promise.resolve({ data: [] }));
  const { fireEvent } = await import('@testing-library/react');
  fireEvent.change(screen.getByRole('textbox', { name: 'Search dives' }), { target: { value: '103B' } });
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/v1/dives/library', expect.objectContaining({ params: expect.objectContaining({ code_prefix: '103B' }) })));
  expect(screen.getByRole('button', { name: /^Open 103B attempt/ })).toBe(original);
  fireEvent.click(original);
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  finish({ data: { items: [attempt], next_cursor: null } });
})

it('keeps a direct-link clip open when the stale saved Library refreshes after resolving it', async () => {
  data();
  render(<MemoryRouter initialEntries={['/dives?scope=all']}><Dives /></MemoryRouter>).unmount();
  await new Promise(resolve => setTimeout(resolve, 20));
  const now = Date.now();
  vi.spyOn(Date, 'now').mockReturnValue(now + 60_001);
  const shared = { ...attempt, id: 99, dive_code: '305C', diver_id: 2, dive_datetime: '2025-01-05T10:00:00' };
  let finish!: (result: unknown) => void;
  const refresh = new Promise(resolve => { finish = resolve });
  vi.mocked(api.get).mockImplementation((url: string) => url === '/api/v1/dives/library' ? refresh as any
    : Promise.resolve({ data: url === '/api/v1/dives/99' ? shared : [] }));
  render(<MemoryRouter initialEntries={['/dives?clip=99&scope=all']}><Dives /></MemoryRouter>);
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  finish({ data: { items: [attempt], next_cursor: null } });
  await new Promise(resolve => setTimeout(resolve, 50));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
