// Development-only synthetic fixture. No account, private media, or server writes.
import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import DiveVideoPlayer from '../../src/components/DiveVideoPlayer'
import { preparePlaybackWindow } from '../../src/utils/preparedPlayback'
import '../../src/i18n'
import '../../src/index.css'
import '../../src/components/clip-viewer/clipViewer.css'
if (!import.meta.env.DEV) throw new Error('Library fixture is development-only')
const nativeFetch = window.fetch.bind(window)
function status(uuid: string) {
  return { video_uuid: uuid, status: 'ready', can_request: false, available_renditions: ['original', 'proxy_720p'],
    playback_url: `/fixture-original-${uuid}.mov`, full_quality_url: `/fixture-original-${uuid}.mov`,
    preview_url: `/node_modules/.cache/library-preview-synthetic.mp4?clip=${uuid}` }
}
window.fetch = async (input, options) => {
  const url = String(input)
  if (url.endsWith('/status/batch')) {
    const uuids = JSON.parse(String(options?.body)).video_uuids as string[]
    return Response.json(Object.fromEntries(uuids.map(uuid => [uuid, status(uuid)])))
  }
  const uuid = url.match(/\/media\/(fixture-\d+)\/status$/)?.[1]
  if (uuid) return Response.json(status(uuid))
  return nativeFetch(input, options)
}
function Fixture() {
  const [index, setIndex] = useState(1)
  useEffect(() => { preparePlaybackWindow([`fixture-${index}`, `fixture-${index + 1}`]) }, [index])
  return <div style={{ height: '100dvh', background: '#080c0d', position: 'relative' }}>
    <DiveVideoPlayer diveCode={`10${index}B`} height="3m" videoUuid={`fixture-${index}`} immersive />
    <button style={{ position: 'absolute', left: 16, top: 16, zIndex: 50, background: 'white', padding: 8 }} onClick={() => setIndex(value => value + 1)}>Next fixture clip</button>
  </div>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><MemoryRouter><Fixture /></MemoryRouter></React.StrictMode>)
