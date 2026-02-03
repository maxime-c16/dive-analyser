import React, { useRef, useState, useEffect } from 'react'
import { X, Play, Pause, Volume2, VolumeX } from 'lucide-react'

interface DiveVideoPlayerProps {
  diveCode: string
  height: string
  videoUuid: string
  onClose: () => void
}

function DiveVideoPlayer({ diveCode, height, videoUuid, onClose }: DiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [isMuted, setIsMuted] = useState(false)
  const [showControls, setShowControls] = useState(true)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const controlsTimeoutRef = useRef<NodeJS.Timeout>()
  const [videoSrc, setVideoSrc] = useState<string | null>(null)
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    console.log(`[DiveVideoPlayer] Loading video: ${videoUuid}`)
    const videoUrl = `/api/v1/videos/${videoUuid}`
    console.log(`[DiveVideoPlayer] URL: ${videoUrl}`)

    // Check availability and initiate download if needed
    let cancelled = false
    const startPolling = () => {
      if (pollRef.current) return
      pollRef.current = window.setInterval(async () => {
        try {
          const r = await fetch(`/api/v1/videos/check/${videoUuid}`)
          const d = await r.json()
          if (d.available) {
            setVideoSrc(videoUrl)
            setIsLoading(false)
            setDownloadStatus(null)
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
          } else if (d.status && d.status === 'failed') {
            setError('Download failed')
            setIsLoading(false)
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
          }
        } catch (e) {
          // ignore and continue polling
        }
      }, 3000)
    }

    const check = async () => {
      try {
        const res = await fetch(`/api/v1/videos/check/${videoUuid}`)
        const data = await res.json()
        if (data.available) {
          if (!cancelled) {
            setVideoSrc(videoUrl)
            setIsLoading(false)
            setDownloadStatus(null)
          }
        } else if (data.status && (data.status === 'queued' || data.status === 'downloading')) {
          if (!cancelled) {
            setDownloadStatus(data.status)
            setIsLoading(true)
            startPolling()
          }
        } else {
          // Not available; trigger backend to initiate download
          const g = await fetch(videoUrl, { method: 'GET' })
          if (g.status === 202) {
            if (!cancelled) {
              setDownloadStatus('downloading')
              setIsLoading(true)
              startPolling()
            }
          } else if (g.status === 200) {
            if (!cancelled) {
              setVideoSrc(videoUrl)
              setIsLoading(false)
            }
          } else {
            if (!cancelled) {
              setError('Video not available')
              setIsLoading(false)
            }
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError('Error checking video availability')
          setIsLoading(false)
        }
      }
    }

    check()

    // Auto-hide controls after 3 seconds of inactivity (trainer focus mode)
    const resetTimeout = () => {
      setShowControls(true)
      if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current)
      controlsTimeoutRef.current = setTimeout(() => setShowControls(false), 3000)
    }

    videoRef.current?.addEventListener('mousemove', resetTimeout)
    videoRef.current?.addEventListener('click', resetTimeout)

    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      videoRef.current?.removeEventListener('mousemove', resetTimeout)
      videoRef.current?.removeEventListener('click', resetTimeout)
      if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current)
    }
  }, [videoUuid])

  const handlePlayPause = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause()
      } else {
        videoRef.current.play()
      }
      setIsPlaying(!isPlaying)
    }
  }

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime)
    }
  }

  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration)
      console.log(`[DiveVideoPlayer] ✅ Metadata loaded: ${videoRef.current.duration}s`)
    }
    setIsLoading(false)
  }

  const handleLoadStart = () => {
    console.log(`[DiveVideoPlayer] Starting to load...`)
    setIsLoading(true)
  }

  const handleCanPlay = () => {
    console.log(`[DiveVideoPlayer] ✅ Can play!`)
  }

  const handleProgressChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newTime = parseFloat(e.target.value)
    if (videoRef.current) {
      videoRef.current.currentTime = newTime
      setCurrentTime(newTime)
    }
  }

  const handleVolumeToggle = () => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted
      setIsMuted(!isMuted)
    }
  }

  const handleError = (e: any) => {
    console.error(`[DiveVideoPlayer] ❌ Error:`, e)
    if (videoRef.current) {
      console.error(`[DiveVideoPlayer] Error code:`, videoRef.current.error?.code)
      console.error(`[DiveVideoPlayer] Error message:`, videoRef.current.error?.message)
    }
    setError('Video could not be loaded')
    setIsLoading(false)
  }

  const formatTime = (time: number) => {
    if (!time || isNaN(time)) return '0:00'
    const minutes = Math.floor(time / 60)
    const seconds = Math.floor(time % 60)
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }

  return (
    <div className="relative w-full h-full bg-black rounded-lg overflow-hidden group">
      {/* Video Element */}
      <video
        ref={videoRef}
        className="w-full h-full"
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onLoadStart={handleLoadStart}
        onCanPlay={handleCanPlay}
        onError={handleError}
        crossOrigin="anonymous"
        preload="metadata"
      >
        {videoSrc ? <source src={videoSrc} type="video/mp4" /> : null}
        Your browser does not support the video tag.
      </video>

      {/* Loading State */}
      {isLoading && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60">
          <div className="w-10 h-10 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
          {downloadStatus && (
            <div className="absolute bottom-6 text-center text-gray-200 text-sm">{downloadStatus === 'downloading' ? 'Downloading video…' : 'Queued for download'}</div>
          )}
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80">
          <div className="text-center">
            <p className="text-gray-300 mb-2">No video available</p>
            <p className="text-gray-500 text-sm">This dive video could not be loaded</p>
          </div>
        </div>
      )}

      {/* Controls Overlay */}
      {!error && (
        <>
          {/* Video Info Header */}
          <div className="absolute top-0 left-0 right-0 bg-gradient-to-b from-black/60 to-transparent p-4 z-10">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-white font-semibold">{diveCode}</p>
                <p className="text-gray-300 text-sm">{height}</p>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 hover:bg-black/40 rounded-lg transition"
              >
                <X className="w-5 h-5 text-gray-300" />
              </button>
            </div>
          </div>

          {/* Main Controls - Bottom */}
          <div
            className={`absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4 transition-opacity ${
              showControls ? 'opacity-100' : 'opacity-0 hover:opacity-100'
            }`}
          >
            {/* Progress Bar */}
            <div className="mb-4">
              <input
                type="range"
                min="0"
                max={duration || 0}
                value={currentTime}
                onChange={handleProgressChange}
                className="w-full h-1 bg-gray-700 rounded-full cursor-pointer appearance-none accent-cyan-500"
              />
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span>{formatTime(currentTime)}</span>
                <span>{formatTime(duration)}</span>
              </div>
            </div>

            {/* Control Buttons */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {/* Play/Pause Button */}
                <button
                  onClick={handlePlayPause}
                  className="p-2 hover:bg-white/20 rounded-lg transition"
                >
                  {isPlaying ? (
                    <Pause className="w-5 h-5 text-white" />
                  ) : (
                    <Play className="w-5 h-5 text-white" />
                  )}
                </button>

                {/* Volume Control */}
                <button
                  onClick={handleVolumeToggle}
                  className="p-2 hover:bg-white/20 rounded-lg transition"
                >
                  {isMuted ? (
                    <VolumeX className="w-5 h-5 text-gray-300" />
                  ) : (
                    <Volume2 className="w-5 h-5 text-gray-300" />
                  )}
                </button>
              </div>

              {/* Duration Display */}
              <span className="text-xs text-gray-400 font-mono">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            </div>
          </div>

          {/* Center Play Button (Click to Play) */}
          {!isPlaying && !error && (
            <button
              onClick={handlePlayPause}
              className="absolute inset-0 flex items-center justify-center transition-all hover:bg-black/20"
            >
              <div className="p-4 rounded-full bg-white/20 hover:bg-white/40 transition">
                <Play className="w-12 h-12 text-white fill-white" />
              </div>
            </button>
          )}
        </>
      )}
    </div>
  )
}

export default DiveVideoPlayer
