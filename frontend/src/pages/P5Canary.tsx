import React, { useEffect, useState } from "react";
import { LogIn, LogOut, ShieldCheck } from "lucide-react";

/**
 * Authenticated media player (bounded feature surface).
 *
 * Single playback source (GET /api/v1/media/revisions/{id}/play): the backend
 * chooses B2 (short-TTL presigned redirect) or an authenticated legacy
 * source transparently. The <video> element uses NO crossorigin
 * attribute and no fetch(): the redirect is followed by the element itself
 * and Range/seek requests go straight to the provider URL.
 */

interface CanaryRevision {
  media_revision_id: number;
  video_uuid: string;
  storage_location_id: number;
}

function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        setError("Login failed");
        return;
      }
      setPassword("");
      onLogin();
    } catch {
      setError("Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="mx-auto mt-8 max-w-sm border border-app bg-app-panel p-6"
    >
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4" /> Sign in
      </div>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        autoComplete="username"
        className="mb-3 w-full border border-app bg-app-panel-elevated px-3 py-2 text-sm"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        autoComplete="current-password"
        className="mb-3 w-full border border-app bg-app-panel-elevated px-3 py-2 text-sm"
        required
      />
      {error && <div className="mb-3 text-sm text-red-400">{error}</div>}
      <button
        type="submit"
        disabled={busy}
        className="touch-target inline-flex items-center gap-2 border border-app-strong bg-app-panel px-4 py-2 text-sm font-medium"
      >
        <LogIn className="h-4 w-4" /> {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

function P5Canary() {
  const [checked, setChecked] = useState(false);
  const [user, setUser] = useState<{ email: string } | null>(null);
  const [revisions, setRevisions] = useState<CanaryRevision[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const me = await fetch("/api/v1/auth/me", { credentials: "same-origin" });
      if (me.ok) {
        const body = await me.json();
        setUser({ email: body.email });
        const list = await fetch("/api/v1/media/playback/canary/revisions", {
          credentials: "same-origin",
        });
        if (list.ok) {
          const data = await list.json();
          setRevisions(data.revisions ?? []);
        } else {
          setRevisions([]);
        }
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setChecked(true);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  if (!checked) {
    return <div className="text-sm text-app-muted">Loading…</div>;
  }

  if (!user) {
    return <LoginPage onLogin={refresh} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Media player</h1>
        <button
          type="button"
          onClick={async () => {
            await fetch("/api/v1/auth/logout", {
              method: "POST",
              credentials: "same-origin",
            });
            setUser(null);
            setRevisions([]);
          }}
          className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-3 py-2 text-sm"
        >
          <LogOut className="h-4 w-4" /> Sign out ({user.email})
        </button>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      {revisions.length === 0 ? (
        <div className="border border-app bg-app-panel p-4 text-sm text-app-muted">
          No media.
        </div>
      ) : (
        <div className="grid gap-4">
          {revisions.map((revision) => (
            <div
              key={revision.media_revision_id}
              className="border border-app bg-app-panel p-3"
            >
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-app-muted">
                revision #{revision.media_revision_id} ·{" "}
                {revision.video_uuid.slice(0, 8)}…
              </div>
              {/* No crossorigin attribute by design (P5 §17): the browser
                  follows the 302 itself; Range/seek goes to the provider. */}
              <video
                controls
                preload="metadata"
                width="480"
                src={`/api/v1/media/revisions/${revision.media_revision_id}/play`}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default P5Canary;
