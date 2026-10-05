import { api } from './api';
import { takeIntentData, warmIntentData } from './intentCache';

type Params = Record<string, string | number>;
function key(url: string, params?: Params) {
  return JSON.stringify([url, Object.entries(params ?? {}).sort(([a], [b]) => a.localeCompare(b))]);
}

export function getNavigationData(url: string, params?: Params) {
  return takeIntentData(key(url, params), () => api.get(url, params ? { params } : undefined));
}

export function warmNavigationData(path: string, diverScope: 'self' | 'all') {
  const urls = path === '/analytics' ? [
    '/api/v1/analytics/monthly', '/api/v1/analytics/by-height',
    '/api/v1/analytics/by-direction', '/api/v1/analytics/trending?limit=10',
  ] : path === '/dashboard' ? [
    '/api/v1/analytics/overall', '/api/v1/analytics/monthly',
    '/api/v1/analytics/by-height', '/api/v1/analytics/by-direction',
    '/api/v1/sessions?limit=100',
  ] : [];
  for (const url of urls) warmIntentData(key(url), () => api.get(url));
  if (path === '/sessions') {
    const url = '/api/v1/sessions';
    const params = { limit: 50, diver_scope: diverScope };
    warmIntentData(key(url, params), () => api.get(url, { params }));
  }
}
