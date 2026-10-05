// Standalone, development-only review fixture. Never imported by the app.
// Counters/comments are fixture data; real API authorization is tested separately.
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../../src/contexts/AuthContext";
import ClipViewer from "../../src/components/clip-viewer/ClipViewer";
import { api } from "../../src/services/api";
import type { Attempt } from "../../src/utils/attemptPresentation";
import "../../src/index.css";
if (!import.meta.env.DEV) throw new Error("Review fixture is development-only");
const originalFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = String(input);
  if (url === "/api/v1/auth/me")
    return Response.json({
      user_id: 1,
      email: "review@example.test",
      display_name: "Reviewer",
      role: "owner",
      divers: [],
    });
  if (url === "/api/v1/media/status/batch") return Response.json({});
  if (/\/media\/.*\/status$/.test(url))
    return Response.json({
      status: "ready",
      can_request: false,
      available_renditions: ["proxy_360p"],
      playback_url: "/player-review.mp4",
    });
  return originalFetch(input, init);
};
const states = new Map<
  number,
  { liked: boolean; like_count: number; comment_count: number }
>();
import type { Comment } from "../../src/components/clip-viewer/useDiveSocial";
const discussion = new Map<number, Comment[]>();
const shareCounts = new Map<number, number>();
api.defaults.adapter = async (config) => {
  const id = Number(config.url?.match(/dives\/(\d+)/)?.[1] || 1);
  if (config.url?.endsWith('/shares')) {
    let data: unknown;
    if (config.method === 'post') {
      shareCounts.set(id, (shareCounts.get(id) ?? 0) + 1);
      data = { path: `/share/${id}#review-only` };
    } else if (config.method === 'delete') {
      shareCounts.set(id, 0);
      data = {};
    } else data = { active_count: shareCounts.get(id) ?? 0 };
    return { data, status: 200, statusText: 'OK', headers: {}, config };
  }
  if (!states.has(id))
    states.set(id, { liked: false, like_count: 12, comment_count: 2 });
  if (!discussion.has(id))
    discussion.set(id, [
      {
        id: 2, liked: false, like_count: 0, reply_count: 0,
        body: "The entry is getting cleaner. Keep that line!",
        author: "Camille",
        user_id: 2,
        created_at: "2026-10-05T09:00:00Z",
      },
      {
        id: 1, liked: false, like_count: 0, reply_count: 0,
        body: "One more rep. Focus on the opening.",
        author: "Reviewer",
        user_id: 1,
        created_at: "2026-10-05T08:00:00Z",
      },
    ]);
  const state = states.get(id)!;
  let data: unknown = { ...state };
  if (/comments\/\d+\/like$/.test(config.url || "")) {
    const commentId = Number(config.url!.split("/").slice(-2)[0]);
    const row = discussion.get(id)!.find(item => item.id === commentId)!;
    const { liked } = JSON.parse(config.data);
    row.like_count = (row.like_count ?? 0) + Number(liked) - Number(row.liked ?? false);
    row.liked = liked;
    data = { ...row };
  } else if (config.url?.endsWith("/like")) {
    const { liked } = JSON.parse(config.data);
    state.like_count += Number(liked) - Number(state.liked);
    state.liked = liked;
    data = { ...state };
  } else if (config.url?.includes("/comments")) {
    if (config.method === "post") {
      data = {
        id: Date.now(),
        body: JSON.parse(config.data).body,
        parent_id: JSON.parse(config.data).parent_id ?? null,
        liked: false, like_count: 0, reply_count: 0,
        author: "Reviewer",
        user_id: 1,
        created_at: new Date().toISOString(),
      };
      discussion.get(id)!.unshift(data as never);
      const parentId = (data as Comment).parent_id;
      const parent = discussion.get(id)!.find(row => row.id === parentId);
      if (parent) parent.reply_count = (parent.reply_count ?? 0) + 1;
      state.comment_count++;
    } else if (config.method === "delete") {
      const commentId = Number(config.url.split("/").pop());
      const rows = discussion.get(id)!;
      const removed = rows.filter(row => row.id === commentId || row.parent_id === commentId);
      const parent = rows.find(row => row.id === removed[0]?.parent_id);
      if (parent) parent.reply_count = Math.max(0, (parent.reply_count ?? 0) - 1);
      discussion.set(id, rows.filter(row => row.id !== commentId && row.parent_id !== commentId));
      state.comment_count -= removed.length;
    } else {
      const parentId = config.params?.parent_id ?? null;
      const items = discussion.get(id)!.filter(row => (row.parent_id ?? null) === parentId);
      data = { items: items.map(row => ({ ...row })), next_before: null };
    }
  }
  return { data, status: 200, statusText: "OK", headers: {}, config };
};
const attempts: Attempt[] = ["201C", "103B", "301C"].map((dive_code, i) => ({
  id: i + 1,
  dive_code,
  height: "1m",
  platform_type: "springboard",
  dive_datetime: "2026-10-03T10:00:00",
  performance: "G",
  performance_numeric: 3,
  session_id: 1,
  is_lineup: false,
  is_sync: false,
  official_dd: 1.7,
  phase1_performance: "G",
  phase2_performance: "G",
  notes: "Find the height. Hold the line. Trust the entry.",
  raw_caption: `${dive_code} G/G`,
  video_uuid: `review-${i}`,
  visibility: "public",
  can_manage: true,
}));
function Review() {
  const [attempt, setAttempt] = useState(attempts[0]);
  const [rate, setRate] = useState(1);
  const [open, setOpen] = useState(true);
  return (
    <MemoryRouter>
      <AuthProvider>
        {open ? (
          <ClipViewer
            attempt={attempt}
            attempts={attempts}
            onClose={() => setOpen(false)}
            onMove={setAttempt}
            playbackRate={rate}
            onPlaybackRateChange={setRate}
          />
        ) : (
          <button onClick={() => setOpen(true)}>Open player review</button>
        )}
      </AuthProvider>
    </MemoryRouter>
  );
}
createRoot(document.getElementById("root")!).render(<Review />);
