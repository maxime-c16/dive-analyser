import React, { useEffect, useState } from "react";
import {
  Routes,
  Route,
  NavLink,
  Link,
  useLocation,
  Navigate,
} from "react-router-dom";
import Login from "./pages/Login";
import { useAuth } from "./contexts/AuthContext";
import {
  BarChart3,
  BookOpen,
  CalendarDays,
  Film,
  Gauge,
  HardDriveDownload,
  Medal,
  Menu,
  ShieldCheck,
  Waves,
  X,
} from "lucide-react";
import Dashboard from "./pages/Dashboard";
import Analytics from "./pages/Analytics";
import Dives from "./pages/Dives";
import Sessions from "./pages/Sessions";
import Journey from "./pages/Journey";
import DiveAnalysis from "./pages/DiveAnalysis";
import RepresentativeMedia from "./pages/RepresentativeMedia";
import MediaRecall from "./pages/MediaRecall";
import P5Canary from "./pages/P5Canary";
import Admin from "./pages/Admin";

const navItems = [
  { to: "/", label: "Overview", icon: Gauge },
  { to: "/journey", label: "Journey", icon: BookOpen },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/dives", label: "Dives", icon: Waves },
  { to: "/media/representatives", label: "Representatives", icon: Film },
  { to: "/media/recall", label: "Media recall", icon: HardDriveDownload },
  { to: "/media/p5-canary", label: "Player", icon: Film },
  { to: "/admin", label: "System", icon: ShieldCheck },
  { to: "/sessions", label: "Sessions", icon: CalendarDays },
  { to: "/competitions", label: "Competitions", icon: Medal },
];

const routeLabels: Record<string, string> = {
  "/": "Overview",
  "/journey": "Journey",
  "/analytics": "Analytics",
  "/dives": "Dives",
  "/media": "Media",
  "/media/representatives": "Representatives",
  "/media/recall": "Media recall",
  "/media/p5-canary": "Player",
  "/admin": "System",
  "/sessions": "Sessions",
  "/competitions": "Competitions",
};

function AppNavLink({ to, label, icon: Icon }: (typeof navItems)[number]) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        [
          "flex items-center gap-3 border border-transparent px-3 py-2.5 text-sm font-medium transition-colors",
          isActive
            ? "border-app bg-app-panel text-app-text"
            : "text-app-muted hover:border-app hover:bg-app-panel/70 hover:text-app-text",
        ].join(" ")
      }
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </NavLink>
  );
}

function Breadcrumbs() {
  const location = useLocation();
  const parts = location.pathname.split("/").filter(Boolean);
  const crumbs =
    parts.length === 0
      ? [{ href: "/", label: "Overview" }]
      : parts.map((part, index) => {
          const href = `/${parts.slice(0, index + 1).join("/")}`;
          return {
            href,
            label: routeLabels[href] ?? part.replace(/-/g, " "),
          };
        });

  return (
    <div className="mx-auto mb-4 hidden w-full max-w-[1320px] items-center gap-2 overflow-x-auto text-xs font-medium uppercase tracking-[0.14em] text-app-muted sm:flex">
      <Link to="/" className="hover:text-app-text">
        Dive Analyser
      </Link>
      {crumbs.map((crumb, index) => (
        <React.Fragment key={crumb.href}>
          <span>/</span>
          {index === crumbs.length - 1 ? (
            <span className="text-app-text">{crumb.label}</span>
          ) : (
            <Link to={crumb.href} className="hover:text-app-text">
              {crumb.label}
            </Link>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

function MobileNavigation() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const currentLabel = routeLabels[location.pathname] ?? "Workspace";

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  return (
    <div className="sticky top-0 z-40 border-b border-app bg-app lg:hidden">
      <div className="flex h-14 items-center justify-between px-4">
        <Link
          to="/"
          className="min-h-11 inline-flex items-center text-base font-semibold text-app-text"
        >
          Dive Analyser
        </Link>
        <div className="flex items-center gap-2">
          <span className="max-w-36 truncate text-sm text-app-muted">
            {currentLabel}
          </span>
          <button
            type="button"
            aria-expanded={open}
            aria-controls="mobile-navigation"
            onClick={() => setOpen((value) => !value)}
            className="touch-target inline-flex items-center justify-center border border-app bg-app-panel p-0 text-app-text"
            aria-label={open ? "Close navigation" : "Open navigation"}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      {open && (
        <div
          id="mobile-navigation"
          className="fixed inset-x-0 bottom-0 top-14 z-50 overflow-y-auto border-t border-app bg-app p-4 shadow-[0_18px_40px_rgba(0,0,0,.35)]"
        >
          <nav aria-label="Primary navigation" className="grid gap-2">
            {navItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `touch-target flex items-center gap-3 border px-4 text-base font-medium ${isActive ? "border-app-strong bg-app-panel text-app-text" : "border-app bg-app-panel-elevated text-app-muted"}`
                }
              >
                <Icon className="h-5 w-5" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </div>
      )}
    </div>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-app text-app-text">
      <div className="flex min-h-screen w-full">
        <aside className="hidden w-64 shrink-0 border-r border-app lg:block">
          <div className="sticky top-0 flex min-h-screen flex-col px-5 py-6">
            <div className="border-b border-app pb-5">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-app-muted">
                Dive Analyser
              </div>
              <div className="mt-2 text-xl font-semibold text-app-text">
                Training Workspace
              </div>
              <p className="mt-2 text-sm leading-6 text-app-muted">
                Operational view for review, progression, sessions, and
                competition prep.
              </p>
            </div>

            <nav className="mt-6 space-y-1">
              {navItems.map((item) => (
                <AppNavLink key={item.to} {...item} />
              ))}
            </nav>

            <div className="mt-auto border-t border-app pt-4 text-xs leading-5 text-app-muted">
              LAN / WireGuard workspace
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <MobileNavigation />

          <main className="flex-1">
            <div className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
              <Breadcrumbs />
              {children}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

/** Redirect unauthenticated visitors to /login, preserving the intended URL. */
function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, checking } = useAuth();
  const location = useLocation();
  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-app-muted">
        Loading…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
}

function Router() {
  return (
    <Routes>
      {/* Login is outside the Layout and needs no auth */}
      <Route path="/login" element={<Login />} />

      {/* All other routes require a live session */}
      <Route
        path="*"
        element={
          <AuthGuard>
            <Layout>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/dashboard" element={<Navigate to="/" replace />} />
                <Route path="/journey" element={<Journey />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/dives" element={<Dives />} />
                <Route path="/dives/analysis/:diveCode" element={<DiveAnalysis />} />
                <Route
                  path="/media/representatives"
                  element={<RepresentativeMedia />}
                />
                <Route path="/media/recall" element={<MediaRecall />} />
                <Route path="/media/p5-canary" element={<P5Canary />} />
                <Route path="/admin" element={<Admin />} />
                <Route path="/sessions" element={<Sessions />} />
                <Route path="/competitions" element={<Journey />} />
              </Routes>
            </Layout>
          </AuthGuard>
        }
      />
    </Routes>
  );
}

export default Router;
