import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import XrayOverlay, { xrayRow } from './XrayOverlay'

const auth = vi.hoisted(() => ({ user: { is_admin: false } as { is_admin: boolean } | null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))

describe('Xray privacy and access', () => {
  it('reduces signed URLs, ids and arbitrary server descriptions to categories', () => {
    const row = xrayRow({ name: 'https://example.test/api/v1/media/cache/123/play?signature=secret',
      startTime: 1, duration: 20, serverTiming: [
        { name: 'db', duration: 4, description: 'private-media-id' },
        { name: 'private-media-id', duration: 5 },
      ] } as unknown as PerformanceResourceTiming, 'https://example.test')
    expect(row).toEqual({ label: 'Media', start: 1, duration: 20, server: 'db 4.0 ms' })
    expect(xrayRow({ name: 'https://b2.test/signed-secret', duration: 1, startTime: 0 } as unknown as PerformanceResourceTiming,
      'https://example.test').label).toBe('External resource')
  })
  it.each([null, { is_admin: false }])('does not mount diagnostic observers for nonadmins', user => {
    auth.user = user
    render(<MemoryRouter initialEntries={['/dives?xray=1']}><XrayOverlay /></MemoryRouter>)
    expect(screen.queryByLabelText('Xray')).not.toBeInTheDocument()
  })
  it('requires an explicit query even for admins', () => {
    auth.user = { is_admin: true }
    render(<MemoryRouter initialEntries={['/dives']}><XrayOverlay /></MemoryRouter>)
    expect(screen.queryByLabelText('Xray')).not.toBeInTheDocument()
  })
})

it('shows only anonymous timings when explicitly enabled by an admin', () => {
  auth.user = { is_admin: true }
  const descriptor = Object.getOwnPropertyDescriptor(performance, 'getEntriesByType')
  Object.defineProperty(performance, 'getEntriesByType', { configurable: true, value: () => [
    { name: window.location.origin + '/api/v1/media/cache/987/play?token=private', startTime: 10, duration: 5,
      serverTiming: [{ name: 'app', duration: 3 }] },
  ] })
  vi.stubGlobal('PerformanceObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
  const view = render(<MemoryRouter initialEntries={['/dives?xray=1']}><XrayOverlay /></MemoryRouter>)
  try {
    expect(screen.getByLabelText('Xray')).toHaveTextContent('Media')
    expect(screen.getByLabelText('Xray')).toHaveTextContent('app 3.0 ms')
    expect(screen.getByLabelText('Xray')).not.toHaveTextContent('987')
    expect(screen.getByLabelText('Xray')).not.toHaveTextContent('private')
  } finally {
    view.unmount()
    vi.unstubAllGlobals()
    if (descriptor) Object.defineProperty(performance, 'getEntriesByType', descriptor)
    else Reflect.deleteProperty(performance, 'getEntriesByType')
  }
})
