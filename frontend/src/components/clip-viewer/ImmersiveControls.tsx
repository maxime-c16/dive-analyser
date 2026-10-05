import { useEffect, useRef, useState, type RefObject } from "react";
import { Heart, Pause, Play, Volume2, VolumeX } from "lucide-react";

/** One gesture owner keeps taps, double taps, holds and swipes mutually exclusive. */
export default function ImmersiveControls({
  videoRef,
  playbackRate,
  onLike,
  onNavigate,
}: {
  videoRef: RefObject<HTMLVideoElement>;
  playbackRate: number;
  onLike: () => void;
  onNavigate: (direction: -1 | 1) => void;
}) {
  const [paused, setPaused] = useState(false);
  const [muted, setMuted] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [holding, setHolding] = useState(false);
  const [heart, setHeart] = useState(false);
  const holdTimer = useRef<ReturnType<typeof setTimeout>>();
  const tapTimer = useRef<ReturnType<typeof setTimeout>>();
  const heartTimer = useRef<ReturnType<typeof setTimeout>>();
  const gesture = useRef<{
    x: number;
    y: number;
    held: boolean;
    moved: boolean;
  } | null>(null);
  const rateRef = useRef(playbackRate);
  rateRef.current = playbackRate;

  const toggle = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => setPaused(true));
    else video.pause();
  };
  const like = () => {
    onLike();
    setHeart(true);
    clearTimeout(heartTimer.current);
    heartTimer.current = setTimeout(() => setHeart(false), 800);
  };
  const cancelHold = () => {
    clearTimeout(holdTimer.current);
    if (videoRef.current) videoRef.current.playbackRate = rateRef.current;
    setHolding(false);
  };
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const sync = () => {
      setPaused(video.paused);
      setMuted(video.muted);
      setDuration(Number.isFinite(video.duration) ? video.duration : 0);
      setProgress(video.currentTime || 0);
    };
    const events = [
      "play",
      "pause",
      "volumechange",
      "timeupdate",
      "loadedmetadata",
    ];
    events.forEach((event) => video.addEventListener(event, sync));
    sync();
    return () => {
      events.forEach((event) => video.removeEventListener(event, sync));
      clearTimeout(holdTimer.current);
      clearTimeout(tapTimer.current);
      clearTimeout(heartTimer.current);
      video.playbackRate = rateRef.current;
    };
  }, [videoRef]);

  return (
    <>
      <button
        type="button"
        className="clip-gesture"
        aria-label={paused ? "Play video" : "Pause video"}
        onContextMenu={(event) => event.preventDefault()}
        onPointerDown={(event) => {
          if (!event.isPrimary || event.button !== 0) return;
          event.currentTarget.setPointerCapture?.(event.pointerId);
          gesture.current = {
            x: event.clientX,
            y: event.clientY,
            held: false,
            moved: false,
          };
          holdTimer.current = setTimeout(() => {
            if (!gesture.current || gesture.current.moved) return;
            clearTimeout(tapTimer.current);
            tapTimer.current = undefined;
            gesture.current.held = true;
            if (videoRef.current) videoRef.current.playbackRate = 2;
            setHolding(true);
          }, 350);
        }}
        onPointerMove={(event) => {
          if (!event.isPrimary) return;
          const start = gesture.current;
          if (
            start &&
            Math.hypot(event.clientX - start.x, event.clientY - start.y) > 12
          ) {
            start.moved = true;
            cancelHold();
          }
        }}
        onPointerCancel={() => {
          gesture.current = null;
          cancelHold();
        }}
        onLostPointerCapture={() => {
          gesture.current = null;
          cancelHold();
        }}
        onPointerUp={(event) => {
          if (!event.isPrimary) return;
          const start = gesture.current;
          gesture.current = null;
          cancelHold();
          if (!start || start.held) return;
          const dy = event.clientY - start.y;
          const dx = event.clientX - start.x;
          if (Math.abs(dy) > 65 && Math.abs(dy) > Math.abs(dx) * 1.3) {
            clearTimeout(tapTimer.current);
            tapTimer.current = undefined;
            onNavigate(dy < 0 ? 1 : -1);
            return;
          }
          if (start.moved) return;
          if (tapTimer.current) {
            clearTimeout(tapTimer.current);
            tapTimer.current = undefined;
            like();
          } else {
            tapTimer.current = setTimeout(() => {
              tapTimer.current = undefined;
              toggle();
            }, 260);
          }
        }}
        onClick={(event) => {
          if (event.detail === 0) toggle();
        }}
      >
        {paused && (
          <span className="clip-play-indicator">
            <Play size={30} fill="currentColor" />
          </span>
        )}
        {heart && (
          <Heart className="clip-heart" size={84} fill="currentColor" />
        )}
        {holding && <span className="clip-speed-indicator">2× speed</span>}
      </button>
      <div className="clip-transport">
        <button
          type="button"
          aria-label={paused ? "Resume playback" : "Pause playback"}
          onClick={toggle}
        >
          {paused ? <Play size={18} /> : <Pause size={18} />}
        </button>
        <span className="clip-time">
          {Math.floor(progress)} / {Math.floor(duration)}s
        </span>
        <button
          type="button"
          aria-label={muted ? "Unmute video" : "Mute video"}
          onClick={() => {
            if (videoRef.current)
              videoRef.current.muted = !videoRef.current.muted;
          }}
        >
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
      </div>
      <input
        className="clip-progress"
        type="range"
        aria-label="Video position"
        min={0}
        max={duration || 1}
        step={0.01}
        value={progress}
        disabled={!duration}
        onChange={(event) => {
          if (videoRef.current)
            videoRef.current.currentTime = Number(event.target.value);
        }}
      />
    </>
  );
}
