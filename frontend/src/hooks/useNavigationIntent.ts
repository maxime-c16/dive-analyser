import { useEffect, useRef } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { warmNavigationData } from '../services/navigationData';

export function canPrefetch() {
  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;
  return navigator.onLine !== false && !connection?.saveData &&
    !['slow-2g', '2g'].includes(connection?.effectiveType ?? '');
}

export function useNavigationIntent(path: string, load?: () => Promise<unknown>) {
  const { user } = useAuth();
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const cancel = () => { clearTimeout(timer.current); };
  useEffect(() => cancel, [path]);
  const warm = () => {
    cancel();
    if (!user || !canPrefetch() || window.location.pathname === path) return;
    void load?.().catch(() => {});
    warmNavigationData(path, user.divers?.length ? 'self' : 'all');
  };
  const schedule = () => { cancel(); timer.current = setTimeout(warm, 120); };
  return {
    onMouseEnter: schedule,
    onMouseLeave: cancel,
    onFocus: schedule,
    onBlur: cancel,
    onPointerDown: warm,
  };
}
