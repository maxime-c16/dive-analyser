import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import ShareDiveButton from './ShareDiveButton';
import { api } from '../../services/api';
vi.mock('../../services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.get).mockResolvedValue({ data: { active_count: 0 } });
  vi.stubGlobal('ClipboardItem', undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
it('creates and copies one link despite repeated clicks while saving', async () => {
  let resolve!: (value: { data: { path: string } }) => void;
  vi.mocked(api.post).mockReturnValue(new Promise(done => { resolve = done; }));
  render(<ShareDiveButton id={42} />);
  const button = screen.getByRole('button', { name: 'Share dive' });
  fireEvent.click(button); fireEvent.click(button);
  expect(api.post).toHaveBeenCalledTimes(1);
  resolve({ data: { path: '/share/7#secret' } });
  await screen.findByText('Link copied');
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`${location.origin}/share/7#secret`);
  fireEvent.click(button);
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(2));
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('keeps the committed link when clipboard permission fails and allows revocation', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: { path: '/share/7#secret' } });
  vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error('denied'));
  vi.mocked(api.delete).mockResolvedValue({});
  render(<ShareDiveButton id={42} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  expect(await screen.findByRole('textbox', { name: 'Share link' })).toHaveValue(`${location.origin}/share/7#secret`);
  fireEvent.click(screen.getByRole('button', { name: 'Revoke shared links' }));
  await screen.findByText('Shared links revoked');
  expect(api.delete).toHaveBeenCalledWith('/api/v1/dives/42/shares');
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
});
it('requests clipboard access before the creation request finishes', async () => {
  let resolve!: (value: { data: { path: string } }) => void;
  vi.mocked(api.post).mockReturnValue(new Promise(done => { resolve = done; }));
  let text!: Promise<Blob>;
  vi.stubGlobal('ClipboardItem', class { constructor(value: { 'text/plain': Promise<Blob> }) { text = value['text/plain']; } });
  const write = vi.fn().mockImplementation(async () => { await text; });
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { write } });
  render(<ShareDiveButton id={42} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  expect(write).toHaveBeenCalledTimes(1);
  resolve({ data: { path: '/share/7#secret' } });
  await screen.findByText('Link copied');
});

it('revokes existing links after closing and reopening without creating another capability', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: { path: '/share/7#secret' } });
  vi.mocked(api.delete).mockResolvedValue({});
  const first = render(<ShareDiveButton id={42} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  await screen.findByText('Link copied');
  first.unmount();
  vi.mocked(api.get).mockResolvedValue({ data: { active_count: 1 } });
  render(<ShareDiveButton id={42} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Revoke shared links' }));
  await screen.findByText('Shared links revoked');
  expect(api.delete).toHaveBeenCalledWith('/api/v1/dives/42/shares');
  expect(api.post).toHaveBeenCalledTimes(1);
});
