/**
 * Evaluation-scoped media player, v2 (issue #68).
 *
 * The Library transport (DiveVideoPlayer + mediaApi) is deliberately NOT
 * reused: another member's private evaluation dive is invisible there. This
 * player reads ONLY the evaluation transport of ticket 1 — status, poster,
 * playback bytes and preparation under `/api/v1/evaluations/requests/…` —
 * keeps its own local state (no shared preview cache, nothing leaks into the
 * Library), and never renders social/owner actions. Judging controls: replay,
 * pause/play, sound, slow motion — lucide glyphs grouped over the stage,
 * matching the existing immersive viewer's interaction vocabulary.
 *
 * HQ contract: identical to the established viewer — the backend status
 * resolves the preferred rendition (original → 720p preview → 360p preview) server-side;
 * `available_renditions` only informs the upgradability hint. When a clip is
 * playing a proxy while HQ could exist, preparation is requested once through
 * the evaluation transport (bounded, current clip only).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RotateCcw, Play, Pause, Volume2, VolumeX, Maximize } from 'lucide-react'
import {
  evaluationPlaybackUrl,
  getEvaluationMediaStatus,
  prepareEvaluationMedia,
  type EvaluationMediaStatus,
} from '../../services/evaluationApi'

const PREPARATION_GRACE_MS = 90_000
const SLOW_RATE = 0.5
/** Secondary player controls fade during smooth playback and come back on
 * any interaction or focus; critical navigation/score controls live outside
 * this component and never fade. */
const CONTROLS_IDLE_MS = 2200

type Playback =
  | { kind: 'checking' }
  | { kind: 'ready'; src: string; poster: string | null; hq: boolean; rendition: string; playableChoices: string[] }
  | { kind: 'preparing' }
  | { kind: 'missing' }
  | { kind: 'failed' }

const HQ_RENDITIONS = new Set(['proxy_720p', 'original'])
const PLAYABLE_RENDITIONS = ['original', 'proxy_720p', 'proxy_360p']

// Sound preference persists across dives (one nudge, no repeated prompts).
let soundPreferred = true

function packReady(status: EvaluationMediaStatus, rendition: string, automatic: boolean): Extract<Playback, { kind: 'ready' }> {
  if (status.available_renditions.includes('original')) rendition = 'original'
  const playableChoices = status.available_renditions.filter((name) => PLAYABLE_RENDITIONS.includes(name))
  return {
    kind: 'ready',
    src: evaluationPlaybackUrl(status.request_id, rendition, automatic),
    poster: status.poster_url,
    hq: HQ_RENDITIONS.has(rendition),
    rendition,
    playableChoices: playableChoices.length > 1 ? playableChoices : [],
  }
}

