// Development-only synthetic fixture: the immersive ClipViewer with an
// auto-hiding HUD. No account, private media, or server writes. The clip is
// a local test pattern video (frontend/node_modules/.cache/hud-fixture-clip.mp4,
// gitignored) served straight from the dev server, so playback, pause and the
// 2×-speed press hold all behave like they do against a real file.
import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import ClipViewer from '../../src/components/clip-viewer/ClipViewer'
import { preparePlaybackWindow } from '../../src/utils/preparedPlayback'
import { api } from '../../src/services/api'
import type { Attempt } from '../../src/utils/attemptPresentation'
import '../../src/i18n'
import '../../src/index.css'
import '../../src/components/clip-viewer/clipViewer.css'
if (!import.meta.env.DEV) throw new Error('ClipViewer HUD fixture is development-only')

// The social/evaluation layer talks to the same origin through axios.axios
// resolves URLs and captures fetch eagerly, so instead of redirecting to a
// fetch stub, serve the fixture from a custom adapter (dev-only).
api.defaults.adapter = async (config) => {
  const method = (config.method || 'get').toLowerCase()
  const url = config.url || ''
  const respond = (data: unknown) => ({ data, status: 200, statusText: 'OK', headers: {}, config, request: {} as Record<string, unknown> })
  const dive = url.match(/^\/api\/v1\/dives\/(\d+)/)?.[1]
  if (dive) {
    const id = Number(dive)
    if (url.endsWith('/social') && method === 'get') return respond({ liked: false, like_count: id * 3, comment_count: id })
    if (url.endsWith('/like') && method === 'put') return respond({ liked: true, like_count: id * 3 + 1, comment_count: id })
    if (url.endsWith('/comments') && method === 'get') return respond({ items: [], next_before: null })
    if (url.endsWith('/comments') && method === 'post') return respond({ id: 4242, body: 'Fixture comment', author: 'Fixture', user_id: 1, created_at: new Date().toISOString() })
    if (url.endsWith('/evaluation') && method === 'get') return respond({ mean_score: 4, rating_count: 2, ratings: [] })
    if (url.endsWith('/shares') && method === 'get') return respond({ active_count: 2 })
  }
  throw Object.assign(new Error(`ClipViewer HUD fixture stub has no case for ${method.toUpperCase()} ${url}`), { isAxiosError: false })
}

const CLIP = '/node_modules/.cache/hud-fixture-clip.mp4'
function status(uuid: string) {
  return {
    video_uuid: uuid,
    status: 'ready',
    can_request: false,
    available_renditions: ['original', 'proxy_720p'],
    playback_url: `${CLIP}?v=${uuid}`,
    full_quality_url: `${CLIP}?full=1&v=${uuid}`,
    preview_url: `${CLIP}?preview=1&v=${uuid}`,
    poster_url: null,
    job: null,
  }
}
function social(id: number) {
  return { liked: false, like_count: id * 3, comment_count: id }
}
function commentList() {
  return { items: [], next_before: null }
}

const nativeFetch = window.fetch.bind(window)
window.fetch = async (input: RequestInfo | URL, options?: RequestInit) => {
  // Axios resolves relative URLs against the origin: compare pathnames only.
  let path: string
  try {
    path = new URL(String(input), window.location.origin).pathname
  } catch {
    path = String(input).replace(/[?#].*$/, '')
  }
  if (path === '/api/v1/media/status/batch') {
    const uuids = JSON.parse(String(options?.body)).video_uuids as string[]
    return Response.json(Object.fromEntries(uuids.map(uuid => [uuid, status(uuid)])))
  }
  let match = path.match(/^\/api\/v1\/media\/([^/]+)\/status$/)
  if (match) return Response.json(status(decodeURIComponent(match[1])))
  match = path.match(/^\/api\/v1\/media\/([^/]+)\/request$/)
  if (match) {
    const uuid = decodeURIComponent(match[1])
    return Response.json({ ...status(uuid), status: 'queued', created_job: true })
  }
  match = path.match(/^\/api\/v1\/dives\/(\d+)\/social$/)
  if (match) return Response.json(social(Number(match[1])))
  match = path.match(/^\/api\/v1\/dives\/(\d+)\/like$/)
  if (match) {
    const id = Number(match[1])
    return Response.json({ liked: true, like_count: id * 3 + 1, comment_count: id })
  }
  match = path.match(/^\/api\/v1\/dives\/(\d+)\/comments(\?.*)?$/)
  if (match) return Response.json(commentList())
  match = path.match(/^\/api\/v1\/dives\/(\d+)\/comments$/)
  if (match && options?.method === 'POST') {
    return Response.json({ id: 1, body: 'Fixture comment', author: 'Fixture', user_id: 1, created_at: new Date().toISOString() })
  }
  if (path === '/api/v1/auth/me') return new Response(null, { status: 401 })
  return nativeFetch(input, options)
}

const attempt = (id: number): Attempt => ({
  id,
  dive_code: '103B',
  performance: 'G',
  performance_numeric: 3,
  height: '3m',
  dive_datetime: `2026-07-${String((id % 28) + 1).padStart(2, '0')}T10:00:00`,
  session_id: 1,
  is_lineup: false,
  is_sync: false,
  platform_type: 'springboard',
  position: 'B',
  official_dd: 2.0,
  phase1_performance: 'G',
  phase2_performance: 'M',
  raw_caption: '103B G/G DB — HUD fixture',
  video_uuid: `hud-fixture-${id}`,
  diver_id: 1,
})
const attempts = [attempt(11), attempt(12), attempt(13)]

function Fixture() {
  const [index, setIndex] = useState(0)
  const current = attempts[index]
  useEffect(() => {
    preparePlaybackWindow(attempts.slice(index, index + 2).map(a => a.video_uuid))
  }, [index])
  return (
    <ClipViewer
      attempt={current}
      attempts={attempts}
      onClose={() => {}}
      onMove={(target) => setIndex(attempts.findIndex(a => a.id === target.id))}
      playbackRate={1}
      onPlaybackRateChange={() => {}}
    />
  )
}
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MemoryRouter>
      <Fixture />
    </MemoryRouter>
  </React.StrictMode>,
)
