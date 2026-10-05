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
import { getPreview } from "../../utils/mediaPreview";
import { inertExcept, trapTabKey } from "../../utils/a11y";
import DiveVideoPlayer from "../DiveVideoPlayer";
import ClipViewerNavigation from "./ClipViewerNavigation";
import ClipMetadataSummary from "./ClipMetadataSummary";
import DiveManagement from "./DiveManagement";
import DiveVisibilityControl from "./DiveVisibilityControl";
import ClipDetails from "./ClipDetails";
import ClipComments from "./ClipComments";
import ShareDiveButton from "./ShareDiveButton";
import { useDiveSocial } from "./useDiveSocial";
import "./clipViewer.css";

const TYPING_TARGET = 'input, textarea, select, [contenteditable="true"]';
const INTERACTIVE_TARGET =
  'input, textarea, select, button, a, video, [contenteditable="true"], [role="slider"], [role="combobox"]';

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
  const descriptionGesture = useRef<number | null>(null);
  const descriptionSwiped = useRef(false);
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
  const navigate = (direction: -1 | 1) => {
    const next = attempts[index + direction];
    if (next) onMove(next);
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

  // Warm the adjacent clips' poster/status cache so Previous/Next feel
  // instant. Deduped and cached; no new caching architecture.
  useEffect(() => {
    [attempts[index - 1], attempts[index + 1]].forEach((neighbor) => {
      if (neighbor?.video_uuid) getPreview(neighbor.video_uuid);
    });
  }, [attempts, index]);

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
          onMove(attempts[index - 1]);
        }
        return;
      }
      if (event.shiftKey && event.key === "ArrowRight") {
        if (index < total - 1) {
          event.preventDefault();
          onMove(attempts[index + 1]);
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
          <div
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
                      <DiveVisibilityControl
                        key={attempt.id}
                        attempt={attempt}
                        onUpdate={onUpdate}
                      />
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
