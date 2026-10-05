import React, { lazy, Suspense, useEffect, useState } from "react";
import {
  Routes,
  Route,
  NavLink,
  Link,
  useLocation,
  Navigate,
} from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dives from "./pages/Dives";
import SharedDive from "./pages/SharedDive";
import { useAuth } from "./contexts/AuthContext";
import { WhatsNewProvider, WhatsNewButton } from "./components/WhatsNew";
import {
  BarChart3,
  BookOpen,
  CalendarDays,
  ChevronDown,
  Film,
  Gauge,
  HardDriveDownload,
  ShieldCheck,
  Menu,
  UserRound,
  Waves,
  X,
} from "lucide-react";
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Sessions = lazy(() => import("./pages/Sessions"));
const Journey = lazy(() => import("./pages/Journey"));
const DiveAnalysis = lazy(() => import("./pages/DiveAnalysis"));
const RepresentativeMedia = lazy(() => import("./pages/RepresentativeMedia"));
const MediaRecall = lazy(() => import("./pages/MediaRecall"));
const P5Canary = lazy(() => import("./pages/P5Canary"));
const Admin = lazy(() => import("./pages/Admin"));
const Account = lazy(() => import("./pages/Account"));

/** Library is the product home; everything else is secondary or operational. */
const primaryNav = [{ to: "/dives", label: "Library", icon: Waves }];

const secondaryNav = [
  { to: "/dashboard", label: "Overview", icon: Gauge },
  { to: "/journey", label: "Journey", icon: BookOpen },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/media/representatives", label: "Representatives", icon: Film },
  { to: "/sessions", label: "Sessions", icon: CalendarDays },
];

const operationsNav = [
  { to: "/media/recall", label: "Media recall", icon: HardDriveDownload },
  { to: "/admin", label: "System", icon: ShieldCheck },
];

const routeLabels: Record<string, string> = {
  "/": "Library",
  "/dashboard": "Overview",
  "/journey": "Journey",
  "/analytics": "Analytics",
  "/dives": "Library",
  "/media/representatives": "Representatives",
  "/media/recall": "Media recall",
  "/media/p5-canary": "Player canary",
  "/admin": "System",
  "/account": "Account",
  "/sessions": "Sessions",
};

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

function AppNavLink({
  to,
  label,
  icon: Icon,
  emphasis = false,
}: NavItem & { emphasis?: boolean }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        [
          "flex items-center gap-3 border border-transparent px-3 py-2.5 transition-colors",
          emphasis ? "text-base font-semibold" : "text-sm font-medium",
          isActive
            ? "border-app bg-app-panel text-app-text"
            : "text-app-muted hover:border-app hover:bg-app-panel/70 hover:text-app-text",
        ].join(" ")
      }
    >
      <Icon className={emphasis ? "h-5 w-5" : "h-4 w-4"} />
      <span>{label}</span>
    </NavLink>
  );
}

function OperationsDisclosure({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="operations-navigation"
        className={
          compact
            ? "touch-target flex w-full items-center justify-between border border-app bg-app-panel-elevated px-4 text-base font-medium text-app-muted"
            : "flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-app-muted hover:text-app-text"
        }
      >
        Operations
        <ChevronDown
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <nav
          id="operations-navigation"
          aria-label="Operations navigation"
          className={compact ? "mt-2 grid gap-2" : "mt-2 space-y-1"}
        >
          {operationsNav.map((item) => (
            <AppNavLink key={item.to} {...item} emphasis={compact} />
          ))}
        </nav>
      )}
    </div>
  );
}

type Crumb = { label: string; href?: string };

/**
 * User-visible breadcrumb trail for a pathname. Hidden operational routes
 * and deep viewer/analysis paths never expose router-internal hierarchy:
 * only destinations a user can actually navigate to become links.
 */
