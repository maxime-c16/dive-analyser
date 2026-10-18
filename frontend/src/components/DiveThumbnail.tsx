import { prepareLibraryPlayback } from '../utils/preparedPlayback'
import { useTranslation } from 'react-i18next'
import React, { useEffect, useRef, useState } from "react";
import { cachedPreview, getPreview, type MediaPreview } from "../utils/mediaPreview";
import type { Attempt } from "../utils/attemptPresentation";

export default function DiveThumbnail({
  dive,
  compact = false,
}: {
  dive: Attempt;
  compact?: boolean;
}) {
  const { t } = useTranslation()
  const [preview, setPreview] = useState<MediaPreview | null>(() =>
    dive.video_uuid ? cachedPreview(dive.video_uuid) || null : null,
  );
  const [imgError, setImgError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setImgError(false);
    if (!dive.video_uuid) return;
    // If already cached, apply immediately — no network request needed.
    const cached = cachedPreview(dive.video_uuid);
    if (cached) {
      setPreview(cached);
      // Only the first two visible candidates are prepared speculatively.
      const rect = containerRef.current?.getBoundingClientRect();
      if (cached.ready && rect && rect.bottom > 0 && rect.top < window.innerHeight) prepareLibraryPlayback(dive.video_uuid);
      return;
    }
    // Gate the fetch behind IntersectionObserver so we only hit the
    // backend for thumbnails that are actually near the viewport.
    // Without this, opening the Dives page fires 2000+ concurrent
    // status requests and exhausts the DB connection pool.
    const container = containerRef.current;
    if (!container) return;
    let active = true;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          observer.disconnect();
          getPreview(dive.video_uuid!).then((result) => {
            if (active) {
              setPreview(result);
              if (result.ready) prepareLibraryPlayback(dive.video_uuid!);
            }
          });
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(container);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [dive.video_uuid]);
  useEffect(() => {
    const button = containerRef.current?.closest('button')
    if (!button || !dive.video_uuid) return
    const warm = () => prepareLibraryPlayback(dive.video_uuid!, true)
    button.addEventListener('pointerenter', warm)
    button.addEventListener('focus', warm)
    button.addEventListener('pointerdown', warm)
    return () => {
      button.removeEventListener('pointerenter', warm)
      button.removeEventListener('focus', warm)
      button.removeEventListener('pointerdown', warm)
    }
  }, [dive.video_uuid])
  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden bg-app-panel-elevated ${compact ? "h-full w-full" : "aspect-[4/3] w-full"}`}
    >
      {preview?.posterUrl && !imgError ? (
        // Poster image from local media cache — instant, lightweight
        <img
          src={preview.posterUrl}
          alt={t('thumbnail.posterFor', { code: dive.dive_code })}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => setImgError(true)}
        />
      ) : preview?.videoThumbUrl || preview?.playbackUrl ? (
        // Poster missing (or failed to load) but a playable proxy exists —
        // e.g. the poster job failed while the proxy succeeded. Render the
        // video frame directly instead of a blank tile. Muted + no autoplay
        // so the grid stays silent and cheap; preload="metadata" shows the
        // first frame without downloading the whole clip.
        <video
          src={(preview.videoThumbUrl || preview.playbackUrl) as string}
          className="h-full w-full object-cover"
          muted
          playsInline
          preload="metadata"
          aria-label={t('thumbnail.posterFor', { code: dive.dive_code })}
        />
      ) : (
        // No media at all — show the dive code as a visual placeholder
        <div className="flex h-full w-full items-end bg-[linear-gradient(135deg,#243136_0%,#15191c_58%,#0d1113_100%)] p-3">
          <span
            className={`font-mono font-semibold tracking-tight text-app-muted ${compact ? "text-sm" : "text-xl"}`}
          >
            {dive.dive_code}
          </span>
        </div>
      )}
    </div>
  );
}
