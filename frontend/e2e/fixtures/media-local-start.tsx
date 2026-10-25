// Local synthetic measurement only. No production requests, credentials or writes.
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import DiveVideoPlayer from '../../src/components/DiveVideoPlayer'
import '../../src/i18n'
import '../../src/index.css'
if (!import.meta.env.DEV) throw new Error('Development only')
const baseline = new URLSearchParams(location.search).has('baseline')
const local = 'http://127.0.0.1:3023/preview'
const light = 'http://127.0.0.1:3023/light'
const nativeFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  if (String(input).includes('/api/v1/media/')) return Response.json({
    video_uuid: 'fixture-lot3', status: 'ready', can_request: false,
    playback_url: baseline ? light : local, preview_url: baseline ? light : local,
    available_renditions: ['proxy_720p'], full_quality_url: null,
    // Baseline reproduces old durable-first selection by hiding the local entry
    // from the new source policy. Both runs use the actual current player.
    cache_entries: baseline ? [] : [{ id: 1, rendition: 'proxy_720p', playback_url: local }],
    derivatives: { hq: { state: 'missing' }, poster: { state: 'missing' }, light: { state: 'ready', playback_url: light } },
  })
  return nativeFetch(input, options)
}
function Fixture() {
  const [open, setOpen] = useState(false)
  return open ? <DiveVideoPlayer diveCode="103B" height="3m" videoUuid="fixture-lot3" immersive /> : <button onClick={() => setOpen(true)}>Start</button>
}
createRoot(document.getElementById('root')!).render(<MemoryRouter><Fixture /></MemoryRouter>)