export function breadcrumbTrail(pathname: string): Crumb[] {
  const analysisMatch = pathname.match(/^\/dives\/analysis\/([^/]+)\/?$/);
  if (analysisMatch) {
    return [
      { label: "Library", href: "/dives" },
      { label: `${decodeURIComponent(analysisMatch[1])} analysis` },
    ];
  }
  switch (pathname) {
    case "/":
    case "/dives":
      return [{ label: "Library" }];
    case "/dashboard":
      return [{ label: "Overview" }];
    case "/journey":
      return [{ label: "Journey" }];
    case "/analytics":
      return [{ label: "Analytics" }];
    case "/sessions":
      return [{ label: "Sessions" }];
    case "/media/representatives":
      return [{ label: "Representatives" }];
    case "/media/recall":
      return [{ label: "Media recall" }];
    case "/media/p5-canary":
      return [{ label: "Player canary" }];
    case "/admin":
      return [{ label: "System" }];
    case "/account":
      return [{ label: "Account" }];
    default: {
      const last = pathname.split("/").filter(Boolean).pop();
      return [{ label: last ? last.replace(/-/g, " ") : "Library" }];
    }
  }
}

function Breadcrumbs() {
  const location = useLocation();
  const crumbs = breadcrumbTrail(location.pathname);

  return (
    <div className="mx-auto mb-4 hidden w-full max-w-[1320px] items-center gap-2 overflow-x-auto text-xs font-medium uppercase tracking-[0.14em] text-app-muted sm:flex">
      <Link to="/" className="hover:text-app-text">
        Dive Analyser
      </Link>
      {crumbs.map((crumb) => (
        <React.Fragment key={crumb.label}>
          <span>/</span>
          {crumb.href ? (
            <Link to={crumb.href} className="hover:text-app-text">
              {crumb.label}
            </Link>
          ) : (
            <span className="text-app-text">{crumb.label}</span>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

function MobileNavigation() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const { user } = useAuth();
  const friend = !user?.is_admin;
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
    <div className="sticky top-0 z-40 border-b border-app bg-app pt-safe lg:hidden">
      <div className="flex h-14 items-center justify-between px-4">
        <Link
          to="/dives"
          className="min-h-11 inline-flex items-center text-base font-semibold text-app-text"
        >
          Dive Analyser
        </Link>
        <div className="flex items-center gap-2">
          <WhatsNewButton compact />
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
          className="fixed inset-x-0 bottom-0 top-14 z-50 overflow-y-auto border-t border-app bg-app p-4 pb-safe shadow-[0_18px_40px_rgba(0,0,0,.35)]"
        >
          <nav aria-label="Primary navigation" className="grid gap-2">
            {primaryNav.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `touch-target flex items-center gap-3 border px-4 text-lg font-semibold ${isActive ? "border-app-strong bg-app-panel text-app-text" : "border-app bg-app-panel-elevated text-app-text"}`
                }
              >
                <Icon className="h-5 w-5" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
          <p className="mb-2 mt-5 px-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-app-muted">
            Review
          </p>
          <nav aria-label="Secondary navigation" className="grid gap-2">
            {secondaryNav.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
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
          <div className="mt-5">
            <NavLink
              to="/account"
              onClick={() => setOpen(false)}
              className="touch-target flex items-center gap-3 border border-app bg-app-panel-elevated px-4 text-base font-medium text-app-text"
            >
              <UserRound className="h-5 w-5" />
              <span>Account</span>
            </NavLink>
          </div>
          {!friend && (
            <div className="mt-5">
              <OperationsDisclosure compact />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const friend = !user?.is_admin;
  return (
    <div className="min-h-screen bg-app text-app-text">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <div className="flex min-h-screen w-full">
        <aside className="hidden w-64 shrink-0 border-r border-app lg:block" aria-label="Workspace sidebar">
          <div className="sticky top-0 flex min-h-screen flex-col px-5 py-6 pt-safe">
            <div className="border-b border-app pb-5">
              <div className="text-xl font-semibold text-app-text">
                Dive Analyser
              </div>
            </div>

            <nav className="mt-6 space-y-1" aria-label="Primary navigation">
              {primaryNav.map((item) => (
                <AppNavLink key={item.to} {...item} emphasis />
              ))}
            </nav>

            <div className="mt-6">
              <p className="px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-app-muted">
                Review
              </p>
              <nav
                className="mt-2 space-y-1"
                aria-label="Secondary navigation"
              >
                {secondaryNav.map((item) => (
                  <AppNavLink key={item.to} {...item} />
                ))}
              </nav>
            </div>

            {!friend && (
              <div className="mt-6">
                <OperationsDisclosure />
              </div>
            )}

            <div className="mt-auto border-t border-app pt-4">
              <div className="mb-3"><WhatsNewButton /></div>
              <div className="truncate px-3 text-xs text-app-muted">
                {user?.display_name ?? user?.email}
                {friend ? " · diver" : " · administrator"}
              </div>
              <nav aria-label="Account navigation" className="mt-2 space-y-1">
                <AppNavLink to="/account" label="Account" icon={UserRound} />
              </nav>
            </div>

          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <MobileNavigation />

          <main id="main-content" tabIndex={-1} className="flex-1">
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

/** `/` is the product entry: the Library. Query parameters are preserved. */
function RootRedirect() {
  const location = useLocation();
  return <Navigate to={`/dives${location.search}`} replace />;
}

/**
 * `/competitions` never owned unique content (it rendered Journey
 * directly). Compatibility redirect: old bookmarks land on Journey with
 * their query string intact; no separate page/component ownership.
 */
export function CompetitionsRedirect() {
  const location = useLocation();
  return <Navigate to={`/journey${location.search}`} replace />;
}

function NotFound() {
  return (
    <div className="app-panel mx-auto mt-10 max-w-lg py-10 text-center">
      <h1 className="text-2xl font-semibold text-app-text">Page not found</h1>
      <p className="mt-2 text-sm leading-6 text-app-muted">
        Nothing lives at this address.
      </p>
      <Link
        to="/dives"
        className="touch-target mt-6 inline-flex items-center gap-2 border border-app-accent bg-app-panel px-4 text-sm text-app-accent"
      >
        <Waves className="h-4 w-4" />
        Back to Library
      </Link>
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

/** Keep friends out of owner operations (Media recall, System). */
function OwnerGuard({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user?.is_admin) {
    return <Navigate to="/dives" replace />;
  }
  return <>{children}</>;
}

/** Logged-in visitors never need the auth pages. */
function AnonymousOnly({ children }: { children: React.ReactNode }) {
  const { user, checking } = useAuth();
  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-app-muted">
        Loading…
      </div>
    );
  }
  if (user) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

function Router() {
  return (
    <Routes>
      <Route path="/share/:shareId" element={<SharedDive />} />
      {/* Login / register live outside the Layout and need no auth */}
      <Route
        path="/login"
        element={
          <AnonymousOnly>
            <Login />
          </AnonymousOnly>
        }
      />
      <Route
        path="/register"
        element={
          <AnonymousOnly>
            <Register />
          </AnonymousOnly>
        }
      />

      {/* All other routes require a live session */}
      <Route
        path="*"
        element={
          <AuthGuard>
            <WhatsNewProvider><Layout>
              <Suspense fallback={<p role="status" className="py-8 text-sm text-app-muted">Loading page…</p>}>
                <Routes>
                  <Route path="/" element={<RootRedirect />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/journey" element={<Journey />} />
                  <Route path="/analytics" element={<Analytics />} />
                  <Route path="/dives" element={<Dives />} />
                  <Route path="/dives/analysis/:diveCode" element={<DiveAnalysis />} />
                  <Route
                    path="/media/representatives"
                    element={<RepresentativeMedia />}
                  />
                  <Route
                    path="/media/recall"
                    element={
                      <OwnerGuard>
                        <MediaRecall />
                      </OwnerGuard>
                    }
                  />
                  <Route path="/media/p5-canary" element={<P5Canary />} />
                  <Route
                    path="/admin"
                    element={
                      <OwnerGuard>
                        <Admin />
                      </OwnerGuard>
                    }
                  />
                  <Route path="/account" element={<Account />} />
                  <Route path="/sessions" element={<Sessions />} />
                  <Route
                    path="/competitions"
                    element={<CompetitionsRedirect />}
                  />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </Layout></WhatsNewProvider>
          </AuthGuard>
        }
      />
    </Routes>
  );
}

export default Router;
