import { useState } from "react";
import { Award, CalendarDays, Film, KeyRound, LogOut, Waves } from "lucide-react";
import { inputCls, labelCls, initials, mockUser, Toggle } from "./shared";

/**
 * V3 — Diver card. Product-specific: identity + stats + quick toggles,
 * mobile-first stacked cards. Best fit for Dive Analyser's domain.
 */
export default function ProfileV3Diver() {
  const [name, setName] = useState(mockUser.display_name);
  const [notif, setNotif] = useState(true);
  const [autoplay, setAutoplay] = useState(false);
  const [weekly, setWeekly] = useState(true);

  const stats = [
    { icon: Film, value: String(mockUser.totalDives), label: "Dives" },
    { icon: CalendarDays, value: String(mockUser.totalSessions), label: "Sessions" },
    { icon: Award, value: mockUser.level, label: "Level" },
  ];

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-app-text">Profile</h1>
        <p className="mt-1 text-sm text-app-muted">Your diver identity and app preferences.</p>
      </header>

      {/* Diver identity card */}
      <section className="overflow-hidden border border-app bg-app-panel">
        <div className="h-20 bg-gradient-to-r from-[rgba(84,190,171,0.5)] via-[rgba(84,190,171,0.15)] to-transparent" />
        <div className="-mt-8 px-5 pb-5">
          <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-app bg-app-panel-elevated text-xl font-bold text-app-accent">
            {initials(name || mockUser.display_name)}
          </div>
          <h2 className="mt-2 text-xl font-semibold text-app-text">{name}</h2>
          <p className="text-sm text-app-muted">{mockUser.email} · {mockUser.role} · since {mockUser.memberSince}</p>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {stats.map(({ icon: Icon, value, label }) => (
              <div key={label} className="border border-app bg-app-panel-elevated px-2 py-3 text-center">
                <Icon className="mx-auto h-4 w-4 text-app-accent" />
                <div className="mt-1 truncate text-sm font-semibold text-app-text">{value}</div>
                <div className="text-[11px] uppercase tracking-wider text-app-muted">{label}</div>
              </div>
            ))}
          </div>
          <button className="touch-target mt-4 inline-flex w-full items-center justify-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm font-medium text-app-text">
            <Waves className="h-4 w-4" /> View public profile
          </button>
        </div>
      </section>

      {/* Edit */}
      <section className="border border-app bg-app-panel p-5">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-app-muted">Edit profile</h2>
        <div className="mt-3 space-y-3">
          <div>
            <label className={labelCls} htmlFor="v3-name">Display name</label>
            <input id="v3-name" className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="v3-bio">Focus this season</label>
            <input id="v3-bio" className={inputCls} defaultValue="Reverse 2½ — cleaner entry" />
          </div>
        </div>
      </section>

      {/* Quick settings */}
      <section className="border border-app bg-app-panel p-5">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-app-muted">Quick settings</h2>
        <div className="mt-2 divide-y divide-[rgba(82,96,105,0.25)]">
          {[
            { l: "Milestone alerts", d: "Personal bests & streaks", v: notif, f: () => setNotif(!notif) },
            { l: "Autoplay clips", d: "Hover to preview in Library", v: autoplay, f: () => setAutoplay(!autoplay) },
            { l: "Monday digest", d: "Weekly progress email", v: weekly, f: () => setWeekly(!weekly) },
          ].map((r) => (
            <div key={r.l} className="flex items-center justify-between gap-4 py-3">
              <div>
                <div className="text-sm font-medium text-app-text">{r.l}</div>
                <div className="text-xs text-app-muted">{r.d}</div>
              </div>
              <Toggle checked={r.v} onChange={r.f} label={r.l} />
            </div>
          ))}
        </div>
      </section>

      {/* Security compact */}
      <section className="border border-app bg-app-panel p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.12em] text-app-muted">
          <KeyRound className="h-4 w-4" /> Security
        </h2>
        <div className="mt-3 flex gap-2">
          <input type="password" placeholder="New password (10+ chars)" className={inputCls} aria-label="New password" />
          <button className="touch-target shrink-0 bg-app-accent px-4 text-sm font-semibold text-black">Set</button>
        </div>
        <button className="touch-target mt-3 inline-flex items-center gap-2 text-sm text-app-muted hover:text-app-text">
          <LogOut className="h-4 w-4" /> Sign out
        </button>
      </section>
    </div>
  );
}
