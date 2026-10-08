import { StrictMode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import SharedDive from './SharedDive';
import { api } from '../services/api';
vi.mock('../services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const video = { dive_id: 42, dive_code: '101B', height: '3m', guest_id: 8, guest_name: 'Neville Londubat', video_url: '/api/v1/shared-dives/7/video' };
const token = 's'.repeat(43);
const ownComment = { id: 1, author: video.guest_name, guest_id: 8, user_id: null, body: 'Belle entrée !', created_at: '2026-10-05T09:00:00Z' };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.post).mockResolvedValue({ data: video });
  vi.mocked(api.get).mockImplementation(async url => ({ data: String(url).endsWith('/social') ? { liked: false, like_count: 2, comment_count: 2 } : { items: [ownComment, { ...ownComment, id: 2, guest_id: 9, author: 'Dobby', body: 'Bravo !' }], next_before: null } }));
});
function open(path = `/share/7#${token}`) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/share/:shareId" element={<SharedDive />} /></Routes></MemoryRouter>);
}
it('opens without an account and restricts social requests to the shared video', async () => {
  const { container } = open();
  await screen.findByText('Neville Londubat');
  expect(api.post).toHaveBeenCalledWith('/api/v1/shared-dives/7/visit', null, { headers: { 'X-Dive-Share': token } });
  expect(container.querySelector('video')).toHaveAttribute('src', video.video_url);
  expect(screen.queryByText('Library')).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Like dive' })).not.toBeDisabled());
  vi.mocked(api.put).mockResolvedValue({ data: { liked: true, like_count: 3, comment_count: 2 } });
  fireEvent.click(screen.getByRole('button', { name: 'Like dive' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/v1/shared-dives/7/like', { liked: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Comments' }));
  await screen.findByText('Belle entrée !');
  expect(screen.getByRole('button', { name: 'Delete comment by Neville Londubat' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete comment by Dobby' })).not.toBeInTheDocument();
  vi.mocked(api.post).mockResolvedValue({ data: { ...ownComment, id: 3, body: 'Super !' } });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Super !' } });
  fireEvent.click(screen.getByRole('button', { name: 'Post comment' }));
  await screen.findByText('Super !');
  expect(api.post).toHaveBeenLastCalledWith('/api/v1/shared-dives/7/comments', { body: 'Super !', mentions: [] });
});
it('shows an unavailable link without requesting workspace data', async () => {
  vi.mocked(api.post).mockRejectedValue(new Error('revoked'));
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent('unavailable');
  expect(api.get).not.toHaveBeenCalled();
});
it('rejects missing link secrets before making a request', async () => {
  open('/share/7');
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid');
  expect(api.post).not.toHaveBeenCalled();
});

it('exchanges the link once when React replays the initial effect', async () => {
  let resolve!: (value: { data: typeof video }) => void;
  vi.mocked(api.post).mockReturnValue(new Promise(done => { resolve = done; }));
  render(<StrictMode><MemoryRouter initialEntries={[`/share/7#${token}`]}><Routes><Route path="/share/:shareId" element={<SharedDive />} /></Routes></MemoryRouter></StrictMode>);
  expect(api.post).toHaveBeenCalledTimes(1);
  resolve({ data: video });
  await screen.findByText('Neville Londubat');
});