export default function EvaluationPlayer({
  requestId,
  paused = false,
  automatic = false,
  watching = false,
  onEnded,
  onReplay,
  onFailure,
}: {
  requestId: number
  paused?: boolean
  automatic?: boolean
  watching?: boolean
  onEnded?: () => void
  onReplay?: () => void
  onFailure?: () => void
}) {
  const { t } = useTranslation()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [wholeFrame, setWholeFrame] = useState(false)
  const [cover, setCover] = useState(1)
  const [pinchProgress, setPinchProgress] = useState(0)
  const failedRenditions = useRef(new Set<string>())
  const [decodeError, setDecodeError] = useState(false)
  const [playback, setPlayback] = useState<Playback>({ kind: 'checking' })
  // Identity guards: a response for a PREVIOUS request id (pending status
  // lookup or prepare follow-up after the jury advanced) must never replace
  // the new dive's playback — the juror would score dive A while watching B.
  const requestEpochRef = useRef(0)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(!soundPreferred)
  const [slow, setSlow] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [hqHint, setHqHint] = useState(false)
  const [controlsIdle, setControlsIdle] = useState(false)
  const idleTimerRef = useRef<number | null>(null)
  const prepareQueued = useRef(false)
  const userPausedRef = useRef(false)

  const load = useCallback(async () => {
    const epoch = ++requestEpochRef.current
    setPlayback({ kind: 'checking' })
    setHqHint(false)
    failedRenditions.current.clear()
    setDecodeError(false)
    setWholeFrame(false); setPinchProgress(0)
    prepareQueued.current = false
    try {
      const status = await getEvaluationMediaStatus(requestId, automatic)
      if (epoch !== requestEpochRef.current) return
      if (status.status === 'ready' && status.playback_url) {
        setPlayback(packReady(status, status.rendition ?? 'proxy_360p', automatic))
        setHqHint(!HQ_RENDITIONS.has(status.rendition ?? ''))
        if (!HQ_RENDITIONS.has(status.rendition ?? '') && !prepareQueued.current) {
          // Proxy-only playback while HQ may be preparable: one bounded ask.
          prepareQueued.current = true
          prepareEvaluationMedia(requestId, automatic).then((prepared) => {
            if (epoch !== requestEpochRef.current) return
            if (prepared.status === 'ready' && prepared.playback_url) {
              setPlayback(packReady(prepared, prepared.rendition ?? 'proxy_720p', automatic))
              setHqHint(!HQ_RENDITIONS.has(prepared.rendition ?? ''))
            }
          }).catch(() => {})
        }
        return
      }
      if (status.status === 'preparing') {
        setPlayback({ kind: 'preparing' })
        return
      }
      setPlayback({ kind: 'missing' })
    } catch (error: unknown) {
      if (epoch !== requestEpochRef.current) return
      const axios = error as { response?: { status?: number } }
      // Deactivated/revoked request: the evaluation ended for this item.
      setPlayback(axios.response?.status === 404 ? { kind: 'missing' } : { kind: 'failed' })
    }
  }, [requestId, automatic])

  useEffect(() => {
    userPausedRef.current = false
    setSlow(false)
    setMuted(!soundPreferred)
    void load()
  }, [load, attempt])

  // Bounded preparation wait with an explicit prepare request (transport
  // allows preparing the CURRENT clip only; never a mass preparation).
  useEffect(() => {
    if (playback.kind !== 'preparing' && playback.kind !== 'missing') return
    let alive = true
    const epoch = requestEpochRef.current
    const deadline = Date.now() + PREPARATION_GRACE_MS
    let timer: number
    const poll = async () => {
      if (!prepareQueued.current) {
        prepareQueued.current = true
        try { await prepareEvaluationMedia(requestId, automatic) } catch { /* Retry remains available. */ }
      }
      if (!alive || epoch !== requestEpochRef.current) return
      try {
        const status = await getEvaluationMediaStatus(requestId, automatic)
        if (!alive || epoch !== requestEpochRef.current) return
        if (status.status === 'ready' && status.playback_url) {
          setPlayback(packReady(status, status.rendition ?? 'proxy_360p', automatic))
          setHqHint(!HQ_RENDITIONS.has(status.rendition ?? ''))
          return
        }
      } catch { /* Retry transient failures within the bounded wait. */ }
      if (!alive || epoch !== requestEpochRef.current) return
      if (Date.now() >= deadline) setPlayback({ kind: 'failed' })
      else timer = window.setTimeout(poll, 2000)
    }
    timer = window.setTimeout(poll, playback.kind === 'missing' ? 600 : 2000)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [playback.kind, requestId, automatic])

  // Preparation may return the existing proxy while its HQ job is queued.
  // Keep checking the current clip, with a finite wait and identity guard.
  useEffect(() => {
    if (!hqHint || playback.kind !== 'ready') return
    let alive = true
    const epoch = requestEpochRef.current
    const deadline = Date.now() + PREPARATION_GRACE_MS
    let timer: number
    const poll = async () => {
      try {
        const status = await getEvaluationMediaStatus(requestId, automatic)
        if (!alive || epoch !== requestEpochRef.current) return
        if (status.status === 'ready' && status.playback_url && HQ_RENDITIONS.has(status.rendition ?? '')) {
          setPlayback(packReady(status, status.rendition!, automatic))
          setHqHint(false)
          return
        }
      } catch { /* Retry transient errors within the bounded wait. */ }
      if (!alive || epoch !== requestEpochRef.current) return
      if (Date.now() < deadline) timer = window.setTimeout(poll, 2000)
      else setHqHint(false)
    }
    timer = window.setTimeout(poll, 2000)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [hqHint, playback.kind, requestId, automatic])

  useEffect(() => {
    if (watching && (playback.kind === 'failed' || playback.kind === 'missing')) onFailure?.()
  }, [watching, playback.kind, onFailure])

  // Sound-first autoplay: honor the account's sound preference when the
  // browser still grants the gesture context, fall back silently otherwise
  // (iOS); no promise of guaranteed audio autoplay.
  useEffect(() => {
    if (playback.kind !== 'ready' || paused) return
    const video = videoRef.current
    if (!video || userPausedRef.current) return
    const start = async () => {
      try {
        video.muted = false
        await video.play()
        setMuted(false)
      } catch {
        try {
          video.muted = true
          await video.play()
          setMuted(true)
        } catch {
          /* Autoplay refused: the Play control stays available. */
        }
      }
    }
    void start()
  }, [playback.kind])

  // Judging/reveal moments pause the take so HUD controls never cover live
  // action the juror still needs to see (replay restarts on demand).
  useEffect(() => {
    if (playback.kind !== 'ready') return
    const video = videoRef.current
    if (!video) return
    if (paused) video.pause()
    else if (!userPausedRef.current) video.play().catch(() => {})
  }, [paused, playback.kind])

  /* Calm playback: while the take runs smoothly the secondary rail fades;
   * pointer movement, clicks, keys and focus bring it straight back, and the
   * rail always shows when paused. */
  useEffect(() => {
    if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current)
    if (!playing || paused) {
      setControlsIdle(false)
      return
    }
    idleTimerRef.current = window.setTimeout(() => setControlsIdle(true), CONTROLS_IDLE_MS)
    return () => {
      if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current)
    }
  }, [playing, paused, playback.kind])

  const wakeControls = () => {
    if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current)
    setControlsIdle(false)
    if (playing && !paused) {
      idleTimerRef.current = window.setTimeout(() => setControlsIdle(true), CONTROLS_IDLE_MS)
    }
  }

  const measureFrame = () => {
    const v = videoRef.current
    if (!v?.videoWidth || !v.videoHeight || !v.clientWidth || !v.clientHeight) return
    const scale = Math.min(v.clientWidth / v.videoWidth, v.clientHeight / v.videoHeight)
    setCover(Math.max(v.clientWidth / (v.videoWidth * scale), v.clientHeight / (v.videoHeight * scale)))
  }
  useEffect(() => {
    measureFrame()
    const v = videoRef.current
    if (!v) return
    const observer = new ResizeObserver(measureFrame)
    observer.observe(v)
    return () => observer.disconnect()
  }, [playback.kind, watching])
  useEffect(() => {
    const v = videoRef.current
    if (!v || !watching) return
    let start = 0, initial = 0, progress = wholeFrame ? 1 : 0
    const distance = (event: TouchEvent) => Math.hypot(event.touches[0].clientX - event.touches[1].clientX, event.touches[0].clientY - event.touches[1].clientY)
    const begin = (event: TouchEvent) => { if (event.touches.length === 2) { start = distance(event); initial = wholeFrame ? 1 : 0 } }
    const move = (event: TouchEvent) => {
      if (!start || event.touches.length !== 2) return
      event.preventDefault()
      progress = Math.max(0, Math.min(1, initial + (1 - distance(event) / start) / .35))
      setPinchProgress(progress)
    }
    const end = () => { if (start) { setWholeFrame(progress >= .5); setPinchProgress(progress >= .5 ? 1 : 0); start = 0 } }
    v.addEventListener('touchstart', begin)
    v.addEventListener('touchmove', move, { passive: false })
    v.addEventListener('touchend', end)
    v.addEventListener('touchcancel', end)
    return () => { v.removeEventListener('touchstart', begin); v.removeEventListener('touchmove', move); v.removeEventListener('touchend', end); v.removeEventListener('touchcancel', end) }
  }, [watching, wholeFrame, playback.kind])
  function mediaError() {
    if (playback.kind !== 'ready') return
    failedRenditions.current.add(playback.rendition)
    const next = playback.playableChoices.find(name => !failedRenditions.current.has(name))
    if (next) setDecodeError(true)
    else setPlayback({ kind: 'failed' })
  }

  function togglePlay() {
    if (paused) { onReplay?.(); return }
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      userPausedRef.current = false
      video.play().catch(() => {})
    } else {
      userPausedRef.current = true
      video.pause()
    }
  }

  function replay() {
    if (paused) { onReplay?.(); return }
    const video = videoRef.current
    if (!video) return
    userPausedRef.current = false
    video.currentTime = 0
    video.play().catch(() => {})
  }

  function toggleSound() {
    const video = videoRef.current
    if (!video) return
    const next = !video.muted
    video.muted = next
    soundPreferred = !next
    setMuted(next)
    if (!next && !paused) video.play().catch(() => {})
  }

  function toggleSlow() {
    const video = videoRef.current
    if (!video) return
    const next = !slow
    video.playbackRate = next ? SLOW_RATE : 1
    setSlow(next)
  }

  if (playback.kind === 'checking') {
    return <div className="eval-player eval-player-state" role="status">{t('evaluations.mediaChecking')}</div>
  }
  if (playback.kind === 'preparing' || playback.kind === 'missing') {
    return (
      <div className="eval-player eval-player-state" role="status">
        <p>{playback.kind === 'preparing' ? t('evaluations.mediaPending') : t('evaluations.mediaMissing')}</p>
        <button type="button" className="eval-retry" onClick={() => setAttempt((value) => value + 1)}>
          {t('evaluations.mediaRetry')}
        </button>
      </div>
    )
  }
  if (playback.kind === 'ready' && decodeError) {
    const next = playback.playableChoices.find(name => !failedRenditions.current.has(name))
    return <div className="eval-player eval-player-state" role="alert">
      <p>{t('evaluations.mediaFailed')}</p>
      <button type="button" className="eval-retry" onClick={() => { setDecodeError(false); setAttempt(value => value + 1) }}>{t('evaluations.mediaRetry')}</button>
      {next && <button type="button" className="eval-retry" onClick={() => {
        setDecodeError(false)
        setPlayback({ ...playback, rendition: next, src: evaluationPlaybackUrl(requestId, next, automatic), hq: HQ_RENDITIONS.has(next) })
      }}>{t('videoPlayer.usePreview')}</button>}
    </div>
  }
  if (playback.kind === 'failed') {
    return (
      <div className="eval-player eval-player-state" role="alert">
        <p>{t('evaluations.mediaFailed')}</p>
        <button type="button" className="eval-retry" onClick={() => setAttempt((value) => value + 1)}>
          {t('evaluations.mediaRetry')}
        </button>
      </div>
    )
  }
  return (
    <div
      className="eval-player"
      data-watching={watching ? 'true' : undefined}
      style={{ '--eval-cover': cover + (1 - cover) * pinchProgress } as React.CSSProperties}
      data-controls-idle={controlsIdle ? 'true' : undefined}
      onPointerMove={wakeControls}
      onPointerDown={wakeControls}
      onKeyDown={wakeControls}
      onFocusCapture={wakeControls}
    >
      <video
        key={playback.src}
        ref={videoRef}
        src={playback.src}
        poster={playback.poster ?? undefined}
        autoPlay={!paused}
        tabIndex={0}
        aria-label={t('evaluations.playerControlsAria')}
        onKeyDown={event => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); togglePlay() } }}
        onEnded={onEnded}
        onError={mediaError}
        onLoadedMetadata={measureFrame}
        muted={muted}
        playsInline
        preload="auto"
        controlsList="nodownload noremoteplayback"
        disablePictureInPicture
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onRateChange={(event) => setSlow(event.currentTarget.playbackRate < 1)}
        onClick={togglePlay}
      />
      {hqHint && (
        <span className="eval-hq-hint" role="status">{t('evaluations.hqUpgrading')}</span>
      )}
      <div className="eval-player-controls" role="group" aria-label={t('evaluations.playerControlsAria')}>
        <button type="button" onClick={replay} disabled={paused && !onReplay} aria-label={t('evaluations.replayAria')}>
          <RotateCcw size={18} />
        </button>
        <button type="button" onClick={togglePlay} disabled={paused && !onReplay} aria-label={playing ? t('evaluations.pauseAria') : t('evaluations.playAria')}>
          {playing ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button
          type="button"
          onClick={toggleSound}
          aria-label={muted ? t('evaluations.soundOnAria') : t('evaluations.soundOffAria')}
          className={muted ? 'eval-sound-off' : 'eval-sound-on'}
        >
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <button type="button" onClick={toggleSlow} aria-pressed={slow} aria-label={t('evaluations.slowAria')} title={t('evaluations.slowLabel')}>
          0.5×
        </button>
        {watching && <button type="button" aria-label={t('evaluations.wholeFrame')} aria-pressed={wholeFrame} onClick={() => { setWholeFrame(!wholeFrame); setPinchProgress(wholeFrame ? 0 : 1) }}><Maximize size={18} /></button>}
        {playback.playableChoices.length >= 2 && playback.kind === 'ready' && (
          <button
            type="button"
            aria-label={t('evaluations.qualityLabelAria')}
            title={playback.rendition === 'original' ? t('evaluations.qualityOriginal') : `${t('videoPlayer.previewQuality')} (${playback.rendition === 'proxy_720p' ? '720p' : '360p'})`}
            className={playback.rendition === 'original' ? 'eval-quality-orig' : undefined}
            onClick={() => {
              // Cycle within the READY playable list; the first entry keeps
              // the server's HQ-contract choice (original → 720p preview).
              const order = [...playback.playableChoices]
              const index = order.indexOf(playback.rendition)
              const next = order[(index + 1) % order.length]
              setPlayback({ ...playback, src: evaluationPlaybackUrl(requestId, next, automatic), rendition: next, hq: HQ_RENDITIONS.has(next) })
            }}
          >
            {playback.rendition === 'original' ? t('evaluations.qualityOriginal') : `${t('videoPlayer.previewQuality')} (${playback.rendition === 'proxy_720p' ? '720p' : '360p'})`}
          </button>
        )}
      </div>
    </div>
  )
}
