import { useState } from "react";
import {
  Bell,
  Eye,
  KeyRound,
  LogOut,
  Palette,
  UserRound,
} from "lucide-react";
import { inputCls, labelCls, initials, mockUser, Toggle } from "./shared";

/**
 * V2 — Sidebar settings (GitHub-style). Left nav, right content.
 * Best for a growing settings surface.
 */
const sections = [
  { id: "profile", label: "Profile", icon: UserRound },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "privacy", label: "Privacy", icon: Eye },
  { id: "security", label: "Security", icon: KeyRound },
] as const;

type SectionId = (typeof sections)[number]["id"];

export default function ProfileV2Sidebar() {
  const [section, setSection] = useState<SectionId>("profile");
  const [emailNotif, setEmailNotif] = useState(true);
  const [pushNotif, setPushNotif] = useState(false);
  const [publicProfile, setPublicProfile] = useState(true);
  const [autoplay, setAutoplay] = useState(true);
  const [density, setDensity] = useState("comfortable");

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-5 border-b border-app pb-4">
        <h1 className="text-3xl font-semibold tracking-tight text-app-text">Profile & settings</h1>
        <p className="mt-1 text-sm text-app-muted">Manage your identity, preferences and security.</p>
      </header>

      <div className="grid gap-5 md:grid-cols-[220px_1fr]">
        {/* Sidebar */}
        <nav aria-label="Settings sections" className="h-fit border border-app bg-app-panel p-2 md:sticky md:top-4">
          {sections.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setSection(id)}
              aria-current={section === id ? "page" : undefined}
              className={`touch-target flex w-full items-center gap-3 px-3 text-sm font-medium ${
                section === id
                  ? "border border-app bg-app-panel-elevated text-app-text"
                  : "border border-transparent text-app-muted hover:text-app-text"
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
          <div className="mt-2 border-t border-app pt-2">
            <button className="touch-target flex w-full items-center gap-3 px-3 text-sm text-app-muted hover:text-app-text">
              <LogOut className="h-4 w-4" /> Sign out
            </button>
          </div>
        </nav>

        {/* Content */}
        <div className="min-w-0 space-y-5">
          {section === "profile" && (
            <section className="border border-app bg-app-panel p-5">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-app-panel-elevated text-lg font-bold text-app-accent ring-1 ring-app-accent">
                  {initials(mockUser.display_name)}
                </div>
                <div>
                  <button className="touch-target border border-app bg-app-panel-elevated px-3 text-sm text-app-text">
                    Upload photo
                  </button>
                  <p className="mt-1 text-xs text-app-muted">PNG or JPG, max 2 MB</p>
                </div>
              </div>
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <div>
                  <label className={labelCls}>Display name</label>
                  <input className={inputCls} defaultValue={mockUser.display_name} />
                </div>
                <div>
                  <label className={labelCls}>Email</label>
                  <input className={inputCls} defaultValue={mockUser.email} />
                </div>
                <div className="sm:col-span-2">
                  <label className={labelCls}>Bio</label>
                  <textarea className={inputCls} rows={3} defaultValue="Coach · Lyon Plongeon · 3m & platform" />
                </div>
              </div>
              <button className="touch-target mt-5 bg-app-accent px-4 py-2.5 text-sm font-semibold text-black">
                Save profile
              </button>
            </section>
          )}

          {section === "notifications" && (
            <section className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">Notifications</h2>
              <div className="mt-3 divide-y divide-[rgba(82,96,105,0.25)]">
                {[
                  { label: "Email notifications", desc: "Milestones, comments, shares", v: emailNotif, s: () => setEmailNotif(!emailNotif) },
                  { label: "Push notifications", desc: "Only on this device", v: pushNotif, s: () => setPushNotif(!pushNotif) },
                ].map((r) => (
                  <div key={r.label} className="flex items-center justify-between gap-4 py-3">
                    <div>
                      <div className="text-sm font-medium text-app-text">{r.label}</div>
                      <div className="text-xs text-app-muted">{r.desc}</div>
                    </div>
                    <Toggle checked={r.v} onChange={r.s} label={r.label} />
                  </div>
                ))}
              </div>
            </section>
          )}

          {section === "appearance" && (
            <section className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">Appearance</h2>
              <p className="mt-1 text-sm text-app-muted">Density affects Library and Session lists.</p>
              <div className="mt-4 grid grid-cols-2 gap-3">
                {(["comfortable", "compact"] as const).map((d) => (
                  <button
                    key={d}
                    onClick={() => setDensity(d)}
                    aria-pressed={density === d}
                    className={`border p-4 text-left text-sm font-medium capitalize ${
                      density === d ? "border-app-accent text-app-text" : "border-app text-app-muted"
                    }`}
                  >
                    {d}
                    <span className="mt-1 block text-xs font-normal normal-case text-app-muted">
                      {d === "comfortable" ? "Larger rows, more breathing room" : "More dives per screen"}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {section === "privacy" && (
            <section className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">Privacy</h2>
              <div className="mt-3 divide-y divide-[rgba(82,96,105,0.25)]">
                <div className="flex items-center justify-between gap-4 py-3">
                  <div>
                    <div className="text-sm font-medium text-app-text">Public profile</div>
                    <div className="text-xs text-app-muted">Anyone with a share link can see your name</div>
                  </div>
                  <Toggle checked={publicProfile} onChange={() => setPublicProfile(!publicProfile)} label="Public profile" />
                </div>
                <div className="flex items-center justify-between gap-4 py-3">
                  <div>
                    <div className="text-sm font-medium text-app-text">Autoplay clips</div>
                    <div className="text-xs text-app-muted">Play dive clips on hover in Library</div>
                  </div>
                  <Toggle checked={autoplay} onChange={() => setAutoplay(!autoplay)} label="Autoplay clips" />
                </div>
              </div>
            </section>
          )}

          {section === "security" && (
            <section className="border border-app bg-app-panel p-5">
              <h2 className="flex items-center gap-2 font-semibold text-app-text">
                <KeyRound className="h-4 w-4 text-app-accent" /> Security
              </h2>
              <div className="mt-4 space-y-4">
                <div>
                  <label className={labelCls}>Current password</label>
                  <input type="password" className={inputCls} />
                </div>
                <div>
                  <label className={labelCls}>New password</label>
                  <input type="password" className={inputCls} />
                </div>
                <button className="touch-target border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text">
                  Change password
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
