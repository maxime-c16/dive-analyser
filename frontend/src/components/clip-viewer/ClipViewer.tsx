import { preparePlaybackWindow } from '../../utils/preparedPlayback'
import { useTranslation } from 'react-i18next'
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Heart,
  MessageCircle,
  X,
  ChevronUp,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import type { Attempt } from "../../utils/attemptPresentation";
import {
  attemptDate,
  attemptScore,
  modifiersFor,
  platformTypeName,
} from "../../utils/attemptPresentation";
import { diveCodeName } from "../../i18n/diveNames";
import { cachedPreview, getPreview } from "../../utils/mediaPreview";
import { warmAdjacentClips } from "../../utils/playbackWarming";
import { useModalOverlay, isTopOverlay } from "../../utils/overlays";
import type { FeedDragEnd } from "./ImmersiveControls";
import DiveVideoPlayer from "../DiveVideoPlayer";
import ClipViewerNavigation, { PLAYBACK_RATES } from "./ClipViewerNavigation";
import ClipFilmstrip from "./ClipFilmstrip";
import ClipEvaluation, { useDiveEvaluation } from "./ClipEvaluation";
import DiveManagement from "./DiveManagement";
import DiveVisibilityControl from "./DiveVisibilityControl";
import FederateDiveControl from "./FederateDiveControl";
import ClipDetails from "./ClipDetails";
import ClipComments from "./ClipComments";
import ShareDiveButton from "./ShareDiveButton";
import DownloadDiveButton from "./DownloadDiveButton";
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
// Tablets and desktops: video, filmstrip and a permanent side panel. Phones
// (and phones in landscape) keep the immersive overlay player.
export const STUDIO_QUERY =
  "(min-width: 1024px), (min-width: 600px) and (min-height: 600px)";

type PanelTab = "evaluation" | "comments" | "details";

// Pinch-to-clean-view (Instagram-style). Closing two fingers by this much of
// the starting span takes the view all the way to clean; past it the video
// keeps shrinking a little (rounded, like a card) and springs back on release.
export const PINCH_RANGE = 0.35;
export const PINCH_OVERSHOOT_RANGE = 0.6;
export const PINCH_MAX_SHRINK = 0.12;
export const PINCH_MAX_RADIUS_PX = 28;

/** Where a pinch stands. `progress` is 0 (overlays + cropped fill) to 1
 * (clean, whole frame); `overshoot` is 0..1 once the fingers go past clean. */
