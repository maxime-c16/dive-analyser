import React, { useRef, useState, useEffect } from 'react'
import { Clock, DownloadCloud } from 'lucide-react'
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
}

function DiveVideoPlayer({ diveCode, height, videoUuid }: DiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [videoSrc, setVideoSrc] = useState<string | null>(null)
  const [posterSrc, setPosterSrc] = useState<string | null>(null)
  const [mediaStatus, setMediaStatus] = useState<string | null>(null)
  const [canRequest, setCanRequest] = useState(false)
  const [isRequesting, setIsRequesting] = useState(false)
  const pollRef = useRef<number | null>(null)

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
    setIsLoading(false)
  }

  const handleError = () => {
    setError('Video could not be loaded')
    setIsLoading(false)
  }

  return (
    <div className="relative w-full h-full bg-black rounded-lg overflow-hidden group">
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
          <div className="w-10 h-10 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
          {mediaStatus && mediaStatus !== 'ready' && (
            <div className="absolute bottom-6 text-center text-gray-200 text-sm">
              Preparing media: {mediaStatus.replace(/_/g, ' ')}
            </div>
          )}
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80">
          <div className="text-center max-w-sm px-6">
            <p className="text-gray-300 mb-2">No video available</p>
            <p className="text-gray-500 text-sm mb-4">{error}</p>
            {canRequest && (
              <button
                type="button"
                onClick={requestMedia}
                disabled={isRequesting}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500 text-gray-950 font-semibold hover:bg-cyan-400 disabled:opacity-60 disabled:cursor-not-allowed transition"
              >
                <DownloadCloud className="w-4 h-4" />
                {isRequesting ? 'Requesting…' : 'Retry prepare'}
              </button>
            )}
          </div>
        </div>
      )}

      {!videoSrc && !isLoading && canRequest && !error && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-black/80 px-6">
          <div className="text-center max-w-sm">
            <Clock className="w-10 h-10 text-cyan-400 mx-auto mb-3" />
            <p className="text-gray-200 font-semibold mb-2">Clip is not cached yet</p>
            <p className="text-gray-500 text-sm mb-4">
              Request a lightweight proxy. The Mac agent will prepare it when online.
            </p>
            <button
              type="button"
              onClick={requestMedia}
              disabled={isRequesting}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500 text-gray-950 font-semibold hover:bg-cyan-400 disabled:opacity-60 disabled:cursor-not-allowed transition"
            >
              <DownloadCloud className="w-4 h-4" />
              {isRequesting ? 'Requesting…' : 'Prepare clip'}
            </button>
          </div>
        </div>
      )}

    </div>
  )
}

export default DiveVideoPlayer
