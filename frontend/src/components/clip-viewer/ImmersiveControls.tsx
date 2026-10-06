import { useEffect, useRef, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { Heart, Pause, Play, Volume2, VolumeX } from "lucide-react";

/** One gesture owner keeps taps, double taps, holds and swipes mutually exclusive. */
export interface FeedDragEnd {
  /** Finger displacement in px when the gesture ended (negative = swiped up). */
  dy: number;
  /** Release velocity in px/ms, signed like dy (0 when cancelled). */
  velocity: number;
  cancelled: boolean;
}

const DRAG_ENGAGE_PX = 10;

export default function ImmersiveControls({
  videoRef,
  playbackRate,
  mediaPresented = true,
  onLike,
  onNavigate,
  dragEnabled = false,
  onDragUpdate,
  onDragEnd,
  onPinchStart,
  onPinchUpdate,
  onPinchEnd,
}: {
  videoRef: RefObject<HTMLVideoElement>;
  playbackRate: number;
  /**
   * False until the video has presented its first real frame: the visible
   * play indicator, transport and scrub wait for that moment, while the
   * gesture surface (tap, double-tap like, hold, drag, pinch) stays live so
   * the pager handoff works over the incoming-clip cover.
   */
  mediaPresented?: boolean;
  onLike: () => void;
  onNavigate: (direction: -1 | 1) => void;
  /**
   * Feed-pager mode (mobile): a vertically-dominant drag is reported to the
   * parent frame-by-frame so the dive follows the finger, and the parent
   * decides commit vs spring-back on release. When set, the legacy
   * release-threshold swipe navigation is suppressed for consumed drags;
   * taps, double-tap likes and holds are unchanged.
   */
  dragEnabled?: boolean;
  onDragUpdate?: (dy: number) => void;
  onDragEnd?: (result: FeedDragEnd) => void;
  /**
   * Instagram-style pinch, reported live so the parent can make the video
   * follow the fingers: `ratio` is the current finger span over the span when
   * the second finger landed (<1 = closing, >1 = spreading). The parent owns
   * the visuals and decides what the release settles to.
   */
  onPinchStart?: () => void;
  onPinchUpdate?: (ratio: number) => void;
  onPinchEnd?: (cancelled: boolean) => void;
}) {
  const { t } = useTranslation();
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
    engaged: boolean;
    lastDy: number;
    samples: Array<{ y: number; t: number }>;
  } | null>(null);
  const dragEnabledRef = useRef(dragEnabled);
  dragEnabledRef.current = dragEnabled;
  const dragUpdateRef = useRef(onDragUpdate);
  dragUpdateRef.current = onDragUpdate;
  const dragEndRef = useRef(onDragEnd);
  dragEndRef.current = onDragEnd;
  const rateRef = useRef(playbackRate);
  rateRef.current = playbackRate;
  const pinchStartRef = useRef(onPinchStart);
  pinchStartRef.current = onPinchStart;
  const pinchUpdateRef = useRef(onPinchUpdate);
  pinchUpdateRef.current = onPinchUpdate;
  const pinchEndRef = useRef(onPinchEnd);
  pinchEndRef.current = onPinchEnd;
  // Every finger currently on the surface, and the span of an active pinch.
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ span: number } | null>(null);

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
  /** Release velocity over the trailing samples, signed like dy (px/ms). */
  const releaseVelocity = (samples: Array<{ y: number; t: number }>) => {
    if (samples.length < 2) return 0;
    const windowStart = samples[samples.length - 1].t - 120;
    let first = samples[0];
    for (const sample of samples) {
      if (sample.t >= windowStart) {
        first = sample;
        break;
      }
    }
    const last = samples[samples.length - 1];
    const dt = last.t - first.t;
    if (dt <= 0) return 0;
    return (last.y - first.y) / dt;
  };
  /**
   * Finish a drag-reported gesture. Returns true when the parent consumed
   * the gesture (caller must skip the legacy swipe/tap branches).
   */
  const endDragGesture = (cancelled: boolean) => {
    const start = gesture.current;
    gesture.current = null;
    cancelHold();
    if (!start || !start.engaged || !dragEnabledRef.current) return false;
    dragEndRef.current?.({
      dy: start.lastDy,
      velocity: cancelled ? 0 : releaseVelocity(start.samples),
      cancelled,
    });
    return true;
  };
  const pinchSpan = () => {
    const [a, b] = [...pointers.current.values()];
    return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
  };
  /** A second finger lands: the one-finger gesture (tap, hold, drag) is over. */
  const startPinch = () => {
    clearTimeout(tapTimer.current);
    tapTimer.current = undefined;
    endDragGesture(true);
    gesture.current = null;
    const span = pinchSpan();
    if (span <= 0 || pinch.current) return;
    pinch.current = { span };
    pinchStartRef.current?.();
  };
  const trackPinch = () => {
    const state = pinch.current;
    if (state) pinchUpdateRef.current?.(pinchSpan() / state.span);
  };
  const releasePointer = (pointerId: number, cancelled = false) => {
    pointers.current.delete(pointerId);
    if (pointers.current.size < 2 && pinch.current) {
      pinch.current = null;
      pinchEndRef.current?.(cancelled);
    }
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
        aria-label={paused ? t('clipViewer.play') : t('clipViewer.pause')}
        onContextMenu={(event) => event.preventDefault()}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.currentTarget.setPointerCapture?.(event.pointerId);
          pointers.current.set(event.pointerId, {
            x: event.clientX,
            y: event.clientY,
          });
          if (pointers.current.size >= 2) {
            startPinch();
            return;
          }
          if (!event.isPrimary) return;
          gesture.current = {
            x: event.clientX,
            y: event.clientY,
            held: false,
            moved: false,
            engaged: false,
            lastDy: 0,
            samples: [{ y: event.clientY, t: performance.now() }],
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
          if (pointers.current.has(event.pointerId)) {
            pointers.current.set(event.pointerId, {
              x: event.clientX,
              y: event.clientY,
            });
          }
          if (pinch.current) {
            trackPinch();
            return;
          }
          if (!event.isPrimary) return;
          const start = gesture.current;
          if (!start) return;
          const dy = event.clientY - start.y;
          const dx = event.clientX - start.x;
          if (!start.moved && Math.hypot(dx, dy) > 12) {
            start.moved = true;
            cancelHold();
          }
          start.samples.push({ y: event.clientY, t: performance.now() });
          if (start.samples.length > 6) start.samples.shift();
          if (
            dragEnabledRef.current &&
            !start.engaged &&
            !start.held &&
            Math.abs(dy) > DRAG_ENGAGE_PX &&
            Math.abs(dy) > Math.abs(dx) * 1.3
          ) {
            start.engaged = true;
            start.moved = true;
            cancelHold();
          }
          if (start.engaged) {
            start.lastDy = dy;
            dragUpdateRef.current?.(dy);
          }
        }}
        onPointerCancel={(event) => {
          releasePointer(event.pointerId, true);
          endDragGesture(true);
        }}
        onLostPointerCapture={(event) => {
          // A real release fires pointerup first (gesture already cleared);
          // only a capture loss mid-drag counts as a cancellation.
          releasePointer(event.pointerId, true);
          endDragGesture(true);
        }}
        onPointerUp={(event) => {
          releasePointer(event.pointerId);
          if (!event.isPrimary) return;
          const start = gesture.current;
          gesture.current = null;
          cancelHold();
          if (!start || start.held) return;
          // Feed-pager drags are owned by the parent: it followed the finger
          // live and decides commit vs spring-back from dy + velocity.
          if (start.engaged && dragEnabledRef.current) {
            clearTimeout(tapTimer.current);
            tapTimer.current = undefined;
            dragEndRef.current?.({
              dy: event.clientY - start.y,
              velocity: releaseVelocity([
                ...start.samples,
                { y: event.clientY, t: performance.now() },
              ]),
              cancelled: false,
            });
            return;
          }
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
        {paused && mediaPresented && (
          <span className="clip-play-indicator">
            <Play size={48} strokeWidth={3} fill="currentColor" />
          </span>
        )}
        {heart && (
          <Heart className="clip-heart" size={84} fill="currentColor" />
        )}
        {holding && <span className="clip-speed-indicator">2× speed</span>}
      </button>
      {mediaPresented && (
        <>
          <div className="clip-transport">
            <button
              type="button"
              aria-label={paused ? t('clipViewer.resume') : t('clipViewer.pause')}
              onClick={toggle}
            >
              {paused ? <Play size={20} strokeWidth={3} fill="currentColor" /> : <Pause size={20} strokeWidth={3} />}
            </button>
            <span className="clip-time">
              {Math.floor(progress)} / {Math.floor(duration)}s
            </span>
            <button
              type="button"
              aria-label={muted ? t('clipViewer.unmute') : t('clipViewer.mute')}
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
            aria-label={t('clipViewer.videoPosition')}
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
      )}
    </>
  );
}
