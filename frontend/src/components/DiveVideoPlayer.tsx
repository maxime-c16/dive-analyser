import React, { useRef, useState, useEffect } from 'react'
import { Clock, DownloadCloud, LogIn } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import {
  getMediaStatus,
  getPlaybackUrlFromStatus,
  getPosterUrlFromStatus,
  requestMedia as requestMediaRendition,
  type MediaStatus,
} from '../services/mediaApi'

interface DiveVideoPlayerProps {
  diveCode: string
  height: string
  videoUuid: string
  playbackRate?: number
}

function DiveVideoPlayer({ diveCode, height, videoUuid, playbackRate = 1 }: DiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [videoSrc, setVideoSrc] = useState<string | null>(null)
  const [posterSrc, setPosterSrc] = useState<string | null>(null)
  const [mediaStatus, setMediaStatus] = useState<string | null>(null)
  const [canRequest, setCanRequest] = useState(false)
  const [isRequesting, setIsRequesting] = useState(false)
  const pollRef = useRef<number | null>(null)
  const { user, checking: authChecking } = useAuth()

  useEffect(() => {
    let cancelled = false

    const applyStatus = (data: MediaStatus) => {
      if (cancelled) return
      setMediaStatus(data.status || null)
      setCanRequest(Boolean(data.can_request))
      setPosterSrc(getPosterUrlFromStatus(data))

      const playbackUrl = getPlaybackUrlFromStatus(data)
      if (data.status === 'ready' && playbackUrl) {
        setVideoSrc(playbackUrl)
        setIsLoading(false)
        setError(null)
        if (pollRef.current) {
          clearInterval(pollRef.current)
          pollRef.current = null
        }
        return
      }

      if (['queued', 'waiting_for_mac', 'claimed', 'exporting', 'transcoding', 'uploading', 'verifying'].includes(data.status)) {
        setIsLoading(true)
        setError(null)
        startPolling()
        return
      }

      if (data.status === 'failed' || data.status === 'unavailable') {
        setError(data.job?.last_error || 'Media preparation failed')
        setIsLoading(false)
        if (pollRef.current) {
          clearInterval(pollRef.current)
          pollRef.current = null
        }
        return
      }

      setVideoSrc(null)
      setIsLoading(false)
      setError(null)
    }

    const fetchStatus = async () => {
      const data = await getMediaStatus(videoUuid)
      applyStatus(data)
      return data
    }

    const startPolling = () => {
      if (pollRef.current) return
      pollRef.current = window.setInterval(async () => {
        try {
          await fetchStatus()
        } catch (e) {
          console.debug('Media status polling failed', e)
        }
      }, 3000)
    }

    const check = async () => {
      try {
        await fetchStatus()
      } catch (e) {
        if (!cancelled) {
          setError('Error checking media availability')
          setIsLoading(false)
        }
      }
    }

    check()

    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    }
  }, [videoUuid])

  useEffect(() => {
    if (videoRef.current && videoSrc) {
      videoRef.current.load()
    }
  }, [videoSrc])

  // Keep the requested playback speed applied across source loads and changes.
  useEffect(() => {
    const video = videoRef.current
    if (video) video.playbackRate = playbackRate
  }, [playbackRate, videoSrc])

  const requestMedia = async () => {
    try {
      setIsRequesting(true)
      setError(null)
      setIsLoading(true)
      const data = await requestMediaRendition(videoUuid, 'proxy_360p')
      setMediaStatus(data.status || null)
      setCanRequest(Boolean(data.can_request))
      setPosterSrc(getPosterUrlFromStatus(data))
      const playbackUrl = getPlaybackUrlFromStatus(data)
      if (data.status === 'ready' && playbackUrl) {
        setVideoSrc(playbackUrl)
        setIsLoading(false)
      } else {
        if (!pollRef.current) {
          pollRef.current = window.setInterval(async () => {
            try {
              const statusData = await getMediaStatus(videoUuid)
              setMediaStatus(statusData.status || null)
              setPosterSrc(getPosterUrlFromStatus(statusData))
              const pollingPlaybackUrl = getPlaybackUrlFromStatus(statusData)
              if (statusData.status === 'ready' && pollingPlaybackUrl) {
                setVideoSrc(pollingPlaybackUrl)
                setIsLoading(false)
                if (pollRef.current) {
                  clearInterval(pollRef.current)
                  pollRef.current = null
                }
              }
            } catch (e) {
              console.debug('Media status polling failed', e)
            }
          }, 3000)
        }
      }
    } catch (e) {
      setError('Could not request media preparation')
      setIsLoading(false)
    } finally {
      setIsRequesting(false)
    }
  }

  const handleLoadedMetadata = () => {
    const video = videoRef.current
    if (video) video.playbackRate = playbackRate
    setIsLoading(false)
  }

  const handleError = () => {
    setError('Video could not be loaded')
    setIsLoading(false)
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      {/* Unauthenticated: session expired or never set — prompt to sign in. */}
      {!authChecking && !user && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80 px-6">
          <div className="max-w-sm text-center">
            <LogIn className="mx-auto mb-3 h-10 w-10 text-app-accent" />
            <p className="mb-2 font-semibold text-app-text">Sign in to play</p>
            <p className="mb-4 text-sm text-app-muted">
              Your session has expired. Sign in to watch your clips.
            </p>
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

      {/* Safari owns the complete control surface for playable clips. */}
      <video
        ref={videoRef}
        className="block h-full w-full bg-black object-contain"
        src={videoSrc || undefined}
        controls
        playsInline
        onLoadedMetadata={handleLoadedMetadata}
        onError={handleError}
        preload="metadata"
        poster={posterSrc || undefined}
        aria-label={`${diveCode} ${height} dive video`}
      />

      {/* App UI is visible only before a playable source exists. */}
      {isLoading && !videoSrc && !error && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/60">
          <div className="ops-running-icon h-10 w-10 rounded-full border-4 border-app-accent border-t-transparent"></div>
          {mediaStatus && mediaStatus !== 'ready' && (
            <div className="absolute bottom-6 text-center text-sm text-app-text">
              Preparing media: {mediaStatus.replace(/_/g, ' ')}
            </div>
          )}
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80">
          <div className="max-w-sm px-6 text-center">
            <p className="mb-2 text-app-text">No video available</p>
            <p className="mb-4 text-sm text-app-muted">{error}</p>
            {canRequest && (
              <button
                type="button"
                onClick={requestMedia}
                disabled={isRequesting}
                className="inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated disabled:cursor-not-allowed disabled:opacity-60"
              >
                <DownloadCloud className="h-4 w-4" />
                {isRequesting ? 'Requesting…' : 'Retry prepare'}
              </button>
            )}
          </div>
        </div>
      )}

      {!videoSrc && !isLoading && canRequest && !error && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80 px-6">
          <div className="max-w-sm text-center">
            <Clock className="mx-auto mb-3 h-10 w-10 text-app-accent" />
            <p className="mb-2 font-semibold text-app-text">Clip is not cached yet</p>
            <p className="mb-4 text-sm text-app-muted">
              Request a lightweight proxy. The Mac agent will prepare it when online.
            </p>
            <button
              type="button"
              onClick={requestMedia}
              disabled={isRequesting}
              className="inline-flex items-center gap-2 rounded-lg border border-app-accent bg-app-panel px-4 py-2 font-semibold text-app-accent transition hover:bg-app-panel-elevated disabled:cursor-not-allowed disabled:opacity-60"
            >
              <DownloadCloud className="h-4 w-4" />
              {isRequesting ? 'Requesting…' : 'Prepare clip'}
            </button>
          </div>
        </div>
      )}

    </div>
  )
}

export default DiveVideoPlayer
