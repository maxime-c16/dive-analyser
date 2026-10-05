import React, { useEffect, useRef, useState } from "react";
import { Film } from "lucide-react";
import { cachedPreview, getPreview, type MediaPreview } from "../utils/mediaPreview";
import type { Attempt } from "../utils/attemptPresentation";

export default function DiveThumbnail({
  dive,
  compact = false,
}: {
  dive: Attempt;
  compact?: boolean;
}) {
  const [preview, setPreview] = useState<MediaPreview | null>(() =>
    dive.video_uuid ? cachedPreview(dive.video_uuid) || null : null,
  );
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!dive.video_uuid) return;
    // If already cached, apply immediately — no network request needed.
    const cached = cachedPreview(dive.video_uuid);
    if (cached) {
      setPreview(cached);
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
            if (active) setPreview(result);
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
  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden bg-app-panel-elevated ${compact ? "h-full w-full" : "aspect-[4/3] w-full"}`}
    >
      {preview?.posterUrl ? (
        // Poster image from local media cache — instant, lightweight
        <img
          src={preview.posterUrl}
          alt={`Poster for ${dive.dive_code}`}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      ) : (
        // No media at all — show the dive code as a visual placeholder
        <div className="flex h-full w-full items-end bg-[linear-gradient(135deg,#243136_0%,#15191c_58%,#0d1113_100%)] p-3">
          <span className="font-mono text-xl font-semibold tracking-tight text-app-muted">
            {dive.dive_code}
          </span>
        </div>
      )}
      {dive.video_uuid &&
        (compact ? (
          <span
            className={`absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full border border-black/40 ${preview?.ready ? "bg-app-accent" : "bg-app-muted"}`}
            title={preview?.ready ? "Video ready" : "Video linked"}
            aria-label={preview?.ready ? "Video ready" : "Video linked"}
          />
        ) : (
          <span
            className={`absolute bottom-2 right-2 inline-flex items-center gap-1 border px-1.5 py-1 text-[10px] font-medium ${preview?.ready ? "border-app-accent bg-[#10221f]/95 text-app-accent" : "border-app bg-black/70 text-app-muted"}`}
          >
            <Film className="h-3 w-3" />
            {preview?.ready ? "Ready" : "Linked"}
          </span>
        ))}
    </div>
  );
}
