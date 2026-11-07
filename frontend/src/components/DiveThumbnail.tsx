import { Film } from 'lucide-react'
import { prepareLibraryPlayback } from '../utils/preparedPlayback'
import { useTranslation } from 'react-i18next'
import React, { useEffect, useMemo, useRef, useState } from "react";
import { cachedPreview, getPreview, type MediaPreview } from "../utils/mediaPreview";
import type { Attempt } from "../utils/attemptPresentation";

import { placeholderUrl } from "../utils/thumbhash";

export default function DiveThumbnail({
  dive,
  compact = false,
}: {
  dive: Pick<Attempt, "video_uuid" | "dive_code" | "thumb_url" | "animated_url" | "thumbhash">;
  compact?: boolean;
}) {
  const { t } = useTranslation()
  const [preview, setPreview] = useState<MediaPreview | null>(() =>
    dive.video_uuid ? cachedPreview(dive.video_uuid) || null : null,
  );
  const [visible, setVisible] = useState(false);
  const [motionAllowed, setMotionAllowed] = useState(false);
  const [animatedError, setAnimatedError] = useState(false);
  const animated = !animatedError && motionAllowed && visible && (dive.animated_url || preview?.animatedUrl);
  const [imgError, setImgError] = useState(false);
  const [thumbError, setThumbError] = useState(false);
  const thumb = !thumbError && (dive.thumb_url || preview?.thumbUrl);
  const placeholder = useMemo(() => placeholderUrl(dive.thumbhash || preview?.thumbhash), [dive.thumbhash, preview?.thumbhash]);
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const motion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const connection = (navigator as Navigator & { connection?: EventTarget & { saveData?: boolean } }).connection;
    const update = () => setMotionAllowed(Boolean(motion && !motion.matches && !connection?.saveData));
    update();
    motion?.addEventListener('change', update);
    connection?.addEventListener?.('change', update);
    const observer = new IntersectionObserver(entries => setVisible(entries[0].isIntersecting));
    if (containerRef.current) observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      motion?.removeEventListener('change', update);
      connection?.removeEventListener?.('change', update);
    };
  }, [dive.video_uuid]);
  useEffect(() => {
    setAnimatedError(false);
    setImgError(false);
    setThumbError(false);
    setPreview(dive.video_uuid ? cachedPreview(dive.video_uuid) || null : null);
    if (!dive.video_uuid) return;
    // If already cached, apply immediately — no network request needed.
    const cached = cachedPreview(dive.video_uuid);
    if (cached) {
      setPreview(cached);
      // Only the first two visible candidates are prepared speculatively —
      // and only when a cheap local web preview is already ready. Warming an
      // original-only or poster-only tile would mint a B2 playback grant per
      // tile, so those tiles render without any speculative element.
      const rect = containerRef.current?.getBoundingClientRect();
      if (cached.videoThumbUrl && rect && rect.bottom > 0 && rect.top < window.innerHeight) prepareLibraryPlayback(dive.video_uuid);
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
              if (result.videoThumbUrl) prepareLibraryPlayback(dive.video_uuid!);
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
      data-preview-state={(animated || thumb || (preview?.posterUrl && !imgError) || placeholder || (preview?.videoThumbUrl && !(dive.thumb_url || preview?.thumbUrl || dive.animated_url || preview?.animatedUrl))) ? 'ready' : preview === null && dive.video_uuid ? 'loading' : 'missing'}
      data-thumbhash={placeholder ? "ready" : undefined}
      style={placeholder ? { backgroundImage: `url(${placeholder})`, backgroundSize: "cover", backgroundPosition: "center" } : undefined}
      className={`relative overflow-hidden bg-app-panel-elevated ${compact ? "h-full w-full" : "aspect-[4/3] w-full"}`}
    >
      {(animated || thumb || (preview?.posterUrl && !imgError)) ? (
        // Poster image from local media cache — instant, lightweight
        <img
          src={animated || thumb || preview!.posterUrl!}
          alt={t('thumbnail.posterFor', { code: dive.dive_code })}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => animated ? setAnimatedError(true) : thumb ? setThumbError(true) : setImgError(true)}
        />
      ) : preview?.videoThumbUrl && !(dive.thumb_url || preview?.thumbUrl || dive.animated_url || preview?.animatedUrl) ? (
        // Poster missing (or failed to load) but a ready local web preview
        // exists — render its first frame directly instead of a blank tile.
        // Only already-ready cache previews are eligible here: the camera
        // original (B2 revision URL) must never load from a grid tile.
        // Muted + no autoplay so the grid stays silent and cheap;
        // preload="metadata" shows the first frame without downloading
        // the whole clip.
        <video
          src={preview.videoThumbUrl as string}
          className="h-full w-full object-cover"
          muted
          playsInline
          preload="metadata"
          aria-label={t('thumbnail.posterFor', { code: dive.dive_code })}
        />
      ) : placeholder ? null : (
        // No media at all — show the dive code as a visual placeholder
        <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-app-panel p-4 text-center text-app-muted">
          <Film size={28} strokeWidth={1.5} aria-hidden />
          <span className="text-sm leading-snug">{t(preview === null && dive.video_uuid ? 'thumbnail.loading' : 'thumbnail.unavailable')}</span>
          <span
            className="sr-only"
          >
            {dive.dive_code}
          </span>
        </div>
      )}
    </div>
  );
}
