import { Link, useSearchParams } from "react-router-dom";
import ProfileV1Classic from "./ProfileV1Classic";
import ProfileV2Sidebar from "./ProfileV2Sidebar";
import ProfileV3Diver from "./ProfileV3Diver";

/**
 * Standalone preview for the profile-page experiment.
 * Visit /profile-preview?v=1|2|3 — no auth required.
 */
export default function ProfilePreview() {
  const [params, setParams] = useSearchParams();
  const v = params.get("v") === "2" ? "2" : params.get("v") === "3" ? "3" : "1";

  const btn = (id: string, label: string, desc: string) => (
    <button
      key={id}
      onClick={() => setParams({ v: id })}
      aria-pressed={v === id}
      className={`touch-target flex-1 border px-3 py-2.5 text-left ${
        v === id ? "border-app-accent bg-app-panel-elevated" : "border-app bg-app-panel"
      }`}
    >
      <span className={`block text-sm font-semibold ${v === id ? "text-app-text" : "text-app-muted"}`}>
        {label}
      </span>
      <span className="block text-xs text-app-muted">{desc}</span>
    </button>
  );

  return (
    <div className="min-h-screen bg-app text-app-text">
      <div className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <Link to="/dives" className="text-sm text-app-muted hover:text-app-text">
            ← Back to Library
          </Link>
          <span className="border border-app-accent px-2 py-0.5 text-xs font-medium text-app-accent">
            PROTOTYPE — not saved
          </span>
        </div>
        <div className="mb-6 flex flex-col gap-2 sm:flex-row" role="group" aria-label="Choose version">
          {btn("1", "V1 · Classic tabs", "Safest evolution of Account")}
          {btn("2", "V2 · Sidebar settings", "Scales like GitHub settings")}
          {btn("3", "V3 · Diver card", "Diving-specific, mobile-first")}
        </div>
        {v === "1" && <ProfileV1Classic />}
        {v === "2" && <ProfileV2Sidebar />}
        {v === "3" && <ProfileV3Diver />}
        <footer className="mx-auto mt-8 max-w-2xl border-t border-app pt-4 text-xs leading-5 text-app-muted">
          Prototype renders with mock data (Alex Moreau). Nothing here writes to the API.
          Tell me which version to keep and I'll wire it to <code>/api/v1/auth/me</code> + password change.
        </footer>
      </div>
    </div>
  );
}
