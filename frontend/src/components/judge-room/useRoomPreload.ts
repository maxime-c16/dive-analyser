import { useEffect, useState } from "react";
import type { Dive } from "../../services/judgeRoomApi";

/** Eager room-scoped downloads start in the lobby; at most two fetches run.
 * Blob URLs are private to this mounted room and are revoked on exit/change.
 * No workspace/media-library capability is ever requested by a guest. */
export default function useRoomPreload(
  code: string | undefined,
  dives: Dive[],
) {
  const key = JSON.stringify([code, dives.map((d) => [d.id, d.playback_url])]);
  const [loaded, setLoaded] = useState<{
    key: string;
    urls: Record<number, string>;
  }>({ key: "", urls: {} });
  useEffect(() => {
    const abort = new AbortController();
    const blobs: string[] = [];
    const urls: Record<number, string> = {};
    let cursor = 0;
    const worker = async () => {
      while (!abort.signal.aborted && cursor < dives.length) {
        const dive = dives[cursor++];
        try {
          const response = await fetch(dive.playback_url, {
            credentials: "same-origin",
            signal: abort.signal,
          });
          if (!response.ok) throw new Error("Room preload unavailable");
          const blob = await response.blob();
          if (abort.signal.aborted) return;
          if (!blob.size) throw new Error("Empty room preview");
          const url = URL.createObjectURL(blob);
          blobs.push(url);
          urls[dive.id] = url;
        } catch {
          if (abort.signal.aborted) return;
          // Keep normal scoped streaming available when a preload fails.
          urls[dive.id] = dive.playback_url;
        }
        setLoaded({ key, urls: { ...urls } });
      }
    };
    void Promise.all([worker(), worker()]);
    return () => {
      abort.abort();
      blobs.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [key]);
  return loaded.key === key ? loaded.urls : {};
}
