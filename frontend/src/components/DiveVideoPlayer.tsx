import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Clock, DownloadCloud, ImageOff, LogIn, RefreshCw, WifiOff } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ImmersiveControls, { type FeedDragEnd } from './clip-viewer/ImmersiveControls'
import { useAuth } from '../contexts/AuthContext'
import { cachedPreview } from '../utils/mediaPreview'
import {
  getMediaStatus,
  getPlaybackUrlFromStatus,
  getPosterUrlFromStatus,
  requestMedia as requestMediaRendition,
  type MediaStatus,
} from '../services/mediaApi'

/**
 * Frontend transport-failure policy (backend lifecycle semantics untouched):
 *
 * - Initial status lookup: bounded automatic retries, then a terminal
 *   retryable-error state with a manual "Retry status check" action.
 *   A failed status GET never submits a preparation request.
 * - Active preparation polling: one or more transport failures preserve the
 *   last known authoritative state and surface a "connection interrupted"
 *   notice; after MAX_POLL_FAILURES consecutive failures the automatic loop
 *   stops and a manual "Check status again" action is offered. No endless
 *   spinner while errors are silently swallowed.
 * - A legitimate long-running preparation is never marked failed; after
 *   LONG_PREPARATION_MS the presentation honestly becomes "Still preparing
 *   this clip" with an explicit "Check status now" affordance. No invented
 *   progress percentages, no job cancellation.
 * - Transport retry actions only re-run the status lookup. "Prepare clip" /
 *   "Retry prepare" remain explicit user actions and are guarded against
 *   duplicate submission.
 */

export const INITIAL_STATUS_ATTEMPTS = 3
export const INITIAL_STATUS_RETRY_DELAY_MS = 600
export const MAX_POLL_FAILURES = 5
export const MEDIA_POLL_INTERVAL_MS = 3000
export const LONG_PREPARATION_MS = 90_000

const ACTIVE_PREPARATION_STATES = [
  'queued',
  'waiting_for_mac',
  'claimed',
  'exporting',
  'transcoding',
  'uploading',
  'verifying',
]

type Phase =
  | { kind: 'checking' }
  | { kind: 'ready'; src: string }
  | { kind: 'preparing'; state: string; longRunning: boolean; stopped: boolean }
  | { kind: 'prepare-failed'; message: string | null; fallback: 'prepareFailed' | 'requestFailed' }
  | { kind: 'not-cached' }
  | { kind: 'transport-failed' }

// Feature detection for the first-frame presentation API (Safari/iOS).
type FrameCallbackVideo = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: (now: number) => void) => number
  cancelVideoFrameCallback?: (handle: number) => void
}

function preparationLabel(state: string) {
  return state.replace(/_/g, ' ')
}

const PREPARATION_STATE_KEYS = [
  'queued',
  'waiting_for_mac',
  'claimed',
  'exporting',
  'transcoding',
  'uploading',
  'verifying',
]

interface DiveVideoPlayerProps {
  diveCode: string
  height: string
  videoUuid: string
  playbackRate?: number
  immersive?: boolean
  onAspectRatioChange?: (ratio: number) => void
  onLike?: () => void
  onNavigate?: (direction: -1 | 1) => void
  dragEnabled?: boolean
  onDragUpdate?: (dy: number) => void
  onDragEnd?: (result: FeedDragEnd) => void
  onPinchStart?: () => void
  onPinchUpdate?: (ratio: number) => void
  onPinchEnd?: (cancelled: boolean) => void
}

