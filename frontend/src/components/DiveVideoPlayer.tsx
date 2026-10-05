import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Clock, DownloadCloud, LogIn, RefreshCw, WifiOff } from 'lucide-react'
import { Link } from 'react-router-dom'
import ImmersiveControls from './clip-viewer/ImmersiveControls'
import { useAuth } from '../contexts/AuthContext'
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
  | { kind: 'prepare-failed'; message: string }
  | { kind: 'not-cached' }
  | { kind: 'transport-failed' }

function preparationLabel(state: string) {
  return state.replace(/_/g, ' ')
}

interface DiveVideoPlayerProps {
  diveCode: string
  height: string
  videoUuid: string
  playbackRate?: number
  immersive?: boolean
  onAspectRatioChange?: (ratio: number) => void
  onLike?: () => void
  onNavigate?: (direction: -1 | 1) => void
}

function DiveVideoPlayer({ diveCode, height, videoUuid, playbackRate = 1, immersive = false, onAspectRatioChange, onLike = () => {}, onNavigate = () => {} }: DiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const { user, checking: authChecking } = useAuth()

  const [phase, setPhase] = useState<Phase>({ kind: 'checking' })
  const [stale, setStale] = useState(false)
  const [posterSrc, setPosterSrc] = useState<string | null>(null)
  const [canRequest, setCanRequest] = useState(false)
  const [decodeError, setDecodeError] = useState(false)
  const [isRequesting, setIsRequesting] = useState(false)
  const [retryEpoch, setRetryEpoch] = useState(0)

  const failuresRef = useRef(0)
  const preparingSinceRef = useRef<number | null>(null)
  const lastPreparingLabelRef = useRef<string | null>(null)
  const requestingRef = useRef(false)

  const applyStatus = useCallback((data: MediaStatus) => {
    setCanRequest(Boolean(data.can_request))
    setPosterSrc(getPosterUrlFromStatus(data))

    const playbackUrl = getPlaybackUrlFromStatus(data)
    if (data.status === 'ready' && playbackUrl) {
      preparingSinceRef.current = null
      lastPreparingLabelRef.current = null
      setPhase({ kind: 'ready', src: playbackUrl })
      return
    }

    if (ACTIVE_PREPARATION_STATES.includes(data.status)) {
      if (preparingSinceRef.current === null) preparingSinceRef.current = Date.now()
      const longRunning =
        preparingSinceRef.current !== null &&
        Date.now() - preparingSinceRef.current > LONG_PREPARATION_MS
      lastPreparingLabelRef.current = preparationLabel(data.status)
      setPhase({ kind: 'preparing', state: data.status, longRunning, stopped: false })
      return
    }

    if (data.status === 'failed' || data.status === 'unavailable') {
      preparingSinceRef.current = null
      lastPreparingLabelRef.current = null
      setPhase({
        kind: 'prepare-failed',
        message: data.job?.last_error || 'Media preparation failed',
      })
      return
    }

    preparingSinceRef.current = null
    lastPreparingLabelRef.current = null
    setPhase({ kind: 'not-cached' })
  }, [])

  // Initial status lookup with a bounded automatic retry window. Terminal
  // transport failure is actionable (manual retry) — never an endless
  // spinner, and never an automatic preparation request.
  useEffect(() => {
    let cancelled = false
    failuresRef.current = 0
    setStale(false)
    setDecodeError(false)
    setPosterSrc(null)
    setPhase({ kind: 'checking' })

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
          setPhase({ kind: 'transport-failed' })
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

  useEffect(() => {
    if (videoRef.current && phase.kind === 'ready') {
      videoRef.current.load()
    }
  }, [phase.kind === 'ready' ? phase.src : null])

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
        message: 'Could not request media preparation',
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
  // still starts; the viewer can unmute from ImmersiveControls.
  const attemptImmersiveAutoplay = (video: HTMLVideoElement) => {
    try {
      const attempt = video.play()
      if (attempt && typeof attempt.catch === 'function') {
        attempt.catch(() => {
          try {
            video.muted = true
          } catch {
            /* ignore */
          }
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
    // Safety net for the case where loadedmetadata fired before playback was
    // possible: only nudge a still-paused immersive clip.
    if (video && immersive && video.paused && !video.ended) {
      attemptImmersiveAutoplay(video)
    }
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
    retryStatusCheck()
  }

  const preparing = phase.kind === 'preparing' ? phase : null
  const preparingText = preparing
    ? preparing.stopped
      ? `${preparationLabel(preparing.state)} — status checks stopped`
      : stale
        ? `${preparationLabel(preparing.state)} — connection interrupted`
        : preparing.longRunning
          ? 'Still preparing'
          : `Preparing media: ${preparationLabel(preparing.state)}`
    : null

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      {/* Unauthenticated: session expired or never set — prompt to sign in. */}
      {!authChecking && !user && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80 px-6">
          <div className="max-w-sm text-center">
            <LogIn className="mx-auto mb-3 h-10 w-10 text-app-accent" />
            <p className="mb-2 font-semibold text-app-text">Sign in to play</p>
            <p className="mb-4 text-sm text-app-muted">Session expired.</p>
            <Link
              to="/login"
              state={{ from: window.location.pathname }}
              className="inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated"
            >
              <LogIn className="h-4 w-4" />
              Sign in
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
        onError={handleDecodeError}
        preload={immersive ? 'auto' : 'metadata'}
        poster={posterSrc || undefined}
        aria-label={`${diveCode} ${height} dive video`}
      />

      {immersive && phase.kind === 'ready' && !decodeError && <ImmersiveControls videoRef={videoRef} playbackRate={playbackRate} onLike={onLike} onNavigate={onNavigate} />}

      {phase.kind === 'ready' && !decodeError && (
        <p className="sr-only" role="status">
          Media ready.
        </p>
      )}

      {/* Initial status lookup in progress. */}
      {phase.kind === 'checking' && (
        <div
          className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60"
          role="status"
        >
          <div className="ops-running-icon h-10 w-10 rounded-full border-4 border-app-accent border-t-transparent"></div>
          <p className="mt-3 text-sm text-app-text">Checking…</p>
          {lastPreparingLabelRef.current && (
            <p className="mt-1 text-xs text-app-muted">
              Last known state: {lastPreparingLabelRef.current}
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
                {preparing.stopped ? 'Check status again' : 'Check status now'}
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
              Media status check failed
            </p>
            <button
              type="button"
              onClick={retryStatusCheck}
              className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated"
            >
              <RefreshCw className="h-4 w-4" />
              Retry status check
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
            <p className="mb-2 text-app-text">No video available</p>
            <p className="mb-4 text-sm text-app-muted">{phase.message}</p>
            {canRequest && (
              <button
                type="button"
                onClick={requestMedia}
                disabled={isRequesting}
                className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated disabled:cursor-not-allowed disabled:opacity-60"
              >
                <DownloadCloud className="h-4 w-4" />
                {isRequesting ? 'Requesting…' : 'Retry prepare'}
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
              Video failed to load
            </p>
            <button
              type="button"
              onClick={retryPlayback}
              className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated"
            >
              <RefreshCw className="h-4 w-4" />
              Try again
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
              Clip not cached
            </p>
            <button
              type="button"
              onClick={requestMedia}
              disabled={isRequesting}
              className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated disabled:cursor-not-allowed disabled:opacity-60"
            >
              <DownloadCloud className="h-4 w-4" />
              {isRequesting ? 'Requesting…' : 'Prepare clip'}
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
            No playable media for this clip right now.
          </p>
        </div>
      )}
    </div>
  )
}

export default DiveVideoPlayer
