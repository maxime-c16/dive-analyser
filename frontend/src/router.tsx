import React, { lazy, Suspense, useEffect, useState } from "react";
import {
  Routes,
  Route,
  NavLink,
  Link,
  useLocation,
  Navigate,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
// Side-effect i18next init: tests render Router standalone (no App shell),
// so the default instance must exist before any useTranslation consumer.
import "./i18n";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dives from "./pages/Dives";
import { useNavigationIntent } from "./hooks/useNavigationIntent";

import { useAuth } from "./contexts/AuthContext";
import MemberAvatar from './components/MemberAvatar'
import { WhatsNewProvider, WhatsNewButton } from "./components/WhatsNew";
import { NotificationsProvider, NotificationsButton } from "./components/Notifications";
import {
  BarChart3,
  Bell,
  BookOpen,
  CalendarDays,
  ChevronDown,
  ClipboardCheck,
  Film,
  Gauge,
  HardDriveDownload,
  ShieldCheck,
  Menu,
  UserRound,
  Users,
  Waves,
  X,
} from "lucide-react";
const loadSharedDive = () => import("./pages/SharedDive");
const SharedDive = lazy(loadSharedDive);
const loadDashboard = () => import("./pages/Dashboard");
const Dashboard = lazy(loadDashboard);
const loadAnalytics = () => import("./pages/Analytics");
const Analytics = lazy(loadAnalytics);
const loadSessions = () => import("./pages/Sessions");
const Sessions = lazy(loadSessions);
const loadJourney = () => import("./pages/Journey");
const Journey = lazy(loadJourney);
const loadDiveAnalysis = () => import("./pages/DiveAnalysis");
const DiveAnalysis = lazy(loadDiveAnalysis);
const loadRepresentativeMedia = () => import("./pages/RepresentativeMedia");
const RepresentativeMedia = lazy(loadRepresentativeMedia);
const loadMediaRecall = () => import("./pages/MediaRecall");
const MediaRecall = lazy(loadMediaRecall);
const loadP5Canary = () => import("./pages/P5Canary");
const P5Canary = lazy(loadP5Canary);
const loadAdmin = () => import("./pages/Admin");
const Admin = lazy(loadAdmin);
const AdminAccount = lazy(() => import("./pages/AdminAccount"));
const loadAccount = () => import("./pages/Account");
const Account = lazy(loadAccount);
const loadCommunity = () => import("./pages/Community");
const Community = lazy(loadCommunity);
const loadMemberProfile = () => import("./pages/MemberProfile");
const MemberProfile = lazy(loadMemberProfile);
const loadEvaluations = () => import("./pages/Evaluations");
const Evaluations = lazy(loadEvaluations);
// Design-review mock (fixture data, no backend): dev-only, never shipped.
const loadEvaluationDemo = (): Promise<{ default: React.ComponentType }> =>
  (import.meta.env.DEV ? import("./pages/EvaluationDemo") : Promise.resolve({ default: () => null })) as unknown as Promise<{ default: React.ComponentType }>;
const EvaluationDemo = lazy(loadEvaluationDemo);
const loadNotifications = () => import("./pages/Notifications");
const Notifications = lazy(loadNotifications);

const routeLoaders: Record<string, () => Promise<unknown>> = {
  '/dashboard': loadDashboard, '/analytics': loadAnalytics,
  '/sessions': loadSessions, '/journey': loadJourney,
  '/media/representatives': loadRepresentativeMedia, '/media/recall': loadMediaRecall,
  '/admin': loadAdmin, '/account': loadAccount, '/users': loadMemberProfile, '/notifications': loadNotifications,
  '/evaluations': loadEvaluations, '/community': loadCommunity,
};

function IntentNavLink(props: React.ComponentProps<typeof NavLink>) {
  const path = typeof props.to === 'string' ? props.to : props.to.pathname ?? '';
  const intent = useNavigationIntent(path, routeLoaders[path]);
  return <NavLink {...intent} {...props} />;
}

/**
 * Navigation labels are translation KEYS, not strings: components stay static
 * so a language change re-renders labels through useTranslation lookups.
 */
const primaryNav = [
  { to: "/dives", label: "nav.dives", icon: Waves } as NavItem,
  { to: "/community", label: "nav.community", icon: Users } as NavItem,
  { to: "/evaluations", label: "nav.evaluations", icon: ClipboardCheck } as NavItem,
];

const secondaryNav = [
  { to: "/dashboard", label: "nav.overview", icon: Gauge },
  { to: "/journey", label: "nav.journey", icon: BookOpen },
  { to: "/analytics", label: "nav.analytics", icon: BarChart3 },
  { to: "/media/representatives", label: "nav.representatives", icon: Film },
  { to: "/sessions", label: "nav.sessions", icon: CalendarDays },
  { to: "/notifications", label: "nav.notifications", icon: Bell },
];

const operationsNav = [
  { to: "/media/recall", label: "nav.mediaRecall", icon: HardDriveDownload },
  { to: "/admin", label: "nav.system", icon: ShieldCheck },
];

const routeLabelKeys: Record<string, string> = {
  "/": "nav.dives",
  "/dashboard": "nav.overview",
  "/journey": "nav.journey",
  "/analytics": "nav.analytics",
  "/dives": "nav.dives",
  "/evaluations": "nav.evaluations",
  "/community": "nav.community",
  "/media/representatives": "nav.representatives",
  "/media/recall": "nav.mediaRecall",
  "/media/p5-canary": "nav.playerCanary",
  "/admin": "nav.system",
  "/account": "nav.account",
  "/sessions": "nav.sessions",
  "/notifications": "nav.notifications",
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
  const { t } = useTranslation();
  return (
    <IntentNavLink
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
      <span>{t(label)}</span>
    </IntentNavLink>
  );
}

function OperationsDisclosure({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation();
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
        {t("nav.operations")}
        <ChevronDown
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <nav
          id="operations-navigation"
          aria-label={t("nav.operationsAria")}
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

type Crumb = { label?: string; href?: string; labelKey?: string };

/**
 * User-visible breadcrumb trail for a pathname. Hidden operational routes
 * and deep viewer/analysis paths never expose router-internal hierarchy:
 * only destinations a user can actually navigate to become links.
 */
export function breadcrumbTrail(
  pathname: string,
  translate: (key: string) => string = (key) => key,
): Crumb[] {
  const analysisMatch = pathname.match(/^\/dives\/analysis\/([^/]+)\/?$/);
  if (analysisMatch) {
    return [
      { labelKey: "nav.dives", href: "/dives" },
      { label: `${decodeURIComponent(analysisMatch[1])} ${translate("breadcrumbs.analysis")}` },
    ];
  }
  switch (pathname) {
    case "/":
    case "/dives":
      return [{ labelKey: "nav.dives" }];
    case "/dashboard":
      return [{ labelKey: "nav.overview" }];
    case "/journey":
      return [{ labelKey: "nav.journey" }];
    case "/analytics":
      return [{ labelKey: "nav.analytics" }];
    case "/sessions":
      return [{ labelKey: "nav.sessions" }];
    case "/notifications":
      return [{ labelKey: "nav.notifications" }];
    case "/media/representatives":
      return [{ labelKey: "nav.representatives" }];
    case "/media/recall":
      return [{ labelKey: "nav.mediaRecall" }];
    case "/media/p5-canary":
      return [{ labelKey: "nav.playerCanary" }];
    case "/admin":
      return [{ labelKey: "nav.system" }];
    case "/account":
      return [{ labelKey: "nav.account" }];
    default: {
      if (/^\/admin\/users\/\d+\/?$/.test(pathname)) return [{ labelKey: "nav.system", href: "/admin" }, { label: "Manage account" }];
      const usersMatch = pathname.match(/^\/users\/(\d+)\/?$/);
      if (usersMatch) return [{ labelKey: "nav.community", href: "/community" }, { labelKey: "profile.breadcrumb" }];
      const last = pathname.split("/").filter(Boolean).pop();
      return [{ label: last ? last.replace(/-/g, " ") : translate("nav.dives") }];
    }
  }
}

function Breadcrumbs() {
  const location = useLocation();
  const { t } = useTranslation();
  const crumbs = breadcrumbTrail(location.pathname, t);

  return (
    <div className="mx-auto mb-4 hidden w-full max-w-[1320px] items-center gap-2 overflow-x-auto text-xs font-medium uppercase tracking-[0.14em] text-app-muted sm:flex">
      <Link to="/" className="hover:text-app-text">
        Dive Analyser
      </Link>
      {crumbs.map((crumb, index) => {
        const label = crumb.labelKey ? t(crumb.labelKey) : crumb.label;
        return (
          <React.Fragment key={`${crumb.labelKey ?? crumb.label}-${index}`}>
            <span>/</span>
            {crumb.href ? (
              <Link to={crumb.href} className="hover:text-app-text">
                {label}
              </Link>
            ) : (
              <span className="text-app-text">{label}</span>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

function MobileNavigation() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const { user } = useAuth();
  const { t } = useTranslation();
  const friend = !user?.is_admin;
  const currentLabel = routeLabelKeys[location.pathname]
    ? t(routeLabelKeys[location.pathname])
    : /^\/users\/\d+\/?$/.test(location.pathname) ? t("profile.breadcrumb") : t("nav.workspace");

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
          <NotificationsButton compact />
          <span className="max-w-36 truncate text-sm text-app-muted">
            {currentLabel}
          </span>
          <button
            type="button"
            aria-expanded={open}
            aria-controls="mobile-navigation"
            onClick={() => setOpen((value) => !value)}
            className="touch-target inline-flex items-center justify-center border border-app bg-app-panel p-0 text-app-text"
            aria-label={open ? t("nav.closeNavigation") : t("nav.openNavigation")}
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
          <nav aria-label={t("nav.primaryNavigationAria")} className="grid gap-2">
            {primaryNav.map(({ to, label, icon: Icon }) => (
              <IntentNavLink
                key={to}
                to={to}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `touch-target flex items-center gap-3 border px-4 text-lg font-semibold ${isActive ? "border-app-strong bg-app-panel text-app-text" : "border-app bg-app-panel-elevated text-app-text"}`
                }
              >
                <Icon className="h-5 w-5" />
                <span>{t(label)}</span>
              </IntentNavLink>
            ))}
          </nav>
          <p className="mb-2 mt-5 px-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-app-muted">
            {t("nav.review")}
          </p>
          <nav aria-label={t("nav.secondaryNavigationAria")} className="grid gap-2">
            {secondaryNav.map(({ to, label, icon: Icon }) => (
              <IntentNavLink
                key={to}
                to={to}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `touch-target flex items-center gap-3 border px-4 text-base font-medium ${isActive ? "border-app-strong bg-app-panel text-app-text" : "border-app bg-app-panel-elevated text-app-muted"}`
                }
              >
                <Icon className="h-5 w-5" />
                <span>{t(label)}</span>
              </IntentNavLink>
            ))}
          </nav>
          <div className="mt-5">
            <IntentNavLink
              to="/account"
              onClick={() => setOpen(false)}
              className="touch-target flex items-center gap-3 border border-app bg-app-panel-elevated px-4 text-base font-medium text-app-text"
            >
              <UserRound className="h-5 w-5" />
              <span>{t("nav.account")}</span>
            </IntentNavLink>
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
  const { t } = useTranslation();
  const friend = !user?.is_admin;
  return (
    <div className="min-h-screen bg-app text-app-text">
      <a href="#main-content" className="skip-link">
        {t("nav.skipToContent")}
      </a>
      <div className="flex min-h-screen w-full">
        <aside className="hidden w-64 shrink-0 border-r border-app lg:block" aria-label={t("nav.workspaceSidebarAria")}>
          <div className="sticky top-0 flex min-h-screen flex-col px-5 py-6 pt-safe">
            <div className="border-b border-app pb-5">
              <div className="text-xl font-semibold text-app-text">
                Dive Analyser
              </div>
            </div>

            <nav className="mt-6 space-y-1" aria-label={t("nav.primaryNavigationAria")}>
              {primaryNav.map((item) => (
                <AppNavLink key={item.to} {...item} emphasis />
              ))}
            </nav>

            <div className="mt-6">
              <p className="px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-app-muted">
                {t("nav.review")}
              </p>
              <nav
                className="mt-2 space-y-1"
                aria-label={t("nav.secondaryNavigationAria")}
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
              <div className="mb-3 grid gap-2"><WhatsNewButton /><NotificationsButton /></div>
              <div className="flex items-center gap-2 px-3 text-xs text-app-muted">
                {user && <MemberAvatar member={user} size={32} />}
                <span className="truncate">{user?.display_name ?? user?.email}
                {friend ? ` · ${t("roles.diver")}` : ` · ${t("roles.administrator")}`}</span>
              </div>
              <nav aria-label={t("nav.accountNavigationAria")} className="mt-2 space-y-1">
                <AppNavLink to="/account" label="nav.account" icon={UserRound} />
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
  const { t } = useTranslation();
  return (
    <div className="app-panel mx-auto mt-10 max-w-lg py-10 text-center">
      <h1 className="text-2xl font-semibold text-app-text">{t("notFound.title")}</h1>
      <p className="mt-2 text-sm leading-6 text-app-muted">
        {t("notFound.body")}
      </p>
      <Link
        to="/dives"
        className="touch-target mt-6 inline-flex items-center gap-2 border border-app-accent bg-app-panel px-4 text-sm text-app-accent"
      >
        <Waves className="h-4 w-4" />
        {t("notFound.backToLibrary")}
      </Link>
    </div>
  );
}

/** Redirect unauthenticated visitors to /login, preserving the intended URL. */
function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, checking } = useAuth();
  const location = useLocation();
  const { t } = useTranslation();
  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-app-muted">
        {t("common.loading")}
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
  const { t } = useTranslation();
  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-app-muted">
        {t("common.loading")}
      </div>
    );
  }
  if (user) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

function Router() {
  const { t } = useTranslation();
  return (
    <Routes>
      <Route path="/share/:shareId" element={<Suspense fallback={<p role="status">{t("common.loadingPage")}</p>}><SharedDive /></Suspense>} />
      {/* Design-review mock (fixture data, no backend, no auth): dev build only. */}
      {import.meta.env.DEV && (
        <Route path="/evaluations-demo" element={<Suspense fallback={null}><EvaluationDemo /></Suspense>} />
      )}
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
            <WhatsNewProvider><NotificationsProvider><Layout>
              <Suspense fallback={<p role="status" className="py-8 text-sm text-app-muted">{t("common.loadingPage")}</p>}>
                <Routes>
                  <Route path="/" element={<RootRedirect />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/journey" element={<Journey />} />
                  <Route path="/analytics" element={<Analytics />} />
                <Route path="/dives" element={<Dives />} />
                <Route path="/evaluations" element={<Evaluations />} />
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
                  <Route path="/admin/users/:userId" element={<OwnerGuard><AdminAccount /></OwnerGuard>} />
                  <Route path="/account" element={<Account />} />
                  <Route path="/community" element={<Community />} />
                  <Route path="/users/:userId" element={<MemberProfile />} />
                  <Route path="/sessions" element={<Sessions />} />
                  <Route path="/notifications" element={<Notifications />} />
                  <Route
                    path="/competitions"
                    element={<CompetitionsRedirect />}
                  />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </Layout></NotificationsProvider></WhatsNewProvider>
          </AuthGuard>
        }
      />
    </Routes>
  );
}

export default Router;
