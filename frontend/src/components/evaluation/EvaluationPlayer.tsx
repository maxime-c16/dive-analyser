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
 * Start with a ready 720p preview, then 360p, then the original.
 * The original remains selectable; background preparation updates the quality
 * choices without replacing any source that has already shown a frame.
 * Preparation stays bounded to the current clip and an original-only next clip.
 */
import useEvaluationVideoSource from './useEvaluationVideoSource'
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
const COLD_PREPARATION_GRACE_MS = 5 * 60_000
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

function hasPreview(status: EvaluationMediaStatus) {
  return status.available_renditions.some(name => name === 'proxy_720p' || name === 'proxy_360p')
}

function packReady(status: EvaluationMediaStatus, rendition: string, automatic: boolean): Extract<Playback, { kind: 'ready' }> {
  // Start with the small, browser-compatible rendition; originals stay explicit.
  rendition = ['proxy_720p', 'proxy_360p', 'original'].find(name => status.available_renditions.includes(name)) ?? rendition
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
  preloadOnly = false,
  replayToken = 0,
  onBuffered,
  onPrepared,
  initialMedia,
}: {
  requestId: number
  initialMedia?: EvaluationMediaStatus
  preloadOnly?: boolean
  replayToken?: number
  onBuffered?: () => void
  onPrepared?: () => void
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
  const hasDecodedFrameRef = useRef(false)
  const [decodeError, setDecodeError] = useState(false)
  const initialMediaRef = useRef(initialMedia)
  const [playback, setPlayback] = useState<Playback>(() => initialMedia?.status === 'ready' && initialMedia.playback_url
    ? (hasPreview(initialMedia) ? packReady(initialMedia, initialMedia.rendition ?? 'original', automatic) : { kind: 'preparing' })
    : { kind: 'checking' })
  // Identity guards: a response for a PREVIOUS request id (pending status
  // lookup or prepare follow-up after the jury advanced) must never replace
  // the new dive's playback — the juror would score dive A while watching B.
  const requestEpochRef = useRef(0)
  const source = useEvaluationVideoSource(playback.kind === 'ready' ? playback.src : undefined, playback.kind === 'ready' ? playback.rendition : undefined)
  useEffect(() => {
    // iOS may defer decoding hidden videos. A fully downloaded blob is enough
    // to promote the next slot; the visible player still gates on its frame.
    if (source.src?.startsWith('blob:')) onPrepared?.()
  }, [source.src, onPrepared])
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(!soundPreferred)
  const [slow, setSlow] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [hqHint, setHqHint] = useState(false)
  const [controlsIdle, setControlsIdle] = useState(false)
  const idleTimerRef = useRef<number | null>(null)
  const prepareQueued = useRef(false)
  const waitingForPreviewRef = useRef(false)
  const userPausedRef = useRef(false)

  const preloadOnlyRef = useRef(preloadOnly)
  preloadOnlyRef.current = preloadOnly

  const updatePreparedChoices = useCallback((current: Playback, status: EvaluationMediaStatus): Playback => {
    if (current.kind !== 'ready') return current
    const ready = packReady(status, status.rendition ?? 'original', automatic)
    // A not-yet-started original can yield to its newly prepared preview.
    // Once any action has played, keep the source and only update choices.
    if (current.rendition === 'original' && ready.rendition !== 'original' && !hasDecodedFrameRef.current) return ready
    const choices = [...new Set([current.rendition, ...status.available_renditions.filter(name => PLAYABLE_RENDITIONS.includes(name))])]
    return { ...current, playableChoices: choices.length > 1 ? choices : [] }
  }, [automatic])

  const load = useCallback(async () => {
    const epoch = ++requestEpochRef.current
    const seeded = initialMediaRef.current
    initialMediaRef.current = undefined
    if (!seeded) setPlayback({ kind: 'checking' })
    setHqHint(false)
    failedRenditions.current.clear()
    hasDecodedFrameRef.current = false
    setDecodeError(false)
    setWholeFrame(false); setPinchProgress(0)
    prepareQueued.current = false
    waitingForPreviewRef.current = false
    try {
      const status = seeded ?? await getEvaluationMediaStatus(requestId, automatic)
      if (epoch !== requestEpochRef.current) return
      if (status.status === 'ready' && status.playback_url) {
        if (!hasPreview(status)) {
          waitingForPreviewRef.current = true
          setPlayback({ kind: 'preparing' })
          return
        }
        waitingForPreviewRef.current = false
        const ready = packReady(status, status.rendition ?? 'original', automatic)
        const needsPreview = !status.available_renditions.includes('proxy_720p')
        setPlayback(ready)
        setHqHint(needsPreview)
        if (needsPreview && (!preloadOnlyRef.current || ready.rendition === 'original') && !prepareQueued.current) {
          // Prepare a missing preview once; the session mounts at most two clips.
          prepareQueued.current = true
          prepareEvaluationMedia(requestId, automatic).then((prepared) => {
            if (epoch !== requestEpochRef.current) return
            if (prepared.status === 'ready' && prepared.playback_url) {
              setPlayback(current => updatePreparedChoices(current, prepared))
              setHqHint(!prepared.available_renditions.includes('proxy_720p'))
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
  }, [requestId, automatic, updatePreparedChoices])

  useEffect(() => {
    userPausedRef.current = false
    setSlow(false)
    setMuted(!soundPreferred)
    void load()
    return () => { requestEpochRef.current += 1 }
  }, [load, attempt])

  // Bounded preparation of the current clip and one anticipated clip.
  // Stay here while a queued preview is being generated, even when the
  // catalog advertises a cloud original as ready.
  useEffect(() => {
    if (playback.kind !== 'preparing' && playback.kind !== 'missing') return
    let alive = true
    const epoch = requestEpochRef.current
    const deadline = Date.now() + COLD_PREPARATION_GRACE_MS
    let timer: number
    const poll = async () => {
      if (!prepareQueued.current) {
        prepareQueued.current = true
        try {
          const prepared = await prepareEvaluationMedia(requestId, automatic)
          if (!alive || epoch !== requestEpochRef.current) return
          // Legacy servers may reuse a local original without a preview job.
          // A queued job, however, is NOT playable readiness.
          const previewQueued = [...prepared.created_jobs, ...prepared.reused_jobs].includes('proxy_720p')
          if (previewQueued && !hasPreview(prepared)) waitingForPreviewRef.current = true
          if (prepared.status === 'ready' && prepared.playback_url && (hasPreview(prepared) || !previewQueued)) {
            waitingForPreviewRef.current = false
            setPlayback(packReady(prepared, prepared.rendition ?? 'original', automatic))
            return
          }
        } catch { /* Poll transient preparation errors within the bounded wait. */ }
      }
      if (!alive || epoch !== requestEpochRef.current) return
      try {
        const status = await getEvaluationMediaStatus(requestId, automatic)
        if (!alive || epoch !== requestEpochRef.current) return
        if (status.status === 'ready' && status.playback_url && (!waitingForPreviewRef.current || hasPreview(status))) {
          setPlayback(packReady(status, status.rendition ?? 'proxy_360p', automatic))
          setHqHint(!HQ_RENDITIONS.has(status.rendition ?? ''))
          return
        }
      } catch { /* Retry transient failures within the bounded wait. */ }
      if (!alive || epoch !== requestEpochRef.current) return
      if (Date.now() >= deadline) setPlayback({ kind: 'failed' })
      else timer = window.setTimeout(poll, 2000)
    }
    timer = window.setTimeout(poll, 0)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [playback.kind, requestId, automatic, preloadOnly])

  // Preparation may return the existing proxy while its HQ job is queued.
  // Keep checking the current clip, with a finite wait and identity guard.
  useEffect(() => {
    if (!hqHint || playback.kind !== 'ready' || (preloadOnly && playback.rendition !== 'original')) return
    if (!prepareQueued.current) {
      prepareQueued.current = true
      void prepareEvaluationMedia(requestId, automatic).catch(() => {})
    }
    let alive = true
    const epoch = requestEpochRef.current
    const deadline = Date.now() + PREPARATION_GRACE_MS
    let timer: number
    const poll = async () => {
      try {
        const status = await getEvaluationMediaStatus(requestId, automatic)
        if (!alive || epoch !== requestEpochRef.current) return
        if (status.status === 'ready' && status.playback_url && status.available_renditions.includes('proxy_720p')) {
          setPlayback(current => updatePreparedChoices(current, status))
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
  }, [hqHint, playback.kind, requestId, automatic, preloadOnly, updatePreparedChoices])

  useEffect(() => {
    if ((watching || preloadOnly) && (playback.kind === 'failed' || decodeError)) onFailure?.()
  }, [watching, preloadOnly, playback.kind, decodeError, onFailure])

  useEffect(() => {
    if (playback.kind !== 'ready' || preloadOnly || !source.src) return
    const timer = window.setTimeout(() => {
      if (!hasDecodedFrameRef.current && (!videoRef.current || videoRef.current.readyState < 2)) setPlayback({ kind: 'failed' })
    }, 20_000)
    return () => window.clearTimeout(timer)
  }, [preloadOnly, playback.kind, source.src])

  useEffect(() => {
    if (source.error) mediaError()
    // Each transport failure is handled once; callback state changes do not
    // retry a failed source until the user explicitly retries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.error])

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
  }, [playback.kind, paused, source.src])

  // Judging/reveal moments pause the take so HUD controls never cover live
  // action the juror still needs to see (replay restarts on demand).
  useEffect(() => {
    if (playback.kind !== 'ready') return
    const video = videoRef.current
    if (!video) return
    if (paused) video.pause()
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
  useEffect(() => {
    if (!replayToken) return
    const video = videoRef.current
    if (!video) return
    userPausedRef.current = false
    video.currentTime = 0
    video.play().catch(() => {})
  }, [replayToken])

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
        src={source.src}
        poster={playback.poster ?? undefined}
        autoPlay={!paused}
        tabIndex={0}
        aria-label={t('evaluations.playerControlsAria')}
        onKeyDown={event => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); togglePlay() } }}
        onEnded={onEnded}
        onError={mediaError}
        onLoadedMetadata={measureFrame}
        onLoadedData={() => { hasDecodedFrameRef.current = true; onBuffered?.() }}
        onPlaying={() => { hasDecodedFrameRef.current = true }}
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
            className={`eval-quality-toggle${playback.rendition === 'original' ? ' eval-quality-orig' : ''}`}
            onClick={() => {
              // Cycle within the READY playable list; the first entry keeps
              // the server's HQ-contract choice (original → 720p preview).
              const order = [...playback.playableChoices]
              const index = order.indexOf(playback.rendition)
              const next = order[(index + 1) % order.length]
              setPlayback({ ...playback, src: evaluationPlaybackUrl(requestId, next, automatic), rendition: next, hq: HQ_RENDITIONS.has(next) })
            }}
          >
            {playback.rendition === 'original' ? 'Original' : playback.rendition === 'proxy_720p' ? '720p' : '360p'}
          </button>
        )}
      </div>
    </div>
  )
}
