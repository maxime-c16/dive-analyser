import { useState } from "react";
import { Bell, KeyRound, LogOut, Save, UserRound } from "lucide-react";
import { inputCls, labelCls, initials, mockUser, Toggle } from "./shared";

/**
 * V1 — Classic tabs. Closest evolution of the current Account page:
 * hero header + tab bar (Profile / Security / Preferences).
 */
export default function ProfileV1Classic() {
  const [tab, setTab] = useState<"profile" | "security" | "prefs">("profile");
  const [name, setName] = useState(mockUser.display_name);
  const [emailNotif, setEmailNotif] = useState(true);
  const [weeklyDigest, setWeeklyDigest] = useState(false);
  const [saved, setSaved] = useState(false);

  const tabs = [
    { id: "profile" as const, label: "Profile", icon: UserRound },
    { id: "security" as const, label: "Security", icon: KeyRound },
    { id: "prefs" as const, label: "Preferences", icon: Bell },
  ];

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* Hero */}
      <header className="border border-app bg-app-panel p-5 sm:p-6">
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-app-accent text-xl font-bold text-black">
            {initials(mockUser.display_name)}
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold text-app-text">{mockUser.display_name}</h1>
            <p className="truncate text-sm text-app-muted">{mockUser.email}</p>
            <div className="mt-2 flex gap-2">
              <span className="border border-app-accent px-2 py-0.5 text-xs font-medium text-app-accent">
                {mockUser.role}
              </span>
              <span className="border border-app px-2 py-0.5 text-xs text-app-muted">
                Member since {mockUser.memberSince}
              </span>
            </div>
          </div>
        </div>
        {/* Tabs */}
        <div role="tablist" aria-label="Profile sections" className="mt-5 flex gap-1 border-t border-app pt-4">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              onClick={() => { setTab(id); setSaved(false); }}
              className={`touch-target inline-flex items-center gap-2 px-4 text-sm font-medium ${
                tab === id
                  ? "bg-app-panel-elevated text-app-text underline decoration-app-accent decoration-2 underline-offset-8"
                  : "text-app-muted hover:text-app-text"
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
      </header>

      {tab === "profile" && (
        <section className="border border-app bg-app-panel p-5">
          <h2 className="font-semibold text-app-text">Profile details</h2>
          <p className="mt-1 text-sm text-app-muted">How you appear across shared dives and comments.</p>
          <div className="mt-4 space-y-4">
            <div>
              <label className={labelCls} htmlFor="v1-name">Display name</label>
              <input id="v1-name" className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className={labelCls} htmlFor="v1-bio">Bio</label>
              <textarea
                id="v1-bio"
                rows={3}
                defaultValue="3m springboard · working on reverse 2½"
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls} htmlFor="v1-level">Level</label>
                <select id="v1-level" className={inputCls} defaultValue={mockUser.level}>
                  <option>Regional</option>
                  <option>National</option>
                  <option>International</option>
                  <option>Recreational</option>
                </select>
              </div>
              <div>
                <label className={labelCls} htmlFor="v1-club">Club</label>
                <input id="v1-club" className={inputCls} defaultValue="Lyon Plongeon" />
              </div>
            </div>
            {saved && <p className="text-sm text-app-accent">Profile saved.</p>}
            <button
              onClick={() => setSaved(true)}
              className="touch-target inline-flex items-center gap-2 bg-app-accent px-4 py-2.5 text-sm font-semibold text-black"
            >
              <Save className="h-4 w-4" /> Save changes
            </button>
          </div>
        </section>
      )}

      {tab === "security" && (
        <section className="space-y-4">
          <div className="border border-app bg-app-panel p-5">
            <h2 className="flex items-center gap-2 font-semibold text-app-text">
              <KeyRound className="h-4 w-4 text-app-accent" /> Change password
            </h2>
            <div className="mt-4 space-y-4">
              <div>
                <label className={labelCls}>Current password</label>
                <input type="password" className={inputCls} placeholder="••••••••••" />
              </div>
              <div>
                <label className={labelCls}>New password (10+ characters)</label>
                <input type="password" className={inputCls} placeholder="New password" />
              </div>
              <button className="touch-target border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text">
                Change password
              </button>
            </div>
          </div>
          <div className="border border-app bg-app-panel p-5">
            <h2 className="font-semibold text-app-text">Sessions</h2>
            <p className="mt-1 text-sm text-app-muted">MacBook Pro · Lyon, FR — current session</p>
            <button className="touch-target mt-3 inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm text-app-text">
              <LogOut className="h-4 w-4" /> Sign out everywhere else
            </button>
          </div>
        </section>
      )}

      {tab === "prefs" && (
        <section className="border border-app bg-app-panel p-5">
          <h2 className="font-semibold text-app-text">Preferences</h2>
          <div className="mt-4 divide-y divide-[rgba(82,96,105,0.25)]">
            <div className="flex items-center justify-between gap-4 py-3">
              <div>
                <div className="text-sm font-medium text-app-text">Email notifications</div>
                <div className="text-xs text-app-muted">Milestones and shared-dive comments</div>
              </div>
              <Toggle checked={emailNotif} onChange={() => setEmailNotif(!emailNotif)} label="Email notifications" />
            </div>
            <div className="flex items-center justify-between gap-4 py-3">
              <div>
                <div className="text-sm font-medium text-app-text">Weekly digest</div>
                <div className="text-xs text-app-muted">Progress summary every Monday</div>
              </div>
              <Toggle checked={weeklyDigest} onChange={() => setWeeklyDigest(!weeklyDigest)} label="Weekly digest" />
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
