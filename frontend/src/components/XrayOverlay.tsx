import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export type XrayRow = { label: string; start: number; duration: number; server: string }
// Keep only categories: never retain a URL, query string, media id or server description.
export function xrayRow(entry: PerformanceResourceTiming, origin: string): XrayRow {
  let label = 'External resource'
  try {
    const url = new URL(entry.name)
    if (url.origin === origin) {
      const path = url.pathname
      label = path.includes('/auth/me') ? 'Identity' : path.includes('/dives/library') ? 'Library'
        : path.includes('/media/') ? 'Media' : path.startsWith('/api/') ? 'API'
        : entry.initiatorType === 'img' ? 'Image' : 'App resource'
    }
  } catch { /* Invalid URLs remain anonymous. */ }
  return { label, start: entry.startTime, duration: entry.duration,
    server: (entry.serverTiming || []).filter(t => ['auth', 'db', 'app'].includes(t.name))
      .map(t => `${t.name} ${t.duration.toFixed(1)} ms`).join(' · ') }
}

function ActiveXray() {
  const location = useLocation()
  const boundary = useRef({ key: location.key, started: 0 })
  if (boundary.current.key !== location.key) {
    boundary.current = { key: location.key, started: performance.now() }
  }
  const [rows, setRows] = useState<XrayRow[]>([])
  const [lag, setLag] = useState<string>('')
  useEffect(() => {
    let active = true
    // Include the initial navigation waterfall; reset on subsequent SPA navigations.
    const cutoff = boundary.current.started
    const update = () => setRows((performance.getEntriesByType('resource') as PerformanceResourceTiming[])
      .filter(e => e.startTime >= cutoff && !e.name.includes('/auth/xray'))
      .slice(-80).map(e => xrayRow(e, window.location.origin)))
    update()
    const observer = new PerformanceObserver(update)
    observer.observe({ type: 'resource', buffered: true })
    const poll = async () => {
      try {
        const response = await fetch('/api/v1/auth/xray', { credentials: 'same-origin', cache: 'no-store' })
        if (!response.ok) return
        const data = await response.json()
        if (active) setLag(`Loop p99 ${data.event_loop.p99_ms} ms · max ${data.event_loop.max_ms} ms · ≥100 ms ${data.event_loop.over_100ms_total}`)
      } catch { /* Diagnostics must never interrupt the screen. */ }
    }
    void poll()
    const timer = window.setInterval(poll, 10000)
    return () => { active = false; observer.disconnect(); window.clearInterval(timer) }
  }, [location.key])
  const base = rows.length ? Math.min(...rows.map(r => r.start)) : 0
  const end = Math.max(...rows.map(r => r.start + r.duration), 1)
  const span = Math.max(1, end - base)
  return <aside aria-label="Xray" style={{ position: 'fixed', bottom: 12, right: 12, zIndex: 10000,
    width: 'min(620px, 95vw)', maxHeight: '45vh', overflow: 'auto', background: '#111827',
    color: '#f9fafb', padding: 12, border: '1px solid #64748b', borderRadius: 8, font: '12px monospace' }}>
    <details open><summary>Xray · {rows.length} requests</summary><p>{lag}</p>
      {rows.map((row, i) => <div key={i} style={{ marginBottom: 8 }}>
        <div>{row.label} · +{(row.start - base).toFixed(0)} ms · {row.duration.toFixed(1)} ms {row.server && `· ${row.server}`}</div>
        <div style={{ height: 4, background: '#334155' }}><div style={{ height: 4, background: '#38bdf8',
          marginLeft: `${100 * (row.start - base) / span}%`,
          width: `${Math.max(.3, 100 * row.duration / span)}%` }} /></div>
      </div>)}
    </details>
  </aside>
}

export default function XrayOverlay() {
  const { user } = useAuth()
  const location = useLocation()
  return user?.is_admin && new URLSearchParams(location.search).get('xray') === '1' ? <ActiveXray /> : null
}
