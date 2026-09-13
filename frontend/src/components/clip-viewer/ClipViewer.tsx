import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, BarChart3, ChevronDown } from "lucide-react";
import { Link } from "react-router-dom";
import type { Attempt } from "../../utils/attemptPresentation";
import { attemptDate } from "../../utils/attemptPresentation";
import { getPreview } from "../../utils/mediaPreview";
import { inertExcept, trapTabKey } from "../../utils/a11y";
import DiveVideoPlayer from "../DiveVideoPlayer";
import ClipViewerNavigation from "./ClipViewerNavigation";
import ClipMetadataSummary from "./ClipMetadataSummary";
import ClipDetails from "./ClipDetails";

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
}: {
  attempt: Attempt;
  attempts: Attempt[];
  onClose: () => void;
  onMove: (attempt: Attempt) => void;
  playbackRate: number;
  onPlaybackRateChange: (rate: number) => void;
}) {
  const index = attempts.findIndex((item) => item.id === attempt.id);
  const total = attempts.length;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);

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
        onClose();
        return;
      }
      if (event.key === "Tab") {
        const dialog = dialogRef.current;
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
      if (event.key === " " && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
        if (element?.closest(INTERACTIVE_TARGET)) return;
        const video = dialogRef.current?.querySelector("video");
        if (!video) return;
        event.preventDefault();
        if (video.paused) {
          video.play();
        } else {
          video.pause();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, onMove, attempts, index, total]);

  return (
    <div className="fixed inset-0 z-50 overscroll-none bg-app" role="presentation">
      <section
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="clip-viewer-title"
        data-testid="clip-viewer"
        className="flex h-[100dvh] w-full flex-col overflow-hidden bg-app outline-none"
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-app px-3 py-2.5 sm:px-6 sm:py-3">
          <button
            type="button"
            onClick={onClose}
            className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-3 text-sm text-app-text"
            aria-label="Back to Library"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Library
          </button>
          <h2
            id="clip-viewer-title"
            className="min-w-0 truncate text-center font-mono text-lg font-semibold tracking-tight text-app-text sm:text-xl"
          >
            {attempt.dive_code}
          </h2>
          <p className="hidden shrink-0 text-sm text-app-muted md:block">
            {attemptDate(attempt, "d MMM yyyy · HH:mm")}
          </p>
          <div className="w-[2.75rem] shrink-0 md:hidden" aria-hidden="true" />
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto sm:overflow-hidden">
          <div className="flex w-full shrink-0 justify-center bg-black sm:min-h-0 sm:flex-1 sm:overflow-hidden">
            <div className="aspect-video w-full sm:mx-auto sm:h-full sm:max-w-[76rem]">
              {attempt.video_uuid ? (
                <DiveVideoPlayer
                  key={attempt.id}
                  diveCode={attempt.dive_code}
                  height={attempt.height}
                  videoUuid={attempt.video_uuid}
                  playbackRate={playbackRate}
                />
              ) : (
                <div className="flex h-full items-center justify-center border border-app bg-app-panel text-sm text-app-muted">
                  No linked clip for this attempt.
                </div>
              )}
            </div>
          </div>
          <div className="w-full shrink-0 border-t border-app bg-app">
            <div className="mx-auto w-full max-w-[76rem] px-3 pb-3 pt-3 sm:px-6 sm:pb-4">
              <ClipViewerNavigation
                index={index}
                total={total}
                onPrevious={() => index > 0 && onMove(attempts[index - 1])}
                onNext={() => index < total - 1 && onMove(attempts[index + 1])}
                playbackRate={playbackRate}
                onPlaybackRateChange={onPlaybackRateChange}
              />
              <div className="mt-3">
                <ClipMetadataSummary attempt={attempt} />
              </div>
              <div className="mt-3 flex items-center justify-between gap-2 border-t border-app pt-3">
                <button
                  type="button"
                  onClick={() => setDetailsOpen((open) => !open)}
                  aria-expanded={detailsOpen}
                  aria-controls="clip-viewer-details"
                  className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-3 text-sm text-app-text"
                >
                  Details
                  <ChevronDown
                    className={`h-4 w-4 transition-transform ${detailsOpen ? "rotate-180" : ""}`}
                  />
                </button>
                <Link
                  to={`/dives/analysis/${attempt.dive_code}`}
                  className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-3 text-sm text-app-text"
                >
                  <BarChart3 className="h-4 w-4" />
                  Analysis
                </Link>
              </div>
              <div className="mt-3">
                <ClipDetails attempt={attempt} open={detailsOpen} />
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
