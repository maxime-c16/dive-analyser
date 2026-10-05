import { fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useNavigationIntent } from './useNavigationIntent';
import { warmNavigationData } from '../services/navigationData';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { divers: [] } }) }));
vi.mock('../services/navigationData', () => ({ warmNavigationData: vi.fn() }));
const load = vi.fn().mockResolvedValue({});
function Link() { return <a href="/analytics" {...useNavigationIntent('/analytics', load)}>Analytics</a>; }
beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); load.mockResolvedValue({}); });
afterEach(() => { vi.useRealTimers(); Object.defineProperty(navigator, 'connection', { configurable: true, value: undefined }); });

describe('navigation intent', () => {
  it('ignores passing hover and warms a sustained hover', () => {
    const { getByText } = render(<Link />);
    fireEvent.mouseEnter(getByText('Analytics'));
    vi.advanceTimersByTime(100);
    fireEvent.mouseLeave(getByText('Analytics'));
    vi.advanceTimersByTime(200);
    expect(load).not.toHaveBeenCalled();
    fireEvent.mouseEnter(getByText('Analytics'));
    vi.advanceTimersByTime(120);
    expect(load).toHaveBeenCalledTimes(1);
    expect(warmNavigationData).toHaveBeenCalledWith('/analytics', 'all');
  });
  it('supports keyboard focus and immediate touch intent', () => {
    const { getByText } = render(<Link />);
    fireEvent.focus(getByText('Analytics'));
    vi.advanceTimersByTime(120);
    expect(load).toHaveBeenCalledTimes(1);
    fireEvent.pointerDown(getByText('Analytics'));
    expect(load).toHaveBeenCalledTimes(2);
  });
  it('does not prefetch with data saver or a slow connection', () => {
    const { getByText } = render(<Link />);
    for (const connection of [{ saveData: true }, { effectiveType: '2g' }]) {
      Object.defineProperty(navigator, 'connection', { configurable: true, value: connection });
      fireEvent.pointerDown(getByText('Analytics'));
    }
    expect(load).not.toHaveBeenCalled();
    expect(warmNavigationData).not.toHaveBeenCalled();
  });
  it('cancels scheduled work on unmount', () => {
    const { getByText, unmount } = render(<Link />);
    fireEvent.mouseEnter(getByText('Analytics'));
    unmount();
    vi.advanceTimersByTime(200);
    expect(load).not.toHaveBeenCalled();
  });
});
