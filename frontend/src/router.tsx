import { primaryTabFor, type PrimaryTab } from './navigation/mobileNavigation'
import { useMobileNavPolicy, useTabMemory } from './navigation/useMobileNavigation'
import './navigation/mobileNavigation.css'
import { useModalOverlay } from './utils/overlays'
import React, { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";
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
import { MessagesUnreadProvider, MessagesUnreadBadge, useMessagesUnreadAria } from "./components/MessagesUnread";
import {
  BarChart3,
  Send,
  BookOpen,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Film,
  Gauge,
  HardDriveDownload,
  ShieldCheck,
  UserRound,
  Users,
  Waves,
  X,
} from "lucide-react";
const SeriesPage = lazy(() => import("./pages/Series"));
const loadCalendar = () => import("./pages/Calendar");
const CalendarPage = lazy(loadCalendar);
const loadSharedDive = () => import("./pages/SharedDive");
const SharedDive = lazy(loadSharedDive);
const loadClaim = () => import("./pages/Claim");
const Claim = lazy(loadClaim);
const loadInvite = () => import("./pages/Invite");
const Invite = lazy(loadInvite);
const loadDeposits = () => import("./pages/Deposits");
const Deposits = lazy(loadDeposits);
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
const loadMessages = () => import("./pages/Messages");
const Messages = lazy(loadMessages);
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
  '/messages': loadMessages, '/evaluations': loadEvaluations, '/community': loadCommunity,
  '/calendar': loadCalendar,
};

