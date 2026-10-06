import React, { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  Heart,
  MessageCircle,
  X,
  ChevronUp,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import type { Attempt } from "../../utils/attemptPresentation";
import { attemptDate } from "../../utils/attemptPresentation";
import { cachedPreview, getPreview } from "../../utils/mediaPreview";
import { warmAdjacentClips } from "../../utils/playbackWarming";
import { inertExcept, trapTabKey } from "../../utils/a11y";
import type { FeedDragEnd } from "./ImmersiveControls";
import DiveVideoPlayer from "../DiveVideoPlayer";
import ClipViewerNavigation from "./ClipViewerNavigation";
import ClipMetadataSummary from "./ClipMetadataSummary";
import DiveManagement from "./DiveManagement";
import DiveVisibilityControl from "./DiveVisibilityControl";
import FederateDiveControl from "./FederateDiveControl";
import ClipDetails from "./ClipDetails";
import ClipComments from "./ClipComments";
import ShareDiveButton from "./ShareDiveButton";
import { useDiveSocial } from "./useDiveSocial";
import { useNavigationIntent } from "../../hooks/useNavigationIntent";
import { defaultAnalysisFilters, warmDiveAnalysis } from "../../services/diveAnalysisApi";
import { useAuth } from "../../contexts/AuthContext";
import "./clipViewer.css";

const TYPING_TARGET = 'input, textarea, select, [contenteditable="true"]';
const INTERACTIVE_TARGET =
  'input, textarea, select, button, a, video, [contenteditable="true"], [role="slider"], [role="combobox"]';

// Feed-pager navigation (TikTok/Reels-style drag-follow), mobile only.
//
// The live dive stays mounted in the middle while warmed poster frames sit
// above/below it. A vertical drag translates the frames 1:1 with the finger
// (direct DOM writes, zero React renders); release commits (snap) or
// cancels (spring back) based on drag distance or fling velocity. Only one
// video player is ever mounted — neighbors are posters from the shared
// preview cache, whose bytes the existing warming pipeline already
// pre-loads. Desktop and reduced-motion keep the instant swap.
export const FEED_PUSH_DURATION_MS = 240;
export const FEED_SPRING_DURATION_MS = 200;
export const FEED_COMMIT_FRACTION = 0.25;
export const FEED_FLING_VELOCITY_PX_MS = 0.6;
export const FEED_FLING_MIN_PX = 24;
const MOBILE_PAGER_QUERY = "(max-width: 599px)";

export function shouldEnableFeedPager(): boolean {
  try {
    const reduce =
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ??
      false;
    if (reduce) return false;
    // Mobile-only, matching the max-width:599px mobile styles. An unknown
    // viewport (e.g. jsdom) defaults to enabled so tests can observe it.
    return window.matchMedia?.(MOBILE_PAGER_QUERY).matches ?? true;
  } catch {
    return false;
  }
}

/** Release commits when the drag covers a quarter of the stage, or when a
 * fast fling (same sign as the displacement) escapes a short drag. */
export function shouldCommitDrag(
  dy: number,
  height: number,
  velocity: number,
): boolean {
  if (!Number.isFinite(height) || height <= 0) return false;
  if (Math.abs(dy) > height * FEED_COMMIT_FRACTION) return true;
  return (
    Math.abs(velocity) > FEED_FLING_VELOCITY_PX_MS &&
    Math.abs(dy) > FEED_FLING_MIN_PX &&
    Math.sign(velocity) === Math.sign(dy)
  );
}

/**
 * The warmed poster of a neighboring dive, revealed while the finger drags.
 * Poster-only (never a player): focus can never land here, and mounting one
 * costs a single cached image instead of a media-status lookup + decoder.
 */
function ClipNeighborFrame({
  attempt,
  position,
  frameRef,
}: {
  attempt: Attempt;
  position: "prev" | "next";
  frameRef: React.Ref<HTMLDivElement>;
}) {
  const [poster, setPoster] = useState<string | null>(() =>
    attempt.video_uuid
      ? (cachedPreview(attempt.video_uuid)?.posterUrl ?? null)
      : null,
  );
  useEffect(() => {
    if (poster || !attempt.video_uuid) return;
    let live = true;
    void getPreview(attempt.video_uuid).then((preview) => {
      if (live) setPoster(preview.posterUrl);
    });
    return () => {
      live = false;
    };
  }, [attempt.video_uuid, poster]);
  return (
    <div
      ref={frameRef}
      className={`clip-pager-neighbor is-${position}`}
      aria-hidden="true"
      data-neighbor={attempt.id}
    >
      {poster ? <img src={poster} alt="" draggable={false} /> : null}
      <div className="clip-neighbor-shade" />
      <p className="clip-neighbor-label">
        {attempt.dive_code}
        <span>{attemptDate(attempt)}</span>
      </p>
    </div>
  );
}

export default function ClipViewer({
  attempt,
  attempts,
  onClose,
  onMove,
  playbackRate,
  onPlaybackRateChange,
  onUpdate,
  onDelete,
}: {
  attempt: Attempt;
  attempts: Attempt[];
  onClose: () => void;
  onMove: (attempt: Attempt) => void;
  playbackRate: number;
  onPlaybackRateChange: (rate: number) => void;
  onUpdate?: (attempt: Attempt) => void;
  onDelete?: () => void;
}) {
  const index = attempts.findIndex((item) => item.id === attempt.id);
  const total = attempts.length;
  const location = useLocation();
  const [manageOpen, setManageOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [aspectRatio, setAspectRatio] = useState(9 / 16);
  const [wide, setWide] = useState(
    () => window.matchMedia?.("(min-width: 1024px)").matches ?? true,
  );
  const [commentsOpen, setCommentsOpen] = useState(false);
  const {
    social,
    setSocial,
    like,
    error: socialError,
    busy: socialBusy,
    retry,
  } = useDiveSocial(attempt.id);
  const { user } = useAuth();
  // Hover/pointer-down on the Analysis action speculatively prepares the
  // analysis result so the destination page meets ready data instead of
  // opening on a compute round-trip. Consume-once: the page's own call
  // takes over; retries fall back to its normal fetch.
  const analysisIntent = useNavigationIntent(
    `/dives/analysis/${attempt.dive_code}?attempt=${attempt.id}`,
    () => {
      warmDiveAnalysis(attempt.dive_code, defaultAnalysisFilters(user?.divers?.length ? 'self' : 'all'));
      return Promise.resolve();
    },
  );
  const descriptionGesture = useRef<number | null>(null);
  const descriptionSwiped = useRef(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const currentRef = useRef<HTMLDivElement>(null);
  const prevFrameRef = useRef<HTMLDivElement>(null);
  const nextFrameRef = useRef<HTMLDivElement>(null);
  // A commit/snap animation in flight: drag input is ignored until it lands.
  const animatingRef = useRef(false);
  const commitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Stage height captured once per gesture so moves never force layout.
  const dragHeightRef = useRef<number | null>(null);
  // The selection the live frame shows. Lags the `attempt` prop during a
  // commit snap; external changes (Back button, filters) adopt instantly.
  const displayedIdRef = useRef(attempt.id);
  const [pagerEnabled, setPagerEnabled] = useState(shouldEnableFeedPager);
  const prevAttempt = index > 0 ? attempts[index - 1] : null;
  const nextAttempt = index < total - 1 ? attempts[index + 1] : null;
  const panelOpen = detailsOpen || commentsOpen || manageOpen;
  const panelRef = useRef<HTMLElement>(null);
  const detailsButtonRef = useRef<HTMLButtonElement>(null);
  const commentsButtonRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);
  const closePanel = () => {
    returnFocus.current = (
      commentsOpen ? commentsButtonRef : detailsButtonRef
    ).current;
    setDetailsOpen(false);
    setCommentsOpen(false);
    setManageOpen(false);
  };
  const setFrameTransform = (el: HTMLDivElement | null, y: number | null) => {
    if (!el) return;
    el.style.transform = y === null ? "" : `translateY(${y}px)`;
  };
  // Running WAAPI frame animations. Clearing an inline transform does NOT
  // stop them (they composite independently), so every reset path must
  // cancel them explicitly — otherwise a retained frame keeps sliding over
  // the newly selected dive.
  const frameAnimsRef = useRef<Animation[]>([]);
  const trackFrameAnimation = (anim: unknown) => {
    if (
      !anim ||
      typeof (anim as Animation).cancel !== "function"
    )
      return;
    const animation = anim as Animation;
    frameAnimsRef.current.push(animation);
    const drop = () => {
      frameAnimsRef.current = frameAnimsRef.current.filter(
        (item) => item !== animation,
      );
    };
    try {
      animation.finished?.then(drop, drop);
    } catch {
      // Engines without `finished`: the list drains on the next cancel.
    }
  };
  const cancelFrameAnimations = () => {
    const running = frameAnimsRef.current;
    frameAnimsRef.current = [];
    running.forEach((animation) => {
      try {
        animation.cancel();
      } catch {
        // Already finished between tracking and cancel.
      }
    });
  };
  const animateFrame = (
    el: HTMLDivElement | null,
    keyframes: Keyframe[],
    options: KeyframeAnimationOptions,
  ) => {
    if (!el || typeof el.animate !== "function") return false;
    try {
      trackFrameAnimation(el.animate(keyframes, options));
      return true;
    } catch {
      return false;
    }
  };
  const measureStage = () =>
    viewportRef.current?.clientHeight || window.innerHeight || 0;
  const clearCommitTimer = () => {
    if (commitTimer.current !== null) {
      clearTimeout(commitTimer.current);
      commitTimer.current = null;
    }
  };
  const neighborFrame = (direction: -1 | 1) =>
    direction === 1 ? nextFrameRef.current : prevFrameRef.current;
  const neighborAttempt = (direction: -1 | 1) =>
    direction === 1 ? nextAttempt : prevAttempt;
  /** What the finger actually rendered: full travel, or rubber-banded past
   * a result-set edge where there is nothing to reveal. */
  const renderedDisplacement = (dy: number) => {
    const direction: -1 | 1 = dy < 0 ? 1 : -1;
    return neighborAttempt(direction) ? dy : dy * 0.35;
  };
  // Latest list for revalidating a pending commit: filters/refreshes may
  // replace `attempts` while keeping the selected dive.
  const attemptsRef = useRef(attempts);
  attemptsRef.current = attempts;
  const pendingCommitRef = useRef<{
    targetId: number;
    direction: -1 | 1;
    fromId: number;
  } | null>(null);

  /** Finger-following: translate the live frame and the incoming neighbor
   * 1:1 with the pointer. Direct DOM writes only — no React renders, so the
   * gesture stays at pointer-event rate even on low-end phones. */
  const applyDrag = (dy: number) => {
    if (animatingRef.current || !pagerEnabled) return;
    if (dragHeightRef.current === null) {
      dragHeightRef.current = measureStage();
      viewportRef.current?.classList.add("is-dragging");
    }
    const height = dragHeightRef.current || 0;
    const direction: -1 | 1 = dy < 0 ? 1 : -1;
    const neighbor = neighborAttempt(direction);
    const effective = renderedDisplacement(dy);
    setFrameTransform(currentRef.current, effective);
    if (neighbor && height > 0) {
      setFrameTransform(
        neighborFrame(direction),
        direction * height + effective,
      );
    }
    // The finger may reverse mid-gesture; park the idle side back at base.
    setFrameTransform(neighborFrame(direction === 1 ? -1 : 1), null);
  };

  /** Release: snap through to the neighbor or spring back home. */
  const endDrag = (result: FeedDragEnd) => {
    viewportRef.current?.classList.remove("is-dragging");
    const height = dragHeightRef.current ?? measureStage();
    dragHeightRef.current = null;
    if (animatingRef.current) return;
    const { dy, velocity, cancelled } = result;
    const direction: -1 | 1 = dy < 0 ? 1 : -1;
    const neighbor = neighborAttempt(direction);
    // Animate from the rendered position (rubber-banded at an edge), while
    // the commit decision stays on raw finger travel.
    const rendered = renderedDisplacement(dy);
    if (!cancelled && neighbor && shouldCommitDrag(dy, height, velocity)) {
      commitPush(direction, rendered);
    } else {
      springBack(direction, rendered);
    }
  };

  const springBack = (direction: -1 | 1, fromDy: number) => {
    const current = currentRef.current;
    const frame = neighborFrame(direction);
    const height = measureStage();
    if (!pagerEnabled || !current || typeof current.animate !== "function") {
      setFrameTransform(current, null);
      setFrameTransform(frame, null);
      return;
    }
    animatingRef.current = true;
    cancelFrameAnimations();
    animateFrame(
      current,
      [{ transform: `translateY(${fromDy}px)` }, { transform: "translateY(0)" }],
      { duration: FEED_SPRING_DURATION_MS, easing: "ease-out" },
    );
    if (frame) {
      animateFrame(
        frame,
        [
          { transform: `translateY(${direction * height + fromDy}px)` },
          { transform: `translateY(${direction * height}px)` },
        ],
        { duration: FEED_SPRING_DURATION_MS, easing: "ease-out" },
      );
    }
    clearCommitTimer();
    commitTimer.current = setTimeout(() => {
      commitTimer.current = null;
      animatingRef.current = false;
      cancelFrameAnimations();
      setFrameTransform(currentRef.current, null);
      setFrameTransform(prevFrameRef.current, null);
      setFrameTransform(nextFrameRef.current, null);
    }, FEED_SPRING_DURATION_MS);
  };

  /** Snap through to the neighbor, then swap the selection once it lands. */
  const commitPush = (direction: -1 | 1, fromDy: number) => {
    const target = neighborAttempt(direction);
    if (!target) return;
    const fromId = attempt.id;
    const current = currentRef.current;
    const frame = neighborFrame(direction);
    const height = measureStage();
    if (
      !pagerEnabled ||
      !current ||
      typeof current.animate !== "function" ||
      height <= 0
    ) {
      displayedIdRef.current = target.id;
      onMove(target);
      return;
    }
    animatingRef.current = true;
    pendingCommitRef.current = { targetId: target.id, direction, fromId };
    viewportRef.current?.classList.remove("is-dragging");
    dragHeightRef.current = null;
    cancelFrameAnimations();
    animateFrame(
      current,
      [
        { transform: `translateY(${fromDy}px)` },
        { transform: `translateY(${-direction * height}px)` },
      ],
      {
        duration: FEED_PUSH_DURATION_MS,
        easing: "cubic-bezier(0.32, 0.72, 0, 1)",
      },
    );
    if (frame) {
      animateFrame(
        frame,
        [
          { transform: `translateY(${direction * height + fromDy}px)` },
          { transform: "translateY(0)" },
        ],
        {
          duration: FEED_PUSH_DURATION_MS,
          easing: "cubic-bezier(0.32, 0.72, 0, 1)",
        },
      );
    }
    clearCommitTimer();
    commitTimer.current = setTimeout(() => {
      commitTimer.current = null;
      animatingRef.current = false;
      cancelFrameAnimations();
      const pending = pendingCommitRef.current;
      pendingCommitRef.current = null;
      setFrameTransform(currentRef.current, null);
      setFrameTransform(prevFrameRef.current, null);
      setFrameTransform(nextFrameRef.current, null);
      // An external selection change (Back button, filter) wins over a
      // still-pending commit: never clobber it with a stale target.
      if (!pending || displayedIdRef.current !== pending.fromId) return;
      // The list itself may have changed under the commit (filter, refresh,
      // removal): only land on the neighbor if it is still the neighbor.
      const live = attemptsRef.current;
      const liveIndex = live.findIndex((item) => item.id === pending.fromId);
      const liveTarget =
        liveIndex >= 0 ? live[liveIndex + pending.direction] : undefined;
      if (!liveTarget || liveTarget.id !== pending.targetId) return;
      displayedIdRef.current = liveTarget.id;
      onMove(liveTarget);
    }, FEED_PUSH_DURATION_MS);
  };

  const navigate = (direction: -1 | 1) => {
    if (animatingRef.current) return;
    const next = attempts[index + direction];
    if (!next) return;
    // Buttons/keys take the same push the finger takes, minus the drag.
    if (pagerEnabled) commitPush(direction, 0);
    else onMove(next);
  };
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setManageOpen(false);
    setDetailsOpen(false);
    setCommentsOpen(false);
    setAspectRatio(9 / 16);
  }, [attempt.id]);

  useEffect(() => {
    const media = window.matchMedia?.("(min-width: 1024px)");
    if (!media) return;
    const update = () => setWide(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!panelRef.current) return;
    panelRef.current.toggleAttribute("inert", !wide && !panelOpen);
  }, [wide, panelOpen]);
  useEffect(() => {
    if (panelOpen && panelRef.current) {
      const restore = inertExcept(panelRef.current);
      // The backdrop remains a pointer dismissal target, outside the Tab order.
      dialogRef.current?.querySelector('.clip-panel-scrim')?.removeAttribute('inert');
      return restore;
    }
  }, [panelOpen]);

  useEffect(() => {
    if (panelOpen) panelRef.current?.focus({ preventScroll: true });
    else if (returnFocus.current) {
      returnFocus.current.focus({ preventScroll: true });
      returnFocus.current = null;
    }
  }, [panelOpen]);

  // Focus enters the review surface on open; the Library stays mounted below.
  useEffect(() => {
    dialogRef.current?.focus({ preventScroll: true });
  }, []);

  // Lock the underlying Library while review mode is open.
  useEffect(() => {
    const bodyOverflow = document.body.style.overflow;
    const documentOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = bodyOverflow;
      document.documentElement.style.overflow = documentOverflow;
    };
  }, []);

  // Modal interaction model: the viewer visually covers the Library, so the
  // rest of the page (sidebar, mobile navigation, the mounted Library) is
  // made inert — unreachable for focus, pointer and assistive technology —
  // and Tab/Shift+Tab are kept inside the review surface.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    return inertExcept(dialog);
  }, []);

  // Warm the adjacent clips so Previous/Next feel instant: their status
  // lookups resolve into the shared preview cache (which the player seeds
  // playback from), and their ready renditions download into the browser
  // HTTP cache inside a bounded, low-priority byte warm.
  useEffect(() => {
    warmAdjacentClips([attempts[index - 1]?.video_uuid, attempts[index + 1]?.video_uuid]);
  }, [attempts, index]);

  useEffect(() => {
    const mobile = window.matchMedia?.(MOBILE_PAGER_QUERY);
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mobile || !reduce) return;
    const update = () => setPagerEnabled(mobile.matches && !reduce.matches);
    update();
    mobile.addEventListener("change", update);
    reduce.addEventListener("change", update);
    return () => {
      mobile.removeEventListener("change", update);
      reduce.removeEventListener("change", update);
    };
  }, []);

  // Adopt external selection changes instantly (browser Back, filters, deep
  // links): park any in-flight drag/commit visuals at rest. Our own commits
  // set displayedIdRef before calling onMove, so they no-op here.
  useEffect(() => {
    if (attempt.id === displayedIdRef.current) return;
    displayedIdRef.current = attempt.id;
    clearCommitTimer();
    pendingCommitRef.current = null;
    cancelFrameAnimations();
    animatingRef.current = false;
    dragHeightRef.current = null;
    viewportRef.current?.classList.remove("is-dragging");
    setFrameTransform(currentRef.current, null);
    setFrameTransform(prevFrameRef.current, null);
    setFrameTransform(nextFrameRef.current, null);
  }, [attempt.id]);

  useEffect(
    () => () => {
      clearCommitTimer();
      pendingCommitRef.current = null;
      cancelFrameAnimations();
    },
    [],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (panelOpen) closePanel();
        else onClose();
        return;
      }
      if (event.key === "Tab") {
        const dialog = panelOpen ? panelRef.current : dialogRef.current;
        if (dialog) trapTabKey(dialog, event);
        return;
      }
      const target = event.target as HTMLElement | null;
      const element =
        target && typeof target.closest === "function" ? target : null;
      if (element?.closest(TYPING_TARGET)) return;
      if (event.shiftKey && event.key === "ArrowLeft") {
        if (index > 0) {
          event.preventDefault();
          navigate(-1);
        }
        return;
      }
      if (event.shiftKey && event.key === "ArrowRight") {
        if (index < total - 1) {
          event.preventDefault();
          navigate(1);
        }
        return;
      }
      if (
        event.key === " " &&
        !event.shiftKey &&
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey
      ) {
        if (element?.closest(INTERACTIVE_TARGET)) return;
        const video = dialogRef.current?.querySelector("video");
        if (!video) return;
        event.preventDefault();
        if (video.paused) {
          void video.play()?.catch(() => {});
        } else {
          video.pause();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, onMove, attempts, index, total, panelOpen]);

  return (
    <div
      className="fixed inset-0 z-50 overscroll-none bg-app"
      role="presentation"
    >
      <section
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="clip-viewer-title"
        data-testid="clip-viewer"
        className="clip-viewer"
      >
        <header className="clip-header">
          <button
            type="button"
            onClick={onClose}
            aria-label="Back to Library"
            className="clip-back"
          >
            <ArrowLeft size={20} />
            <span>Library</span>
          </button>
          <div className="clip-header-label">
            <span className="clip-live-dot" />
            DIVE REVIEW
          </div>
          <span className="clip-counter">
            {index + 1} / {total}
          </span>
        </header>
        <div className="clip-layout">
          <div ref={viewportRef} className="clip-stage-viewport">
            {pagerEnabled && prevAttempt && (
              <ClipNeighborFrame
                key={prevAttempt.id}
                attempt={prevAttempt}
                position="prev"
                frameRef={prevFrameRef}
              />
            )}
          <div
            ref={currentRef}
            className="clip-stage"
            data-orientation={aspectRatio > 1 ? "landscape" : "portrait"}
            style={{ "--clip-aspect": aspectRatio } as React.CSSProperties}
          >
            {attempt.video_uuid ? (
              <DiveVideoPlayer
                key={attempt.id}
                diveCode={attempt.dive_code}
                height={attempt.height}
                videoUuid={attempt.video_uuid}
                playbackRate={playbackRate}
                immersive
                onAspectRatioChange={setAspectRatio}
                onLike={() => void like(true)}
                onNavigate={navigate}
                dragEnabled={pagerEnabled}
                onDragUpdate={applyDrag}
                onDragEnd={endDrag}
              />
            ) : (
              <div className="clip-no-media">
                No linked clip for this attempt.
              </div>
            )}
            <div className="clip-stage-shade" />
            <div className="clip-actions">
              <button
                type="button"
                aria-label="Like dive"
                aria-pressed={social?.liked ?? false}
                disabled={!social || socialBusy}
                onClick={() => void like(!social?.liked)}
              >
                <Heart
                  size={25}
                  fill={social?.liked ? "currentColor" : "none"}
                />
                <span>{social?.like_count ?? "Like"}</span>
              </button>
              <button
                type="button"
                ref={commentsButtonRef}
                aria-label="Comments"
                aria-expanded={commentsOpen}
                aria-controls="clip-review-panel"
                onClick={() => {
                  setCommentsOpen(!commentsOpen);
                  setDetailsOpen(false);
                  setManageOpen(false);
                }}
              >
                <MessageCircle size={25} />
                <span>{social?.comment_count ?? "Comments"}</span>
              </button>
              {attempt.can_manage && attempt.video_uuid && <ShareDiveButton key={attempt.id} id={attempt.id} />}
              <Link
                to={`/dives/analysis/${attempt.dive_code}?attempt=${attempt.id}`}
                state={{ returnTo: `${location.pathname}${location.search}` }}
                aria-label="Analysis"
                {...analysisIntent}
              >
                <BarChart3 size={25} />
                <span>Analysis</span>
              </Link>
            </div>
            <div className="clip-caption">
              <div className="clip-caption-eyebrow">
                {attempt.height} <span>·</span> {attempt.platform_type}{" "}
                <span>·</span>{" "}
                {attempt.visibility === "private" ? "Private" : "Public"}
              </div>
              <h2 id="clip-viewer-title">
                {attempt.dive_code}
                <span>{attemptDate(attempt)}</span>
              </h2>
              <button
                ref={detailsButtonRef}
                type="button"
                className="clip-description"
                aria-expanded={detailsOpen}
                aria-controls="clip-viewer-details"
                onPointerDown={(event) => {
                  descriptionSwiped.current = false;
                  descriptionGesture.current = event.clientY;
                  event.currentTarget.setPointerCapture?.(event.pointerId);
                }}
                onPointerUp={(event) => {
                  if (
                    descriptionGesture.current !== null &&
                    descriptionGesture.current - event.clientY > 30
                  ) {
                    descriptionSwiped.current = true;
                    setDetailsOpen(true);
                    setCommentsOpen(false);
                  }
                  descriptionGesture.current = null;
                }}
                onPointerCancel={() => { descriptionGesture.current = null; }}
                onClick={(event) => {
                  if (event.detail !== 0 && descriptionSwiped.current) return;
                  setDetailsOpen(!detailsOpen);
                  setCommentsOpen(false);
                  setManageOpen(false);
                }}
              >
                <span>
                  {attempt.notes ||
                    attempt.raw_caption ||
                    "Every dive, a little further."}
                </span>
                <strong>
                  Details <ChevronUp size={14} />
                </strong>
              </button>
              {socialError && (
                <p className="clip-social-error" role="alert">
                  {socialError} <button onClick={retry}>Retry</button>
                </p>
              )}
            </div>
          </div>
          {pagerEnabled && nextAttempt && (
            <ClipNeighborFrame
              key={nextAttempt.id}
              attempt={nextAttempt}
              position="next"
              frameRef={nextFrameRef}
            />
          )}
          </div>
          {panelOpen && (
            <button
              type="button"
              tabIndex={-1}
              className={`clip-panel-scrim ${commentsOpen ? "clip-comments-scrim" : ""}`}
              aria-label="Close details and comments"
              onClick={closePanel}
            />
          )}
          <aside
            ref={panelRef}
            tabIndex={-1}
            id="clip-review-panel"
            className={`clip-panel ${panelOpen ? "is-open" : ""} ${commentsOpen ? "clip-panel-comments" : ""}`}
            aria-label={commentsOpen ? "Comments" : "Dive details"}
          >
            <div className="clip-panel-heading">
              <div>
                <span className="clip-eyebrow">
                  {commentsOpen ? "DISCUSSION" : "THE ATTEMPT"}
                </span>
                <h3>{commentsOpen ? "Comments" : attempt.dive_code}</h3>
              </div>
              <button
                type="button"
                className="clip-panel-close"
                aria-label="Close panel"
                onClick={closePanel}
              >
                <X size={20} />
              </button>
            </div>
            <div className="clip-panel-scroll">
              {commentsOpen ? (
                <ClipComments
                  key={attempt.id}
                  id={attempt.id}
                  onCountChange={(delta) =>
                    setSocial((value) =>
                      value
                        ? {
                            ...value,
                            comment_count: Math.max(
                              0,
                              value.comment_count + delta,
                            ),
                          }
                        : value,
                    )
                  }
                />
              ) : (
                <>
                  <ClipMetadataSummary attempt={attempt} />
                  <div className="clip-panel-description">
                    <span className="clip-eyebrow">DESCRIPTION</span>
                    <p>
                      {attempt.notes ||
                        attempt.raw_caption ||
                        "No description for this attempt."}
                    </p>
                  </div>
                  <ClipDetails attempt={attempt} open={detailsOpen} />
                  <div className="clip-management">
                    {attempt.can_manage && onUpdate ? (
                      <>
                        <DiveVisibilityControl
                          key={`visibility-${attempt.id}`}
                          attempt={attempt}
                          onUpdate={onUpdate}
                        />
                        <FederateDiveControl
                          key={`fediverse-${attempt.id}`}
                          attempt={attempt}
                          onUpdate={onUpdate}
                        />
                      </>
                    ) : (
                      <span>
                        {attempt.visibility === "private"
                          ? "Private"
                          : "Public"}{" "}
                        dive
                      </span>
                    )}
                    {attempt.can_manage && onUpdate && onDelete && (
                      <button
                        type="button"
                        aria-expanded={manageOpen}
                        onClick={() => setManageOpen((open) => !open)}
                      >
                        Manage dive
                      </button>
                    )}
                  </div>
                  {manageOpen && attempt.can_manage && onUpdate && onDelete && (
                    <DiveManagement
                      key={attempt.id}
                      attempt={attempt}
                      onUpdate={onUpdate}
                      onDelete={onDelete}
                    />
                  )}
                </>
              )}
            </div>
            <p className="clip-gesture-hint">
              Tap to pause · Double tap to like
              <br />
              Hold for 2× · Swipe to change dive
            </p>
          </aside>
        </div>
        <footer className="clip-navigation">
          <ClipViewerNavigation
            index={index}
            total={total}
            onPrevious={() => navigate(-1)}
            onNext={() => navigate(1)}
            playbackRate={playbackRate}
            onPlaybackRateChange={onPlaybackRateChange}
          />
        </footer>
      </section>
    </div>
  );
}