function DiveVideoPlayer({ diveCode, height, videoUuid, playbackRate = 1, immersive = false, onAspectRatioChange, onLike = () => {}, onNavigate = () => {}, dragEnabled = false, onDragUpdate, onDragEnd, onPinchStart, onPinchUpdate, onPinchEnd }: DiveVideoPlayerProps) {
  const { t } = useTranslation()
  const videoRef = useRef<HTMLVideoElement>(null)
  const { user, checking: authChecking } = useAuth()

  // First-paint seed: the shared media-preview cache (warmed by Library
  // tiles and the viewer's neighbor warm-up) is applied in the state
  // initializers, so the very first render already carries the cached poster
  // and playback URL instead of a checking spinner or a black frame. The
  // authoritative status lookup below still runs and stays the lifecycle
  // authority — the seed only decides what the first paint shows.
  const initialSeed = videoUuid ? cachedPreview(videoUuid) : null
  const [phase, setPhase] = useState<Phase>(() =>
    videoUuid && initialSeed?.playbackUrl
      ? { kind: 'ready', src: initialSeed.playbackUrl }
      : { kind: 'checking' },
  )
  const [stale, setStale] = useState(false)
  const [posterSrc, setPosterSrc] = useState<string | null>(() =>
    videoUuid ? initialSeed?.posterUrl ?? null : null,
  )
  const [posterFailed, setPosterFailed] = useState(false)
  const [canRequest, setCanRequest] = useState(false)
  const [decodeError, setDecodeError] = useState(false)
  const [statusUnknown, setStatusUnknown] = useState(false)
  const [isRequesting, setIsRequesting] = useState(false)
  const [retryEpoch, setRetryEpoch] = useState(0)

  // Load identity of the first-frame gate: the ready source itself. Any
  // identity change — source switch, leaving or re-entering ready, A→B→A —
  // opens a new generation whose presentation flag is reset synchronously
  // during this render (pre-paint), so a new load cycle can never be
  // mistaken for the already-presented one and drop its cover. A
  // decode-failure cycle resolves to null: entering the error state itself
  // changes nothing behind the error overlay; the deliberate retry re-arms
  // the gate and performs the real element restart.
  const gateKey = phase.kind === 'ready' && !decodeError ? phase.src : null
  const [gate, setGate] = useState(() => ({ key: gateKey, presented: false }))
  if (gate.key !== gateKey) {
    setGate({ key: gateKey, presented: false })
  }
  const framePresented = phase.kind === 'ready' && gate.presented && gate.key === gateKey

  const failuresRef = useRef(0)
  const preparingSinceRef = useRef<number | null>(null)
  const lastPreparingStateRef = useRef<string | null>(null)
  const requestingRef = useRef(false)
  // Startup-only autoplay guards: the canplay retry must never override an
  // intentional pause (e.g. a later canplay after seeking).
  const hasPlayedRef = useRef(false)
  const userPausedRef = useRef(false)
  // Same-URL decode retry only: the next armed load generation must restart
  // the element for real (React would not reload an unchanged src).
  const needsRestartRef = useRef(false)
  // True only while the element is muted by OUR autoplay fallback below —
  // cleared the moment sound returns by any path, so a later user gesture
  // can restore sound-by-default without ever fighting an intentional mute.
  const [autoMuted, setAutoMuted] = useState(false)

  const applyStatus = useCallback((data: MediaStatus) => {
    setStatusUnknown(false)
    setCanRequest(Boolean(data.can_request))
    setPosterSrc(getPosterUrlFromStatus(data))

    const playbackUrl = getPlaybackUrlFromStatus(data)
    if (data.status === 'ready' && playbackUrl) {
      preparingSinceRef.current = null
      lastPreparingStateRef.current = null
      setPhase({ kind: 'ready', src: playbackUrl })
      return
    }

    if (ACTIVE_PREPARATION_STATES.includes(data.status)) {
      if (preparingSinceRef.current === null) preparingSinceRef.current = Date.now()
      const longRunning =
        preparingSinceRef.current !== null &&
        Date.now() - preparingSinceRef.current > LONG_PREPARATION_MS
      lastPreparingStateRef.current = data.status
      setPhase({ kind: 'preparing', state: data.status, longRunning, stopped: false })
      return
    }

    if (data.status === 'failed' || data.status === 'unavailable') {
      preparingSinceRef.current = null
      lastPreparingStateRef.current = null
      setPhase({
        kind: 'prepare-failed',
        message: data.job?.last_error || null,
        fallback: 'prepareFailed',
      })
      return
    }

    preparingSinceRef.current = null
    lastPreparingStateRef.current = null
    setPhase({ kind: 'not-cached' })
  }, [])

  // Initial status lookup with a bounded automatic retry window. Terminal
  // transport failure is actionable (manual retry) — never an endless
  // spinner, and never an automatic preparation request.
  //
  // Fast path: the shared media-preview cache usually already knows this
  // clip (Library tiles and the viewer's neighbor warm-up both resolve
  // statuses there). A known poster and playback URL are applied
  // immediately, before the status GET resolves, so playback starts in
  // parallel with the authoritative revalidation instead of after it.
  // The backend status remains the lifecycle authority and still rewrites
  // or corrects the seeded phase when it responds.
  useEffect(() => {
    let cancelled = false
    failuresRef.current = 0
    hasPlayedRef.current = false
    userPausedRef.current = false
    setStale(false)
    setDecodeError(false)
    setPosterSrc(null)
    setStatusUnknown(false)
    setAutoMuted(false)

    const seed = videoUuid ? cachedPreview(videoUuid) : null
    if (seed?.posterUrl) setPosterSrc(seed.posterUrl)
    if (seed?.playbackUrl) {
      // Seeding the ready phase with a previously issued playback URL
      // never creates preparation work and never overrides backend state:
      // the authoritative status lookup below still runs and applies.
      preparingSinceRef.current = null
      lastPreparingStateRef.current = null
      setPhase({ kind: 'ready', src: seed.playbackUrl })
    } else {
      setPhase({ kind: 'checking' })
    }

    const run = async (attempt: number) => {
      try {
        const data = await getMediaStatus(videoUuid)
        if (cancelled) return
        applyStatus(data)
      } catch {
        if (cancelled) return
        if (attempt < INITIAL_STATUS_ATTEMPTS) {
          window.setTimeout(() => {
            if (!cancelled) run(attempt + 1)
          }, INITIAL_STATUS_RETRY_DELAY_MS * attempt)
        } else {
          // A windowed transport failure after a seeded playback must not
          // swallow the warm clip (bytes it was served earlier were valid)
          // nor strand the viewer in an unreachable overlay: keep the
          // playback and surface the failed lookup separately, actionable.
          setPhase((prev) => (prev.kind === 'ready' ? prev : { kind: 'transport-failed' }))
          setStatusUnknown(true)
        }
      }
    }
    run(1)
    return () => {
      cancelled = true
    }
  }, [videoUuid, retryEpoch, applyStatus])

  // Status polling while the backend reports a legitimate active
  // preparation state. Transport failures and backend lifecycle state are
  // different concepts: transient failures preserve the last known state;
  // consecutive failures terminalize the automatic loop.
  const isPreparing = phase.kind === 'preparing'
  const pollStopped = phase.kind === 'preparing' && phase.stopped

  useEffect(() => {
    if (!isPreparing || pollStopped) return
    let alive = true
    const tick = async () => {
      try {
        const data = await getMediaStatus(videoUuid)
        if (!alive) return
        failuresRef.current = 0
        setStale(false)
        applyStatus(data)
      } catch {
        if (!alive) return
        failuresRef.current += 1
        if (failuresRef.current >= MAX_POLL_FAILURES) {
          setStale(false)
          setPhase((prev) =>
            prev.kind === 'preparing' ? { ...prev, stopped: true } : prev,
          )
        } else {
          setStale(true)
        }
      }
    }
    const timer = window.setInterval(tick, MEDIA_POLL_INTERVAL_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [isPreparing, pollStopped, videoUuid, applyStatus])

  // A failed poster image only fails once per URL; a corrected status
  // re-arms the image element.
  useEffect(() => {
    setPosterFailed(false)
  }, [posterSrc])

  // First-frame presentation gate. The incoming-clip cover stays up until
  // THIS clip's current source presents a decoded frame — requestVideoFrameCallback
  // when the browser offers it, with loadeddata/canplay (HAVE_CURRENT_DATA)
  // and real-playback (playing/timeupdate) backstops that ALSO apply on the
  // rVFC path. A single one-shot frame callback must never be the only
  // reveal signal: autoplay blocks, background tabs and browser quirks can
  // all leave a registered callback unfired while the element already holds
  // decodable data — or is outright playing behind the cover. Reveal signals
  // are scoped to the load identity: a source change or unmount cancels the
  // pending registration and detaches the listeners, so a late callback or
  // event can never reveal another generation's cover. A paused element that
  // already holds decodable data has presented that frame (e.g. blocked
  // autoplay), so the readiness check backstops the callback path on every
  // media event, not just at arm time.
  //
  // Deliberately no video.load() here: setting the src attribute already
  // starts resource selection, and an explicit restart would abort the
  // in-flight native load (and its autoplay) on every open, delaying the
  // first frame. Only a deliberate same-URL decode retry restarts the
  // element (needsRestartRef); source switches reload implicitly via src.
  useLayoutEffect(() => {
    if (!gateKey) return
    const video = videoRef.current
    if (!video) return
    if (needsRestartRef.current) {
      needsRestartRef.current = false
      video.load()
    }
    let cancelled = false
    let raf = 0
    let handle: number | undefined
    // HAVE_CURRENT_DATA: the frame at the current position is decodable.
    // One compositor frame is granted before the cover is dropped.
    const dataReady = () => video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
    const reveal = () => {
      // Identity-guarded: a late callback from an earlier generation cannot
      // flip the current gate even if cancellation ever missed it.
      if (!cancelled) {
        setGate((current) =>
          current.key === gateKey ? { key: current.key, presented: true } : current,
        )
      }
    }
    const revealViaCompositor = () => {
      if (typeof requestAnimationFrame === 'function') {
        raf = requestAnimationFrame(() => {
          if (!cancelled) reveal()
        })
      } else {
        reveal()
      }
    }
    const requestFrame = (video as FrameCallbackVideo).requestVideoFrameCallback?.bind(video)
    if (typeof requestFrame === 'function') {
      handle = requestFrame(() => reveal())
    }
    // Decodable-data signals: cover the rVFC path too, so a callback that
    // never fires (blocked autoplay, background tab, browser quirk) cannot
    // strand the cover over a ready element.
    const onDataSignal = () => {
      if (dataReady()) revealViaCompositor()
    }
    // Real-playback signals: a playing element IS presenting frames by
    // definition. The cover must never sit over a video that plays behind
    // it, even if every frame callback and readiness probe failed.
    const onPlaybackSignal = () => {
      if (!video.ended) reveal()
    }
    video.addEventListener('loadeddata', onDataSignal)
    video.addEventListener('canplay', onDataSignal)
    video.addEventListener('playing', onPlaybackSignal)
    video.addEventListener('timeupdate', onPlaybackSignal)
    if (dataReady()) revealViaCompositor()
    return () => {
      cancelled = true
      if (raf) cancelAnimationFrame(raf)
      if (handle !== undefined) {
        (video as FrameCallbackVideo).cancelVideoFrameCallback?.(handle)
      }
      video.removeEventListener('loadeddata', onDataSignal)
      video.removeEventListener('canplay', onDataSignal)
      video.removeEventListener('playing', onPlaybackSignal)
      video.removeEventListener('timeupdate', onPlaybackSignal)
    }
  }, [gateKey])

  // Keep the requested playback speed applied across source loads and changes.
  useEffect(() => {
    const video = videoRef.current
    if (video) {
      video.playbackRate = playbackRate
    }
  }, [playbackRate, phase.kind])

  // Manual re-check of media status. Status lookup only — never a
  // preparation request.
  const retryStatusCheck = () => setRetryEpoch((epoch) => epoch + 1)

  // Explicit user action: request preparation via the authoritative
  // endpoint (only where can_request allows it). Guarded against duplicate
  // submission from double-click, rerender, or repeated retries.
  const requestMedia = async () => {
    if (requestingRef.current) return
    requestingRef.current = true
    setIsRequesting(true)
    try {
      const data = await requestMediaRendition(videoUuid, 'proxy_720p')
      applyStatus(data)
    } catch {
      setPhase({
        kind: 'prepare-failed',
        message: null,
        fallback: 'requestFailed',
      })
    } finally {
      requestingRef.current = false
      setIsRequesting(false)
    }
  }

  // Autoplay with sound is blocked by browsers until the user has interacted
  // with the domain (NotAllowedError). Since the clip source arrives
  // asynchronously (after the media-status lookup), the autoPlay attribute
  // alone never starts playback — and the previous fire-and-forget play()
  // left the clip paused when sound was blocked. Try with sound first to
  // preserve sound-by-default, then fall back to muted autoplay so the clip
  // still starts. A muted fallback arms sound restoration on the next user
  // gesture (see below), so scrolled-to clips don't stay muted forever.
  const attemptImmersiveAutoplay = (video: HTMLVideoElement) => {
    try {
      const attempt = video.play()
      if (attempt && typeof attempt.catch === 'function') {
        attempt.catch((error: unknown) => {
          // A source switch (seeded preview URL → authoritative status URL)
          // aborts the in-flight play() with AbortError: a fresh load is
          // already underway and its own loadedmetadata/canplay handlers
          // will start it. Retrying here would only race that load, and the
          // muted fallback below would needlessly steal sound-by-default.
          const name = (error as { name?: unknown } | null)?.name
          if (name === 'AbortError') return
          try {
            video.muted = true
          } catch {
            /* ignore */
          }
          // Flagged for gesture restoration: the first tap/keypress with the
          // fallback still in force brings sound back automatically.
          setAutoMuted(true)
          try {
            const retry = video.play()
            if (retry && typeof retry.catch === 'function') retry.catch(() => {})
          } catch {
            /* ignore */
          }
        })
      }
    } catch {
      /* play() threw synchronously — leave the native affordance */
    }
  }

  // Sound-by-default restoration: browsers that blocked the unmuted start
  // leave the clip muted, and nothing would ever unmute it again — every
  // scrolled-to dive would stay silent until the viewer finds the mute
  // button. The first user gesture (tap, click, keypress) with OUR fallback
  // still in force restores sound (and resumes if stalled). A manual unmute
  // via the transport clears the flag through volumechange, so this never
  // fights an intentional mute; it only undoes what the fallback imposed.
  useEffect(() => {
    if (!immersive || !autoMuted) return
    const video = videoRef.current
    if (!video) return
    const restore = (event: Event) => {
      // Control taps keep their own semantics: pressing the transport's
      // Unmute button must toggle to unmuted, not be pre-empted by an
      // automatic unmute that its click then flips back to muted. Only
      // taps on the content surface (the .clip-gesture layer over the
      // video) restore sound. The gesture layer is itself a button, so it
      // is explicitly allowed back in.
      const target = event.target as HTMLElement | null
      const control = target?.closest?.('button')
      if (control && !control.classList.contains('clip-gesture')) return
      const current = videoRef.current
      if (current && current.muted) {
        current.muted = false
        if (current.paused && !current.ended) {
          try {
            const attempt = current.play()
            if (attempt && typeof attempt.catch === 'function') attempt.catch(() => {})
          } catch {
            /* leave the native affordance */
          }
        }
      }
      setAutoMuted(false)
    }
    const onVolume = () => {
      if (!videoRef.current?.muted) setAutoMuted(false)
    }
    document.addEventListener('pointerdown', restore, true)
    document.addEventListener('keydown', restore, true)
    video.addEventListener('volumechange', onVolume)
    return () => {
      document.removeEventListener('pointerdown', restore, true)
      document.removeEventListener('keydown', restore, true)
      video.removeEventListener('volumechange', onVolume)
    }
  }, [immersive, autoMuted, videoUuid, retryEpoch])

  const handleLoadedMetadata = () => {
    const video = videoRef.current
    if (video) {
      if (video.videoHeight) onAspectRatioChange?.(video.videoWidth / video.videoHeight)
      video.playbackRate = playbackRate
      if (immersive) attemptImmersiveAutoplay(video)
    }
  }

  const handleCanPlay = () => {
    const video = videoRef.current
    // Startup-only safety net for the case where loadedmetadata fired before
    // playback was possible. Never overrides an intentional pause: once the
    // clip has played or the viewer has paused, later canplay events (e.g.
    // after seeking) must not resume playback.
    if (
      video &&
      immersive &&
      video.paused &&
      !video.ended &&
      !hasPlayedRef.current &&
      !userPausedRef.current
    ) {
      attemptImmersiveAutoplay(video)
    }
  }

  const handlePlay = () => {
    hasPlayedRef.current = true
  }

  const handlePause = () => {
    userPausedRef.current = true
  }

  const handleDecodeError = () => {
    if (phase.kind === 'ready') setDecodeError(true)
  }

  // Retry playback by re-checking status rather than reloading the same
  // source: the backend may now point at a different rendition, and B2
  // grants are short-lived presigned redirects. Never creates a new media
  // job; preparation authority stays with the backend status.
  const retryPlayback = () => {
    setDecodeError(false)
    // The decodeError flip reopens a fresh load generation. The src is
    // unchanged so nothing would reload on its own: flag a real element
    // restart, and the cover holds until the source re-presents.
    needsRestartRef.current = true
    retryStatusCheck()
  }

  const stateLabel = (state: string) =>
    PREPARATION_STATE_KEYS.includes(state)
      ? t(`videoPlayer.states.${state}`)
      : preparationLabel(state)

  const preparing = phase.kind === 'preparing' ? phase : null
  const preparingText = preparing
    ? preparing.stopped
      ? t('videoPlayer.statusChecksStopped', { state: stateLabel(preparing.state) })
      : stale
        ? t('videoPlayer.connectionInterrupted', { state: stateLabel(preparing.state) })
        : preparing.longRunning
          ? t('videoPlayer.stillPreparing')
          : t('videoPlayer.preparingMedia', { state: stateLabel(preparing.state) })
    : null

  // The incoming-clip cover holds from the first paint — including a poster-
  // only seed whose status lookup is still checking and an in-flight
  // preparation — until the current source presents its first frame. Decode
  // failures hand over to the load-failed state instead.
  const coverHeld =
    immersive &&
    !decodeError &&
    !framePresented &&
    (phase.kind === 'checking' || phase.kind === 'preparing' || phase.kind === 'ready')

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      {/* Unauthenticated: session expired or never set — prompt to sign in. */}
      {!authChecking && !user && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80 px-6">
          <div className="max-w-sm text-center">
            <LogIn className="mx-auto mb-3 h-10 w-10 text-app-accent" />
            <p className="mb-2 font-semibold text-app-text">{t('videoPlayer.signInToPlay')}</p>
            <p className="mb-4 text-sm text-app-muted">{t('videoPlayer.sessionExpired')}</p>
            <Link
              to="/login"
              state={{ from: window.location.pathname }}
              className="inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated"
            >
              <LogIn className="h-4 w-4" />
              {t('videoPlayer.signIn')}
            </Link>
          </div>
        </div>
      )}

      {/* Native controls remain available in embedded analysis views. */}
      <video
        ref={videoRef}
        className={`block h-full w-full bg-black ${immersive ? "clip-video" : "object-contain"}`}
        src={phase.kind === 'ready' ? phase.src : undefined}
        controls={!immersive}
        autoPlay={immersive}
        loop={immersive}
        playsInline
        onLoadedMetadata={handleLoadedMetadata}
        onCanPlay={handleCanPlay}
        onPlay={handlePlay}
        onPause={handlePause}
        onError={handleDecodeError}
        preload={immersive ? 'auto' : 'metadata'}
        poster={posterSrc || undefined}
        aria-label={t('videoPlayer.videoAria', { code: diveCode, height })}
      />

      {/* Incoming-clip cover: the cached poster held above the video from
          the first paint until THIS source presents its first frame — the
          same poster bytes and full-bleed cover crop the pager neighbor
          frames show, so opening and swiping hand off without a black gap.
          Missing or failed posters get an honest non-black placeholder. */}
      {coverHeld && (
        <div className="clip-cover" aria-hidden="true" data-testid="clip-cover">
          {posterSrc && !posterFailed ? (
            <img
              src={posterSrc}
              alt=""
              draggable={false}
              onError={() => setPosterFailed(true)}
            />
          ) : (
            <div className="clip-cover-empty">
              <ImageOff aria-hidden="true" size={28} />
              <p>{t('videoPlayer.posterUnavailable')}</p>
            </div>
          )}
        </div>
      )}

      {immersive && phase.kind === 'ready' && !decodeError && <ImmersiveControls videoRef={videoRef} playbackRate={playbackRate} mediaPresented={framePresented} onLike={onLike} onNavigate={onNavigate} dragEnabled={dragEnabled} onDragUpdate={onDragUpdate} onDragEnd={onDragEnd} onPinchStart={onPinchStart} onPinchUpdate={onPinchUpdate} onPinchEnd={onPinchEnd} />}

      {/* Failed initial status lookup that did NOT end playback (a seeded
          warm clip): a separate, non-covering status check affordance. */}
      {statusUnknown && phase.kind === 'ready' && !decodeError && (
        <div
          className="absolute inset-x-4 bottom-24 z-20 flex items-center justify-center gap-3 rounded-lg bg-black/60 px-3 py-2"
          role="alert"
        >
          <WifiOff className="hidden h-4 w-4 text-app-muted sm:inline" />
          <p className="text-xs text-app-text">{t('videoPlayer.statusCheckFailed')}</p>
          <button
            type="button"
            onClick={retryStatusCheck}
            className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-3 py-1 text-xs font-semibold text-app-accent"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t('videoPlayer.retryStatusCheck')}
          </button>
        </div>
      )}

      {phase.kind === 'ready' && !decodeError && (
        <p className="sr-only" role="status">
          {t('videoPlayer.mediaReady')}
        </p>
      )}

      {/* Initial status lookup in progress. */}
      {phase.kind === 'checking' && (
        <div
          className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60"
          role="status"
        >
          <div className="ops-running-icon h-10 w-10 rounded-full border-4 border-app-accent border-t-transparent"></div>
          <p className="mt-3 text-sm text-app-text">{t('videoPlayer.checking')}</p>
          {lastPreparingStateRef.current && (
            <p className="mt-1 text-xs text-app-muted">
              {t('videoPlayer.lastKnownState', { state: stateLabel(lastPreparingStateRef.current) })}
            </p>
          )}
        </div>
      )}

      {/* Active preparation: named backend states, honest connectivity. */}
      {preparing && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60">
          {!preparing.stopped && (
            <div className="ops-running-icon h-10 w-10 rounded-full border-4 border-app-accent border-t-transparent"></div>
          )}
          <div
            className="absolute inset-x-4 bottom-6 text-center"
            role={preparing.stopped ? 'alert' : 'status'}
          >
            <p className="text-sm text-app-text">{preparingText}</p>
            {(preparing.stopped || preparing.longRunning) && (
              <button
                type="button"
                onClick={retryStatusCheck}
                className="touch-target mt-3 inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated"
              >
                <RefreshCw className="h-4 w-4" />
                {preparing.stopped ? t('videoPlayer.checkStatusAgain') : t('videoPlayer.checkStatusNow')}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Terminal transport failure of the initial status lookup. */}
      {phase.kind === 'transport-failed' && (
        <div
          className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80"
          role="alert"
        >
          <div className="max-w-sm px-6 text-center">
            <WifiOff className="mx-auto mb-3 h-10 w-10 text-app-muted" />
            <p className="mb-4 font-semibold text-app-text">
              {t('videoPlayer.statusCheckFailed')}
            </p>
            <button
              type="button"
              onClick={retryStatusCheck}
              className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated"
            >
              <RefreshCw className="h-4 w-4" />
              {t('videoPlayer.retryStatusCheck')}
            </button>
          </div>
        </div>
      )}

      {/* Backend-reported preparation failure, or a failed prepare request. */}
      {phase.kind === 'prepare-failed' && (
        <div
          className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80"
          role="alert"
        >
          <div className="max-w-sm px-6 text-center">
            <p className="mb-2 text-app-text">{t('videoPlayer.noVideo')}</p>
            <p className="mb-4 text-sm text-app-muted">{phase.message || t(`videoPlayer.${phase.fallback}`)}</p>
            {canRequest && (
              <button
                type="button"
                onClick={requestMedia}
                disabled={isRequesting}
                className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated disabled:cursor-not-allowed disabled:opacity-60"
              >
                <DownloadCloud className="h-4 w-4" />
                {isRequesting ? t('videoPlayer.requesting') : t('videoPlayer.retryPrepare')}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Video decode/load failure of an otherwise ready clip. */}
      {phase.kind === 'ready' && decodeError && (
        <div
          className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80"
          role="alert"
        >
          <div className="max-w-sm px-6 text-center">
            <p className="mb-4 font-semibold text-app-text">
              {t('videoPlayer.loadFailed')}
            </p>
            <button
              type="button"
              onClick={retryPlayback}
              className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated"
            >
              <RefreshCw className="h-4 w-4" />
              {t('videoPlayer.tryAgain')}
            </button>
          </div>
        </div>
      )}

      {/* Clip exists but no rendition is prepared yet — explicit action. */}
      {phase.kind === 'not-cached' && canRequest && (
        <div
          className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80 px-6"
          role="status"
        >
          <div className="max-w-sm text-center">
            <Clock className="mx-auto mb-3 h-10 w-10 text-app-accent" />
            <p className="mb-4 font-semibold text-app-text">
              {t('videoPlayer.notCached')}
            </p>
            <button
              type="button"
              onClick={requestMedia}
              disabled={isRequesting}
              className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated disabled:cursor-not-allowed disabled:opacity-60"
            >
              <DownloadCloud className="h-4 w-4" />
              {isRequesting ? t('videoPlayer.requesting') : t('videoPlayer.prepareClip')}
            </button>
          </div>
        </div>
      )}

      {/* Media exists but cannot be requested right now — say so honestly. */}
      {phase.kind === 'not-cached' && !canRequest && (
        <div
          className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80 px-6"
          role="status"
        >
          <p className="max-w-sm text-center text-sm text-app-muted">
            {t('videoPlayer.noPlayable')}
          </p>
        </div>
      )}
    </div>
  )
}

export default DiveVideoPlayer
