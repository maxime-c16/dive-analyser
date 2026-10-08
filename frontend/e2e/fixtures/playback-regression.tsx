// Development-only fixture. Browser tests supply account/status/media routes;
// no production authentication or source-selection behavior is bypassed.
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../../src/contexts/AuthContext'
import ClipViewer from '../../src/components/clip-viewer/ClipViewer'
import { prepareLibraryPlayback } from '../../src/utils/preparedPlayback'
import type { Attempt } from '../../src/utils/attemptPresentation'
import '../../src/index.css'
if (!import.meta.env.DEV) throw new Error('Playback fixture is development-only')
const attempts = [1, 2, 3, 4].map(id => ({
  id, video_uuid: `playback-${id}`, dive_code: '103B', height: '1m', platform_type: 'springboard',
  dive_datetime: '2026-10-08T10:00:00', performance: 'G', performance_numeric: 3,
  session_id: 1, is_lineup: false, is_sync: false, official_dd: 1.7,
  phase1_performance: 'G', phase2_performance: 'G', raw_caption: '103B G/G',
  visibility: 'public', can_manage: false,
})) as Attempt[]
function Review() {
  const [attempt, setAttempt] = useState<Attempt | null>(null)
  const [rate, setRate] = useState(1)
  return <MemoryRouter><AuthProvider>{attempt ? <ClipViewer
    attempt={attempt} attempts={attempts} onClose={() => setAttempt(null)} onMove={setAttempt}
    playbackRate={rate} onPlaybackRateChange={setRate}
  /> : <button onPointerEnter={() => prepareLibraryPlayback('playback-1', true)}
    onFocus={() => prepareLibraryPlayback('playback-1', true)} onClick={() => setAttempt(attempts[0])}>Open dive</button>}
  </AuthProvider></MemoryRouter>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><Review /></React.StrictMode>)
