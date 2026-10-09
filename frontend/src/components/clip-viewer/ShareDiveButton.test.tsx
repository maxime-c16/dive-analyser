import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ShareDiveButton from './ShareDiveButton';
import { searchMembers } from '../../services/communityApi';
import { sendMessage, startConversation } from '../../services/messagesApi';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../../services/api';
vi.mock('../../services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../../services/communityApi', () => ({ searchMembers: vi.fn() }));
vi.mock('../../services/messagesApi', () => ({ sendMessage: vi.fn(), startConversation: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.get).mockResolvedValue({ data: { active_count: 0 } });
  vi.stubGlobal('ClipboardItem', undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
afterEach(() => { vi.useRealTimers(); });
it('creates and copies one link despite repeated clicks while saving', async () => {
  let resolve!: (value: { data: { path: string } }) => void;
  vi.mocked(api.post).mockReturnValue(new Promise(done => { resolve = done; }));
  render(<ShareDiveButton id={42} />);
  const button = screen.getByRole('button', { name: 'Share dive' });
  fireEvent.click(button);
  fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
  fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
  expect(api.post).toHaveBeenCalledTimes(1);
  resolve({ data: { path: '/share/7#secret' } });
  await screen.findByText('Link copied');
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`${location.origin}/share/7#secret`);
  fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(2));
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('keeps the committed link when clipboard permission fails and allows revocation', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: { path: '/share/7#secret' } });
  vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error('denied'));
  vi.mocked(api.delete).mockResolvedValue({});
  render(<ShareDiveButton id={42} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
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
  fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
  expect(write).toHaveBeenCalledTimes(1);
  resolve({ data: { path: '/share/7#secret' } });
  await screen.findByText('Link copied');
});

it('revokes existing links after closing and reopening without creating another capability', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: { path: '/share/7#secret' } });
  vi.mocked(api.delete).mockResolvedValue({});
  const first = render(<ShareDiveButton id={42} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
  await screen.findByText('Link copied');
  first.unmount();
  vi.mocked(api.get).mockResolvedValue({ data: { active_count: 1 } });
  render(<ShareDiveButton id={42} />);
  await act(async () => {});
  expect(screen.queryByRole('dialog', { name: 'Video sharing' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  fireEvent.click(screen.getByRole('button', { name: 'Revoke shared links' }));
  await screen.findByText('Shared links revoked');
  expect(api.delete).toHaveBeenCalledWith('/api/v1/dives/42/shares');
  expect(api.post).toHaveBeenCalledTimes(1);
});


it('dismisses copied-link feedback after three seconds without losing link management', async () => {
  vi.useFakeTimers();
  vi.mocked(api.post).mockResolvedValue({ data: { path: '/share/7#secret' } });
  render(<ShareDiveButton id={42} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy link' })));
  expect(screen.getByText('Link copied')).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(3000));
  expect(screen.queryByText('Link copied')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Revoke shared links' })).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(3000));
  expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument();
});

it('keeps manual-copy feedback until dismissed and returns focus to Share', async () => {
  vi.useFakeTimers();
  vi.mocked(api.post).mockResolvedValue({ data: { path: '/share/7#secret' } });
  vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error('denied'));
  render(<ShareDiveButton id={42} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy link' })));
  act(() => vi.advanceTimersByTime(10000));
  expect(screen.getByRole('textbox', { name: 'Share link' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss sharing notification' }));
  expect(screen.queryByRole('dialog', { name: 'Video sharing' })).not.toBeInTheDocument();
  await act(async () => {});
  expect(screen.getByRole('button', { name: 'Share dive' })).toHaveFocus();
});

const member = { user_id: 7, display_name: 'Camille', handle: 'camille', bio: '', avatar_url: null, avatar_hud: 'reticle' as const };
it('opens one menu without creating a link and sends the clip in a DM', async () => {
  vi.mocked(searchMembers).mockResolvedValue({ items: [member], next_after: null });
  vi.mocked(startConversation).mockResolvedValue({ id: 12 });
  vi.mocked(sendMessage).mockResolvedValue({} as never);
  render(<MemoryRouter><ShareDiveButton id={42} allowDm /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  expect(api.post).not.toHaveBeenCalled();
  const dialog = screen.getByRole('dialog', { name: 'Video sharing' });
  expect(dialog).toContainElement(screen.getByRole('button', { name: 'Copy link' }));
  fireEvent.click(await screen.findByRole('button', { name: /Camille/ }));
  await screen.findByText('Dive sent.');
  expect(startConversation).toHaveBeenCalledWith(7);
  expect(sendMessage).toHaveBeenCalledWith(12, { dive_id: 42, client_id: expect.any(String) });
  expect(screen.getByRole('link', { name: 'Open conversation' })).toHaveAttribute('href', '/messages/12');
  expect(api.post).not.toHaveBeenCalled();
});
it('keeps DM available without granting link management to a viewer', async () => {
  vi.mocked(searchMembers).mockResolvedValue({ items: [member], next_after: null });
  render(<MemoryRouter><ShareDiveButton id={42} allowLink={false} allowDm /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  expect(screen.queryByRole('button', { name: 'Copy link' })).not.toBeInTheDocument();
  expect(api.get).not.toHaveBeenCalled();
  expect(await screen.findByRole('button', { name: /Camille/ })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await act(async () => {});
  expect(screen.getByRole('button', { name: 'Share dive' })).toHaveFocus();
});

it('retries a failed DM with the same client key and blocks repeated sends', async () => {
  vi.mocked(searchMembers).mockResolvedValue({ items: [member], next_after: null });
  vi.mocked(startConversation).mockResolvedValue({ id: 12 });
  let reject!: (error: Error) => void;
  vi.mocked(sendMessage).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  render(<MemoryRouter><ShareDiveButton id={42} allowDm /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Share dive' }));
  const recipient = await screen.findByRole('button', { name: /Camille/ });
  fireEvent.click(recipient); fireEvent.click(recipient);
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  const firstKey = vi.mocked(sendMessage).mock.calls[0][1].client_id;
  await act(async () => reject(new Error('network failed')));
  expect(screen.getByRole('alert')).toBeInTheDocument();
  vi.mocked(sendMessage).mockResolvedValue({} as never);
  fireEvent.click(recipient);
  await screen.findByText('Dive sent.');
  expect(sendMessage).toHaveBeenLastCalledWith(12, { dive_id: 42, client_id: firstKey });
});