function IntentNavLink({ primaryActive, ...props }: React.ComponentProps<typeof NavLink> & { primaryActive?: boolean }) {
  const targetPath = typeof props.to === 'string' ? props.to : props.to.pathname ?? '';
  const path = targetPath.split(/[?#]/)[0];
  const intent = useNavigationIntent(path, routeLoaders[path]);
  if (primaryActive !== undefined) return <Link {...intent} {...props} className={typeof props.className === 'string' ? props.className : undefined} style={typeof props.style === 'object' ? props.style : undefined} aria-current={primaryActive ? 'page' : undefined}>{typeof props.children === 'function' ? null : props.children}</Link>;
  return <NavLink {...intent} {...props} />;
}

/**
 * Navigation labels are translation KEYS, not strings: components stay static
 * so a language change re-renders labels through useTranslation lookups.
 */
const basePrimaryNav = [
  { to: "/dives", label: "nav.dives", icon: Waves } as NavItem,
  { to: "/messages", label: "nav.messages", icon: Send } as NavItem,
  { to: "/community", label: "nav.community", icon: Users } as NavItem,
  { to: "/evaluations", label: "nav.evaluations", icon: ClipboardCheck } as NavItem,
];
const calendarNavItem = { to: '/calendar', label: 'nav.calendar', icon: CalendarDays } as NavItem;

/** Calendar is a server-flagged destination (CALENDAR_ENABLED, default off):
 * off keeps the existing four labelled mobile targets; on gives five
 * equal icon-only targets with accessible names. */
function useCalendarEnabled(): boolean {
  const { user } = useAuth();
  return user?.features?.calendar === true;
}

function usePrimaryNav(): NavItem[] {
  const calendar = useCalendarEnabled();
  return calendar ? [...basePrimaryNav.slice(0, 3), calendarNavItem, basePrimaryNav[3]] : basePrimaryNav;
}

const secondaryNav = [
  { to: "/dashboard", label: "nav.overview", icon: Gauge },
  { to: "/journey", label: "nav.journey", icon: BookOpen },
  { to: "/analytics", label: "nav.analytics", icon: BarChart3 },
  { to: "/media/representatives", label: "nav.representatives", icon: Film },
  { to: "/sessions", label: "nav.sessions", icon: CalendarDays },
];

const operationsNav = [
  { to: "/media/recall", label: "nav.mediaRecall", icon: HardDriveDownload },
  { to: "/admin", label: "nav.system", icon: ShieldCheck },
];

const routeLabelKeys: Record<string, string> = {
  "/": "nav.dives",
  "/calendar": "nav.calendar",
  "/messages": "nav.messages",
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
  const messagesAria = useMessagesUnreadAria();
  return (
    <IntentNavLink
      to={to}
      end={to === "/"}
      aria-label={to === "/messages" ? messagesAria : undefined}
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
      {to === "/messages" && <MessagesUnreadBadge className="ml-auto" />}
    </IntentNavLink>
  );
}

function NavigationDisclosure({ compact = false, review = false }: { compact?: boolean; review?: boolean }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation();
  const id = `${review ? "review" : "operations"}-navigation${compact ? "-mobile" : "-desktop"}`;
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={id}
        className={
          compact
            ? "touch-target flex w-full items-center justify-between border border-app bg-app-panel-elevated px-4 text-base font-medium text-app-muted"
            : "flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-app-muted hover:text-app-text"
        }
      >
        {t(review ? "nav.review" : "nav.operations")}
        <ChevronDown
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <nav
          id={id}
          aria-label={t(review ? "nav.secondaryNavigationAria" : "nav.operationsAria")}
          className={compact ? "mt-2 grid gap-2" : "mt-2 space-y-1"}
        >
          {(review ? secondaryNav : operationsNav).map((item) => (
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
  if (/^\/calendar(?:\/|$)/.test(pathname)) return [{ labelKey: "nav.calendar", href: pathname === "/calendar" ? undefined : "/calendar" }];
  if (pathname === "/messages" || /^\/messages\/\d+\/?$/.test(pathname)) return [{ labelKey: "nav.messages" }];
  if (/^\/series(?:\/|$)/.test(pathname)) return [{ labelKey: "series.mySeries", href: pathname === "/series" ? undefined : "/series" }];
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
  if (location.pathname === "/dives") return null;

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
  const tab = primaryTabFor(location.pathname);
  const currentLabel = /^\/series(?:\/|$)/.test(location.pathname) ? t("series.mySeries") : routeLabelKeys[location.pathname]
    ? t(routeLabelKeys[location.pathname])
    : tab ? t(`nav.${tab}`) : t("nav.workspace");

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  useModalOverlay(menuRef, { enabled: open, onClose: () => setOpen(false), returnFocus: () => menuTriggerRef.current });
  useEffect(() => {
    const media = window.matchMedia?.('(min-width: 1024px)');
    if (!media) return;
    const closeOnDesktop = () => { if (media.matches) setOpen(false); };
    closeOnDesktop();
    media.addEventListener('change', closeOnDesktop);
    return () => media.removeEventListener('change', closeOnDesktop);
  }, []);

  return (
    <header className="mobile-header sticky top-0 z-40 border-b border-app bg-app pt-safe lg:hidden">
      <div className="flex min-h-14 items-center justify-between gap-2 px-4">
        <Link to={tab ? `/${tab}` : "/dives"} className="min-h-11 inline-flex min-w-0 items-center text-base font-semibold text-app-text">{currentLabel}</Link>
        <div className="flex shrink-0 items-center gap-2">
          <NotificationsButton compact />
          <button type="button" aria-expanded={open} ref={menuTriggerRef} aria-controls="mobile-navigation"
            onClick={() => setOpen(true)} className="mobile-account-trigger touch-target inline-flex items-center justify-center rounded-full border border-app bg-app-panel text-app-text"
            aria-label={t("nav.accountNavigationAria")}>
            {user ? <MemberAvatar member={user} size={32} /> : <UserRound className="h-5 w-5" />}
          </button>
        </div>
      </div>
      {open && <div className="fixed inset-0 z-50 bg-black/50" onClick={() => setOpen(false)}>
        <div id="mobile-navigation" ref={menuRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label={t("nav.accountNavigationAria")}
          className="mobile-account-sheet border border-app bg-app p-4 text-app-text" onClick={event => event.stopPropagation()}>
          <div className="mb-4 flex items-center justify-between gap-3"><span className="truncate font-semibold">{user?.display_name}</span>
            <button type="button" className="touch-target inline-flex items-center justify-center" onClick={() => setOpen(false)} aria-label={t("nav.closeNavigation")}><X className="h-5 w-5" /></button>
          </div>
          <nav aria-label={t("nav.accountNavigationAria")} className="grid gap-2">
            <IntentNavLink to="/account" onClick={() => setOpen(false)} className="touch-target flex items-center gap-3 border border-app bg-app-panel-elevated px-4"><UserRound className="h-5 w-5" />{t("nav.account")}</IntentNavLink>
            {user && <IntentNavLink to={`/users/${user.user_id}`} onClick={() => setOpen(false)} className="touch-target flex items-center gap-3 border border-app bg-app-panel-elevated px-4"><Users className="h-5 w-5" />{t("nav.myProfile")}</IntentNavLink>}
            <WhatsNewButton />
          </nav>
          {!friend && <div className="mt-5"><NavigationDisclosure compact review /></div>}
          {!friend && <div className="mt-5"><NavigationDisclosure compact /></div>}
        </div>
      </div>}
    </header>
  );
}

function MobileTabLink({ item, active, location, remembered, iconOnly }: {
  item: NavItem;
  active: PrimaryTab | null;
  location: ReturnType<typeof useLocation>;
  remembered: ReturnType<typeof useTabMemory>;
  iconOnly: boolean;
}) {
  const { t } = useTranslation();
  const messagesAria = useMessagesUnreadAria();
  const { to, label, icon: Icon } = item;
  const tab = primaryTabFor(to), memory = remembered(tab);
  const rootActive = active === tab && location.pathname.replace(/\/$/, '') === to;
  const destination = active === tab ? (rootActive ? location.pathname + location.search : to) : memory?.url ?? to;
  return <IntentNavLink primaryActive={active === tab} to={destination} aria-current={active === tab ? 'page' : undefined}
    aria-label={tab === 'messages' ? messagesAria : t(label)}
    state={{ mobileTabRestore: active === tab ? 0 : memory?.scroll ?? 0 }}
    className={`mobile-tab ${active === tab ? 'mobile-tab-active' : ''}`}
    onClick={event => {
      if (rootActive && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) {
        event.preventDefault(); window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      }
    }}><span className="relative"><Icon className="h-5 w-5" />
      {tab === 'messages' && <MessagesUnreadBadge className="absolute -top-1.5 -right-2.5" />}</span><span className={iconOnly ? "sr-only" : undefined}>{t(label)}</span></IntentNavLink>;
}

function MobileTabBar({ policy, remembered }: { policy: ReturnType<typeof useMobileNavPolicy>; remembered: ReturnType<typeof useTabMemory> }) {
  const { t } = useTranslation();
  const location = useLocation();
  const bar = useRef<HTMLElement>(null);
  const active = primaryTabFor(location.pathname);
  const items = usePrimaryNav();
  const five = items.length === 5;
  useLayoutEffect(() => {
    const root = document.documentElement;
    if (policy !== 'visible' || !bar.current) { root.style.setProperty('--mobile-nav-offset', '0px'); return; }
    const update = () => {
      if (!bar.current) return;
      const rect = bar.current.getBoundingClientRect();
      root.style.setProperty('--mobile-nav-offset', `${window.innerHeight - rect.top + 8}px`);
    };
    update();
    const observer = new ResizeObserver(update); observer.observe(bar.current);
    window.addEventListener('resize', update);
    return () => { observer.disconnect(); window.removeEventListener('resize', update); root.style.setProperty('--mobile-nav-offset', '0px'); };
  }, [policy]);
  if (policy !== 'visible') return null;
  return <nav ref={bar} className={`mobile-tab-bar lg:hidden ${five ? "calendar-five-tabs" : ""}`} aria-label={t('nav.primaryNavigationAria')}>
    {items.map(item => <MobileTabLink key={item.to} item={item} active={active} location={location} remembered={remembered} iconOnly={five} />)}
  </nav>;
}

function Layout({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const { t } = useTranslation();
  const friend = !user?.is_admin;
  const policy = useMobileNavPolicy();
  const remembered = useTabMemory(user?.user_id);
  const primaryNavItems = usePrimaryNav();
  return (
    <div className="min-h-screen bg-app text-app-text">
      <a href="#main-content" className="skip-link">
        {t("nav.skipToContent")}
      </a>
      <div className="flex min-h-screen w-full">
        <aside className="hidden w-64 shrink-0 border-r border-app lg:block" aria-label={t("nav.workspaceSidebarAria")}>
          <div className="sticky top-0 flex h-dvh flex-col overflow-y-auto px-5 py-6 pt-safe">
            <div className="shrink-0 border-b border-app pb-5">
              <div className="text-xl font-semibold text-app-text">
                Dive Analyser
              </div>
            </div>

            <nav className="mt-6 space-y-1" aria-label={t("nav.primaryNavigationAria")}>
              {primaryNavItems.map((item) => (
                <AppNavLink key={item.to} {...item} emphasis />
              ))}
            </nav>

            {!friend && (
              <div className="mt-6">
                <NavigationDisclosure review />
              </div>
            )}

            {!friend && (
              <div className="mt-6">
                <NavigationDisclosure />
              </div>
            )}

            <div className="mt-auto shrink-0 border-t border-app pt-4">
              <div className="mb-3 grid gap-2"><WhatsNewButton /><NotificationsButton /></div>
              <IntentNavLink to="/account" aria-label={t("nav.account")} className={({ isActive }) => `flex min-h-11 w-full items-center gap-3 border px-3 py-2 text-sm hover:bg-app-panel-elevated ${isActive ? "border-app-accent bg-app-panel-elevated text-app-accent" : "border-app bg-app-panel text-app-text"}`}>
                {user && <MemberAvatar member={user} size={24} />}
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{user?.display_name ?? user?.email}</span>
                  <span className="block text-xs text-app-muted">{t("nav.account")}</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0" />
              </IntentNavLink>
            </div>

          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <MobileNavigation />

          <main id="main-content" tabIndex={-1} className="shell-main flex-1">
            <div className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
              <Breadcrumbs />
              {children}
            </div>
          </main>
          <MobileTabBar policy={policy} remembered={remembered} />
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

/** Keep regular divers out of admin review and operations pages. */
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

/** Feature off: /calendar behaves like any unknown route (Library). */
function CalendarGate() {
  const { user } = useAuth();
  // Keyed by account: switching accounts never shows the previous account's calendar state.
  return user?.features?.calendar === true ? <CalendarPage key={user.user_id} /> : <Navigate to="/dives" replace />;
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
      <Route path="/claim" element={<Suspense fallback={<p role="status">{t("common.loadingPage")}</p>}><Claim /></Suspense>} />
      {/* Invitation landing: public like /claim — the friend has no account yet. */}
      <Route path="/invite" element={<Suspense fallback={<p role="status">{t("common.loadingPage")}</p>}><Invite /></Suspense>} />
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
            <WhatsNewProvider><NotificationsProvider><MessagesUnreadProvider><Layout>
              <Suspense fallback={<p role="status" className="py-8 text-sm text-app-muted">{t("common.loadingPage")}</p>}>
                <Routes>
                  <Route path="/" element={<RootRedirect />} />
                  <Route path="/dashboard" element={<OwnerGuard><Dashboard /></OwnerGuard>} />
                  <Route path="/journey" element={<OwnerGuard><Journey /></OwnerGuard>} />
                  <Route path="/analytics" element={<OwnerGuard><Analytics /></OwnerGuard>} />
                <Route path="/dives" element={<Dives />} />
                <Route path="/evaluations" element={<Evaluations />} />
                <Route path="/series" element={<SeriesPage />} />
                <Route path="/series/:seriesId" element={<SeriesPage />} />
                <Route path="/calendar/*" element={<CalendarGate />} />
                <Route path="/dives/analysis/:diveCode" element={<DiveAnalysis />} />
                  <Route
                    path="/media/representatives"
                    element={<OwnerGuard><RepresentativeMedia /></OwnerGuard>}
                  />
                  <Route
                    path="/media/recall"
                    element={
                      <OwnerGuard>
                        <MediaRecall />
                      </OwnerGuard>
                    }
                  />
                  <Route path="/media/p5-canary" element={<OwnerGuard><P5Canary /></OwnerGuard>} />
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
                  <Route path="/messages" element={<Messages />} />
                  <Route path="/messages/:conversationId" element={<Messages />} />
                  <Route path="/community" element={<Community />} />
                  <Route path="/users/:userId" element={<MemberProfile />} />
                  <Route path="/sessions" element={<OwnerGuard><Sessions /></OwnerGuard>} />
                  <Route path="/notifications" element={<Notifications />} />
                  <Route path="/deposits" element={<Deposits />} />
                  <Route path="/deposits/:batchId" element={<Deposits />} />
                  <Route
                    path="/competitions"
                    element={<CompetitionsRedirect />}
                  />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </Layout></MessagesUnreadProvider></NotificationsProvider></WhatsNewProvider>
          </AuthGuard>
        }
      />
    </Routes>
  );
}

export default Router;