export function pinchState(startClean: boolean, ratio: number) {
  if (!Number.isFinite(ratio) || ratio <= 0) {
    return { progress: startClean ? 1 : 0, overshoot: 0, clean: startClean };
  }
  const raw = (startClean ? 1 : 0) + (1 - ratio) / PINCH_RANGE;
  const progress = Math.min(1, Math.max(0, raw));
  const overshoot = Math.min(1, Math.max(0, (raw - 1) / PINCH_OVERSHOOT_RANGE));
  return { progress, overshoot, clean: raw >= 0.5 };
}

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
  const { t, i18n } = useTranslation();
  const index = attempts.findIndex((item) => item.id === attempt.id);
  const total = attempts.length;
  const location = useLocation();
  const [manageOpen, setManageOpen] = useState(false);
  const [aspectRatio, setAspectRatio] = useState(9 / 16);
  const [studio, setStudio] = useState(
    () => window.matchMedia?.(STUDIO_QUERY).matches ?? true,
  );
  // The panel tab survives moving between dives; on phones the panel is a
  // sheet opened from the overlay (comments button, description swipe).
  const [tab, setTab] = useState<PanelTab>("evaluation");
  const [sheetOpen, setSheetOpen] = useState(false);
  const detailsOpen = sheetOpen && tab === "details";
  const commentsOpen = sheetOpen && tab === "comments";
  const openSheet = (next: PanelTab) => {
    setTab(next);
    setSheetOpen(true);
    setManageOpen(false);
  };
  // Pinch-in on the video: overlays hide and the whole frame shows, like
  // Instagram. Per-dive: moving to another clip restores the overlays.
  const [cleanView, setCleanView] = useState(false);
  const [pinching, setPinching] = useState(false);
  // The stage video as sized on mobile: its contain-fit picture box, and the
  // zoom that makes it fill the stage the way `cover` would.
  const [picture, setPicture] = useState({ width: 0, height: 0, cover: 1 });
  const {
    social,
    setSocial,
    like,
    error: socialError,
    busy: socialBusy,
    retry,
  } = useDiveSocial(attempt.id);
  const { user } = useAuth();
  const evaluation = useDiveEvaluation(attempt.id, Boolean(user));
  const panelTab: PanelTab = !user && tab === "evaluation" ? "details" : tab;
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
  // Previous index inside the viewer, the swipe sign that steers the
  // rolling warm window. null until the first adopt-effect runs.
  const warmedIndexRef = useRef<number | null>(null);
  const [pagerEnabled, setPagerEnabled] = useState(shouldEnableFeedPager);
  const prevAttempt = index > 0 ? attempts[index - 1] : null;
  const nextAttempt = index < total - 1 ? attempts[index + 1] : null;
  const panelOpen = sheetOpen;
  const panelRef = useRef<HTMLElement>(null);
  const detailsButtonRef = useRef<HTMLButtonElement>(null);
  const commentsButtonRef = useRef<HTMLButtonElement>(null);
  const scrimRef = useRef<HTMLButtonElement>(null);
  const closePanel = () => {
    setSheetOpen(false);
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
    setSheetOpen(false);
    setCleanView(false);
    setAspectRatio(9 / 16);
  }, [attempt.id]);

  useEffect(() => {
    const neighbors = [index, index + 1, index - 1, index + 2]
      .map(i => attempts[i]?.video_uuid).filter((uuid): uuid is string => Boolean(uuid))
    preparePlaybackWindow(neighbors)
  }, [attempt.id, attempts, index])
  useEffect(() => () => preparePlaybackWindow([]), [])

  // Contain-fit picture box inside the stage, and the zoom that makes it
  // fill the stage like `cover` (1 for landscape clips, which stay contained).
  useEffect(() => {
    const stage = currentRef.current;
    if (!stage) return;
    const measure = () => {
      const { clientWidth: w, clientHeight: h } = stage;
      if (!w || !h || !aspectRatio) {
        setPicture({ width: 0, height: 0, cover: 1 });
        return;
      }
      const width = Math.min(w, h * aspectRatio);
      const height = Math.min(h, w / aspectRatio);
      setPicture({
        width,
        height,
        cover: aspectRatio > 1 ? 1 : Math.max(w / width, h / height),
      });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [aspectRatio]);

  // Pinch gesture: the video follows the fingers through CSS variables on the
  // dialog (direct DOM writes, no React renders per move). Release commits to
  // clean or back, and the CSS transitions carry it from the live pose.
  const pinchStartClean = useRef(false);
  const pinchLastClean = useRef(false);
  const writePinchVars = (progress: number, overshoot: number) => {
    const style = dialogRef.current?.style;
    if (!style) return;
    style.setProperty("--clip-pinch-p", String(progress));
    style.setProperty("--clip-pinch-shrink", String(overshoot * PINCH_MAX_SHRINK));
    style.setProperty(
      "--clip-pinch-radius",
      `${Math.min(1, overshoot * 4) * PINCH_MAX_RADIUS_PX}px`,
    );
  };
  const onPinchStart = () => {
    pinchStartClean.current = cleanView;
    pinchLastClean.current = cleanView;
    writePinchVars(cleanView ? 1 : 0, 0);
    setPinching(true);
  };
  const onPinchUpdate = (ratio: number) => {
    const next = pinchState(pinchStartClean.current, ratio);
    pinchLastClean.current = next.clean;
    writePinchVars(next.progress, next.overshoot);
  };
  const onPinchEnd = (cancelled: boolean) => {
    setCleanView(cancelled ? pinchStartClean.current : pinchLastClean.current);
    setPinching(false);
  };
  // The live pose is dropped in the same commit that flips the classes, so
  // the transition starts from where the fingers left the video.
  useLayoutEffect(() => {
    if (pinching) return;
    const style = dialogRef.current?.style;
    style?.removeProperty("--clip-pinch-p");
    style?.removeProperty("--clip-pinch-shrink");
    style?.removeProperty("--clip-pinch-radius");
  }, [pinching]);

  useEffect(() => {
    const media = window.matchMedia?.(STUDIO_QUERY);
    if (!media) return;
    const update = () => setStudio(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useLayoutEffect(() => {
    panelRef.current?.toggleAttribute("inert", !studio && !panelOpen);
  }, [studio, panelOpen]);
  useModalOverlay(dialogRef, { onClose,
    fallbackFocus: () => document.querySelector<HTMLInputElement>('input[data-dives-search]'),
  });
  useModalOverlay(panelRef, { enabled: panelOpen && !studio, layer: 51, extraRef: scrimRef, onClose: closePanel,
    returnFocus: () => (commentsOpen ? commentsButtonRef : detailsButtonRef).current,
  });

  // Slide the rolling warm window so Previous/Next feel instant: status
  // lookups resolve into the shared preview cache (which the player seeds
  // playback from), ready renditions download into the browser HTTP cache
  // inside a bounded, low-priority byte warm, and stale neighbours are
  // cancelled as the window moves.
  useEffect(() => {
    const previous = warmedIndexRef.current;
    warmedIndexRef.current = index;
    const direction: -1 | 0 | 1 = previous === null || previous === index
      ? 0
      : index > previous
        ? 1
        : -1;
    warmAdjacentClips({ nativePlayback: true, attempts, index, direction });
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
      if (!isTopOverlay(dialogRef.current) && !isTopOverlay(panelRef.current)) return;
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

  const lang = i18n.language?.startsWith("fr") ? "fr" : "en";
  const fullName = diveCodeName(attempt.dive_code, lang);
  const diveName = fullName === attempt.dive_code ? "" : fullName;
  const facts = [
    `${attempt.height} ${platformTypeName(attempt.platform_type)}`,
    attempt.official_dd ? `DD ${attempt.official_dd.toFixed(1)}` : null,
    attempt.is_sync ? "SYNC" : t("analysis.individual"),
    ...modifiersFor(attempt),
    attemptDate(attempt),
  ].filter(Boolean);
  const description = attempt.notes || attempt.raw_caption;
  const canShare = Boolean(user || (attempt.can_manage && attempt.video_uuid));
  const shareButton = canShare && (
    <ShareDiveButton key={attempt.id} id={attempt.id} allowLink={!!(attempt.can_manage && attempt.video_uuid)} allowDm={!!user} />
  );
  const downloadButton = user && attempt.video_uuid && (
    <DownloadDiveButton key={`download-${attempt.id}`} id={attempt.id} />
  );
  const analysisLink = (
    <Link
      to={`/dives/analysis/${attempt.dive_code}?attempt=${attempt.id}`}
      state={{ returnTo: `${location.pathname}${location.search}` }}
      aria-label={t("clipViewer.analysis")}
      {...analysisIntent}
    >
      <BarChart3 size={studio ? 18 : 25} />
      <span>{t("clipViewer.analysis")}</span>
    </Link>
  );
  const tabs: Array<[PanelTab, string, boolean]> = [
    ...(user
      ? [["evaluation", t("clipViewer.tabEvaluation"), evaluation.data?.state === "open"] as [PanelTab, string, boolean]]
      : []),
    ["comments", t("clipViewer.comments"), false],
    ["details", t("clipViewer.details"), false],
  ];
  const updateCommentCount = (delta: number) =>
    setSocial((value) =>
      value
        ? { ...value, comment_count: Math.max(0, value.comment_count + delta) }
        : value,
    );
  const speedSelect = (
    <label className="clip-speed">
      <span className="sr-only">{t("clipNav.speed")}</span>
      <select
        aria-label={t("clipNav.playbackSpeed")}
        value={playbackRate}
        onChange={(event) => onPlaybackRateChange(Number(event.target.value))}
      >
        {PLAYBACK_RATES.map((rate) => (
          <option key={rate} value={rate}>
            {rate}×
          </option>
        ))}
      </select>
    </label>
  );

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
        className={`clip-viewer${studio ? " is-studio" : ""}${cleanView ? " is-clean" : ""}${pinching ? " is-pinching" : ""}`}
      >
        <header className="clip-header">
          <button
            type="button"
            onClick={onClose}
            aria-label={t("notFound.backToLibrary")}
            className="clip-back"
          >
            <ArrowLeft size={20} />
            <span>{t("nav.dives")}</span>
          </button>
          {!studio && (
            <div className="clip-header-label">
              <span className="clip-live-dot" />
              {t("clipViewer.diveReview")}
            </div>
          )}
          <div className="clip-header-end">
            {studio && speedSelect}
            <span className="clip-counter" aria-live="polite">
              <b>{index + 1}</b> / {total}
            </span>
          </div>
        </header>
        <div className="clip-layout">
          {studio && (
            <ClipFilmstrip attempt={attempt} attempts={attempts} onSelect={onMove} />
          )}
          <div className="clip-stage-column">
          <div className="clip-stage-row">
          {studio && (
            <button
              type="button"
              className="clip-step"
              onClick={() => navigate(-1)}
              disabled={index <= 0}
              aria-label={t("clipNav.previous")}
              title={`${t("clipNav.previous")} (Shift+←)`}
            >
              <ChevronLeft size={20} />
            </button>
          )}
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
            style={
              {
                "--clip-aspect": aspectRatio,
                "--clip-cover-scale": picture.cover,
                ...(picture.width
                  ? {
                      "--clip-pic-w": `${picture.width}px`,
                      "--clip-pic-h": `${picture.height}px`,
                    }
                  : {}),
              } as React.CSSProperties
            }
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
                onPinchStart={onPinchStart}
                onPinchUpdate={onPinchUpdate}
                onPinchEnd={onPinchEnd}
              />
            ) : (
              <div className="clip-no-media">
                {t("clipViewer.noLinkedClip")}
              </div>
            )}
            {!studio && (
              <>
            <div className="clip-stage-shade" />
            <div className="clip-actions">
              <button
                type="button"
                aria-label={t("clipViewer.likeDive")}
                aria-pressed={social?.liked ?? false}
                disabled={!social || socialBusy}
                onClick={() => void like(!social?.liked)}
              >
                <Heart
                  size={25}
                  fill={social?.liked ? "currentColor" : "none"}
                />
                <span>{social?.like_count ?? t("clipViewer.like")}</span>
              </button>
              <button
                type="button"
                ref={commentsButtonRef}
                aria-label={t("clipViewer.comments")}
                aria-expanded={commentsOpen}
                aria-controls="clip-review-panel"
                onClick={() => (commentsOpen ? closePanel() : openSheet("comments"))}
              >
                <MessageCircle size={25} />
                <span>{social?.comment_count ?? t("clipViewer.comments")}</span>
              </button>
              {shareButton}
              {downloadButton}
              {analysisLink}
            </div>
            <div className="clip-caption">
              <div className="clip-caption-eyebrow">
                {attempt.height} <span>·</span> {platformTypeName(attempt.platform_type)}{" "}
                <span>·</span>{" "}
                {attempt.visibility === "private" ? t("clipViewer.private") : t("clipViewer.public")}
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
                    openSheet("details");
                  }
                  descriptionGesture.current = null;
                }}
                onPointerCancel={() => { descriptionGesture.current = null; }}
                onClick={(event) => {
                  if (event.detail !== 0 && descriptionSwiped.current) return;
                  if (detailsOpen) closePanel();
                  else openSheet("details");
                }}
              >
                <span>
                  {diveName || description || t("clipViewer.defaultCaption")}
                </span>
                <strong>
                  {t("clipViewer.details")} <ChevronUp size={14} />
                </strong>
              </button>
              {socialError && (
                <p className="clip-social-error" role="alert">
                  {socialError} <button onClick={retry}>{t("common.retry")}</button>
                </p>
              )}
            </div>
              </>
            )}
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
          {studio && (
            <button
              type="button"
              className="clip-step"
              onClick={() => navigate(1)}
              disabled={index >= total - 1}
              aria-label={t("clipNav.next")}
              title={`${t("clipNav.next")} (Shift+→)`}
            >
              <ChevronRight size={20} />
            </button>
          )}
          </div>
          </div>
          {panelOpen && !studio && (
            <button
              type="button"
              tabIndex={-1}
              ref={scrimRef}
              className={`clip-panel-scrim ${commentsOpen ? "clip-comments-scrim" : ""}`}
              aria-label={t("clipViewer.closeDetailsAndComments")}
              onClick={closePanel}
            />
          )}
          <aside
            ref={panelRef}
            tabIndex={-1}
            id="clip-review-panel"
            className={`clip-panel ${panelOpen ? "is-open" : ""} ${commentsOpen && !studio ? "clip-panel-comments" : ""}`}
            aria-label={t("clipViewer.diveDetails")}
          >
            {studio ? (
              <>
                <div className="clip-panel-summary">
                  <div className="clip-panel-title">
                    <h2 id="clip-viewer-title">{attempt.dive_code}</h2>
                    <span className="clip-panel-score">{attemptScore(attempt).toFixed(1)}</span>
                  </div>
                  {diveName && <p className="clip-panel-name">{diveName}</p>}
                  <p className="clip-panel-facts">{facts.join(" · ")}</p>
                </div>
                <div className="clip-panel-actions">
                  <button
                    type="button"
                    aria-label={t("clipViewer.likeDive")}
                    aria-pressed={social?.liked ?? false}
                    disabled={!social || socialBusy}
                    onClick={() => void like(!social?.liked)}
                  >
                    <Heart size={18} fill={social?.liked ? "currentColor" : "none"} />
                    <span>{social?.like_count ?? 0}</span>
                  </button>
                  {shareButton}
                  {downloadButton}
                  {analysisLink}
                </div>
                {socialError && (
                  <p className="clip-social-error" role="alert">
                    {socialError} <button onClick={retry}>{t("common.retry")}</button>
                  </p>
                )}
              </>
            ) : (
              <div className="clip-panel-heading">
                <div>
                  <span className="clip-eyebrow">{t("clipViewer.theAttempt")}</span>
                  <h3>{attempt.dive_code}</h3>
                </div>
                <button
                  type="button"
                  className="clip-panel-close"
                  aria-label={t("clipViewer.closePanel")}
                  onClick={closePanel}
                >
                  <X size={20} />
                </button>
              </div>
            )}
            <div className="clip-panel-tabs" role="tablist" aria-label={t("clipViewer.diveDetails")}>
              {tabs.map(([key, label, pending]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  id={`clip-tab-${key}`}
                  aria-selected={panelTab === key}
                  aria-controls="clip-panel-body"
                  className={pending && panelTab !== key ? "has-pending" : undefined}
                  onClick={() => setTab(key)}
                >
                  {label}
                  {key === "comments" && social ? <span>{social.comment_count}</span> : null}
                  {pending && panelTab !== key ? <span className="sr-only">{t("clipViewer.toRate")}</span> : null}
                </button>
              ))}
            </div>
            <div className="clip-panel-scroll" id="clip-panel-body" role="tabpanel" aria-labelledby={`clip-tab-${panelTab}`}>
              {panelTab === "evaluation" ? (
                <ClipEvaluation
                  attempt={attempt}
                  evaluation={evaluation.data}
                  error={evaluation.error}
                  onReload={evaluation.reload}
                  onRated={evaluation.setData}
                  onUpdate={onUpdate}
                />
              ) : panelTab === "comments" ? (
                <ClipComments key={attempt.id} id={attempt.id} onCountChange={updateCommentCount} />
              ) : (
                <>
                  {description && (
                    <div className="clip-panel-description">
                      <span className="clip-eyebrow">{t("clipViewer.description")}</span>
                      <p>{description}</p>
                    </div>
                  )}
                  <ClipDetails attempt={attempt} open />
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
                          ? t("clipViewer.privateDive")
                          : t("clipViewer.publicDive")}
                      </span>
                    )}
                    {attempt.can_manage && onUpdate && onDelete && (
                      <button
                        type="button"
                        aria-expanded={manageOpen}
                        onClick={() => setManageOpen((open) => !open)}
                      >
                        {t("clipViewer.manageDive")}
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
          </aside>
        </div>
        {!studio && (
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
        )}
      </section>
    </div>
  );
}
