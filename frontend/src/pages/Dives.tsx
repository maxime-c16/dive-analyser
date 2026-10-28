import {trainingSessions, formatDuration, type SharedTrainingSession} from "../services/sessionVideosApi";
import { useLocation, useNavigate, type NavigateOptions } from 'react-router-dom'
import React, { lazy, Suspense, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { appLocale } from "../utils/dateLocale";
import { HelpCircle, ChevronRight, Hash, LayoutGrid, List, RefreshCw, Search, SlidersHorizontal, TrendingUp } from "lucide-react";
import { format, parseISO } from "date-fns";
import { api } from "../services/api";
import { clearLibraryCache, libraryKey, loadLibraryCache, readLibraryCache } from "../services/libraryCache";
import { useAuth } from "../contexts/AuthContext";
import { usePreservedSearchParams } from "../hooks/usePreservedSearchParams";
import { divePositionCode } from "../utils/divePosition";
import {
  MODIFIERS,
  PERFORMANCE,
  modifiersFor,
  attemptScore,
  attemptSummary,
  performanceClass,
  performanceLabel,
  type Attempt,
} from "../utils/attemptPresentation";
import AddVideos from "../components/AddVideos";
import { MobileShellActions } from "../navigation/mobileShellActions";
import DiveThumbnail from "../components/DiveThumbnail";
import CodeCards, { type CodeSort } from "../components/code-analysis/CodeCards";
import ProgressHub from "../components/code-analysis/ProgressHub";
import { getCodeSummaries, peekCodeSummaries, type CodeSummaries } from "../services/codeSummariesApi";
import { LibraryCardGrid } from "../components/LibraryCards";
import { Link } from "react-router-dom";
import { Gift } from "lucide-react";
import { canAcceptDeposits, listPendingBatches } from "../services/depositsApi";
import PageLoading from "../components/PageLoading";

const ClipViewer = lazy(() => import("../components/clip-viewer/ClipViewer"));

type Dive = Attempt;
type Diver = { id: number; display_name: string; is_primary_user: boolean };
type Scope = "self" | "all";
type View = "grid" | "list" | "codes" | "progress";

function normalizedHeight(value: string) {
  return value.replace(/\s/g, "").toLowerCase();
}

function ScoreBadge({ dive }: { dive: Dive }) {
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex border px-2 py-1 text-xs font-medium ${performanceClass[dive.performance] || performanceClass.M}`}
    >
      {performanceLabel(dive.performance) || dive.performance}
    </span>
  );
}

type LibraryListEntry = { kind: "session"; session: SharedTrainingSession } | { kind: "dive"; dive: Dive };

function mergeSessionsAndDives(sessions: SharedTrainingSession[], dives: Dive[]): LibraryListEntry[] {
  const entries: LibraryListEntry[] = [
    ...sessions.map((session) => ({ kind: "session" as const, session, day: session.date })),
    ...dives.map((dive) => ({ kind: "dive" as const, dive, day: dive.dive_datetime.slice(0, 10) })),
  ];
  entries.sort((a, b) => b.day.localeCompare(a.day) || (a.kind === b.kind ? 0 : a.kind === "session" ? -1 : 1));
  return entries;
}

function SessionRow({ session }: { session: SharedTrainingSession }) {
  return (
    <Link
      to={`/sessions/shared/${session.session_id}`}
      className="grid w-full grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-app px-3 py-3 text-left hover:bg-app-panel-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent sm:grid-cols-[7rem_minmax(0,1fr)_7rem_8rem] sm:px-4"
      aria-label={`Séance · ${session.video_count} ${session.video_count === 1 ? "vidéo" : "vidéos"}`}
    >
      <div className="flex aspect-video items-center justify-center overflow-hidden border border-app">
        <span className="rounded-full bg-app-accent px-2 text-xs font-bold text-black">Séance</span>
      </div>
      <div className="min-w-0">
        <p className="truncate text-base font-semibold text-app-text">
          {session.video_count} {session.video_count === 1 ? "vidéo" : "vidéos"} · {formatDuration(session.total_duration)}
        </p>
        <p className="mt-1 text-xs text-app-muted">
          {format(parseISO(session.date), "d MMM yyyy", { locale: appLocale() })}
        </p>
      </div>
    </Link>
  );
}

function AttemptRow({ dive, onOpen, showDiver = false }: { dive: Dive; onOpen: () => void; showDiver?: boolean }) {  const { t } = useTranslation();
  const score = attemptScore(dive);
  return (
    <button
      type="button"
      onClick={onOpen}
      data-attempt-id={dive.id}
      className="grid w-full grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-app px-3 py-3 text-left hover:bg-app-panel-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent sm:grid-cols-[7rem_minmax(0,1fr)_7rem_8rem] sm:px-4"
      aria-label={[t("dives.openAttemptAria", { code: dive.dive_code, date: "" }), showDiver && dive.person_name].filter(Boolean).join(" · ")}
    >
      <div className="aspect-video overflow-hidden border border-app">
        <DiveThumbnail dive={dive} compact />
      </div>
      <div className="min-w-0">
        {showDiver && dive.person_name && (
          <p className="mb-1 truncate text-base font-semibold text-app-text" title={dive.person_name}>{dive.person_name}</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-base font-semibold text-app-text">
            {dive.dive_code}
          </span>
          <ScoreBadge dive={dive} />
        </div>
        <p className="mt-1 truncate text-xs text-app-muted">
          {!showDiver && dive.person_name ? `${dive.person_name} · ` : ""}{attemptSummary(dive)}
        </p>
        <p className="mt-1 text-xs text-app-muted sm:hidden">
          {format(parseISO(dive.dive_datetime), "d MMM yyyy · HH:mm", { locale: appLocale() })}
        </p>
      </div>
      <div className="hidden text-sm font-semibold text-app-text sm:block">
        {score.toFixed(1)} / 10
      </div>
      <div className="hidden text-right text-xs text-app-muted sm:block">
        {format(parseISO(dive.dive_datetime), "d MMM yyyy", { locale: appLocale() })}
        <br />
        {format(parseISO(dive.dive_datetime), "HH:mm", { locale: appLocale() })}
      </div>
      <ChevronRight className="h-5 w-5 text-app-muted sm:hidden" />
    </button>
  );
}

function parseSearch(value: string) {
  const tokens = value.toUpperCase().trim().split(/\s+/).filter(Boolean);
  const code = tokens.find((token) => /^\d{3,4}[ABCD]?$/.test(token)) || "";
  const height = tokens.find((token) => /^\d{1,2}(?:\.5)?M$/.test(token)) || "";
  const sync = tokens.includes("SYNC")
    ? true
    : tokens.includes("INDIVIDUAL")
      ? false
      : null;
  const modifiers = tokens.filter(
    (token): token is (typeof MODIFIERS)[number] =>
      (MODIFIERS as readonly string[]).includes(token),
  );
  const performance =
    tokens.find((token): token is (typeof PERFORMANCE)[number] =>
      (PERFORMANCE as readonly string[]).includes(token),
    ) || "";
  // Bare A/B/C/D tokens are also valid performance values. Position wording is
  // therefore intentionally natural-language only in library search.
  const positionToken = tokens.find((token) =>
    ["STRAIGHT", "PIKE", "TUCK", "FREE"].includes(token),
  );
  const position = positionToken ? divePositionCode(positionToken) || "" : "";
  const known = new Set([
    code,
    height,
    ...modifiers,
    performance,
    position,
    "STRAIGHT",
    "PIKE",
    "TUCK",
    "FREE",
    "SYNC",
    "INDIVIDUAL",
  ]);
  const text = tokens.filter((token) => !known.has(token)).join(" ");
  return { code, height, sync, modifiers, performance, position, text };
}

// Recreate local UI state when account/access bindings change; old attempts
// must not remain visible for a render while an effect resets their list.
export default function Dives() {
  const { user } = useAuth();
  return <DiveLibrary key={libraryKey(user) ?? 'anonymous'} />;
}

export function PendingBanner() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    listPendingBatches()
      .then((rows) => {
        if (live) setCount(rows.filter((row) => canAcceptDeposits(user, row.diver_id)).reduce((sum, row) => sum + (row.pending || 0), 0));
      })
      .catch(() => {
        if (live) setCount(0);
      });
    return () => {
      live = false;
    };
  }, [user]);
  if (!count) return null;
  return (
    <Link
      to="/deposits"
      className="mt-3 flex items-center gap-3 border border-app-accent bg-app-panel px-4 py-3"
    >
      <Gift className="h-5 w-5 shrink-0 text-app-accent" aria-hidden />
      <span className="text-sm font-medium text-app-text">
        {t("deposits.banner", { count })}
      </span>
      <span className="ml-auto text-sm font-semibold text-app-accent">{t("deposits.bannerCta")} →</span>
    </Link>
  );
}

function DiveLibrary() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = usePreservedSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [sharedSessions, setSharedSessions] = useState<SharedTrainingSession[]>([]);
  const [sessionsCursor, setSessionsCursor] = useState<number|null>(null);
  useEffect(()=>{let live=true; if(user?.features?.shared_sessions) trainingSessions().then(d=>{if(live){setSharedSessions(d.items);setSessionsCursor(d.next_cursor)}}).catch(()=>{}); return()=>{live=false}},[user?.user_id,user?.features?.shared_sessions]);
  const query = searchParams.get("q") || "";
  const deferredQuery = useDeferredValue(query);
  const scope = (searchParams.get("scope") || ((!user || user.is_admin) ? "self" : "all")) as Scope;
  const heightFilter = searchParams.get("height") || "";
  const contextFilter = searchParams.get("context") || "";
  const performanceFilter = searchParams.get("performance") || "";
  const modifiers = (searchParams.get("modifiers") || "")
    .split(",")
    .filter(Boolean);
  const view = (searchParams.get("view") || "grid") as View;
  const clipParam = searchParams.get("clip") || "";
  const clipRef = useRef(clipParam);
  clipRef.current = clipParam;
  const parsed = useMemo(() => parseSearch(deferredQuery), [deferredQuery]);
  const pageParams = {
    limit: 100, diver_scope: scope,
    height: heightFilter || parsed.height.toLowerCase(),
    performance: performanceFilter || parsed.performance,
    code_prefix: parsed.code, search_text: parsed.text, position_filter: parsed.position,
    ...(contextFilter ? { sync_filter: contextFilter === 'sync' } : parsed.sync !== null ? { sync_filter: parsed.sync } : {}),
    modifier_filter: [...new Set([...modifiers, ...parsed.modifiers])].join(','),
  };
  const pageParamsKey = JSON.stringify(pageParams);
  // Code cards and progress aggregate the whole filtered Library, not the loaded pages.
  const { limit: _limit, ...codeParams } = pageParams;
  const codeParamsKey = JSON.stringify(codeParams);
  const aggregated = view === "codes" || view === "progress";
  const accessKey = libraryKey(user);
  const [codeSummaries, setCodeSummaries] = useState<CodeSummaries | null>(() => peekCodeSummaries(codeParams, accessKey));
  const [codeSummaryError, setCodeSummaryError] = useState(false);
  const codeSort = (["recent", "volume", "progress"].includes(searchParams.get("sort") || "") ? searchParams.get("sort") : "recent") as CodeSort;

  const cacheKey = accessKey ? JSON.stringify([accessKey, "paged", pageParamsKey]) : null;
  const cached = useMemo(() => readLibraryCache(cacheKey), [cacheKey]);
  const [dives, setDives] = useState<Dive[]>(cached?.dives ?? []);
  const [divers, setDivers] = useState<Diver[]>(cached?.divers ?? []);
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [shown, setShown] = useState(48);
  const [nextCursor, setNextCursor] = useState<string | null>(cached?.nextCursor ?? null);
  const [loadingMore, setLoadingMore] = useState(false);
  const pageGeneration = useRef(0);
  const loadedAccessKey = useRef(accessKey);
  const hasLoadedLibrary = useRef(Boolean(cached));
  const [playbackRate, setPlaybackRate] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const scrollAnchorRef = useRef<number | null>(null);
  const viewerReturnAttemptRef = useRef<number | null>(null);

  const update = (
    patch: Record<string, string | null>,
    options?: NavigateOptions,
  ) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([key, value]) =>
      value ? next.set(key, value) : next.delete(key),
    );
    setSearchParams(next, { state: location.state, ...options, replace: options?.replace ?? true });
  };

  useEffect(() => {
    let active = true;
    pageGeneration.current++;
    setLoadingMore(false);
    const snapshot = readLibraryCache(cacheKey);
    const accountChanged = loadedAccessKey.current !== accessKey;
    loadedAccessKey.current = accessKey;
    if (accountChanged) hasLoadedLibrary.current = false;
    // Keep the same-account matching cards mounted while filters refresh;
    // unmounting a card between pointer-down/up drops its open action.
    if (snapshot || accountChanged) {
      setDives(snapshot?.dives ?? []);
      setDivers(snapshot?.divers ?? []);
    }
    setNextCursor(snapshot?.nextCursor ?? null);
    // An empty result is still a loaded library. Keep its filter-reset action
    // mounted during refresh too, so a pending query cannot swallow the click.
    setLoading(!snapshot && !hasLoadedLibrary.current);
    setError(null);
    loadLibraryCache(cacheKey, async () => {
      const [diveResponse, diverResponse] = await Promise.all([
        api.get("/api/v1/dives/library", { params: pageParams }),
        api.get("/api/v1/divers"),
      ]);
      return { dives: Array.isArray(diveResponse.data) ? diveResponse.data : diveResponse.data.items,
        nextCursor: diveResponse.data.next_cursor ?? null, divers: diverResponse.data };
    })
      .then(({ dives, divers, nextCursor }) => {
        if (active) {
          hasLoadedLibrary.current = true;
          // A direct-link clip resolved while this refresh was in flight must survive it.
          setDives(current => {
            const pinned = current.find(dive => String(dive.id) === clipRef.current && !dives.some(item => item.id === dive.id));
            return pinned ? [...dives, pinned] : dives;
          });
          setDivers(divers);
          setNextCursor(nextCursor ?? null);
          setError(null);
        }
      })
      .catch(() => {
        if (active) setError(snapshot ? t("dives.errorSaved") : t("dives.errorLoad"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadKey, cacheKey, pageParamsKey]);

  useEffect(() => {
    if (!aggregated) return;
    let live = true;
    setCodeSummaries(peekCodeSummaries(codeParams, accessKey));
    setCodeSummaryError(false);
    getCodeSummaries(codeParams, accessKey)
      .then((data) => { if (live) setCodeSummaries(data); })
      .catch(() => { if (live) setCodeSummaryError(true); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aggregated, codeParamsKey, reloadKey, accessKey]);

  const loadMore = async () => {
    if (loadingMore || !nextCursor) return;
    const epoch = pageGeneration.current;
    setLoadingMore(true);
    try {
      const response = await api.get('/api/v1/dives/library', { params: { ...pageParams, cursor: nextCursor } });
      if (epoch !== pageGeneration.current) return;
      const items: Dive[] = response.data.items;
      setDives(current => [...current, ...items.filter(item => !current.some(dive => dive.id === item.id))]
        .sort((a, b) => Date.parse(b.dive_datetime) - Date.parse(a.dive_datetime) || b.id - a.id));
      setNextCursor(response.data.next_cursor);
      setShown(count => count + 100);
      setError(null);
    } catch {
      if (epoch === pageGeneration.current) setError(t('dives.errorLoad'));
    } finally {
      if (epoch === pageGeneration.current) setLoadingMore(false);
    }
  };

  // Direct links can target an older page. Resolve that one authorized dive,
  // then let the existing filters decide whether the viewer may show it.
  const [resolvingClip, setResolvingClip] = useState(false);
  const [resolvedClip, setResolvedClip] = useState('');
  useEffect(() => {
    if (!clipParam || loading || dives.some(dive => String(dive.id) === clipParam)) return;
    if (!/^[1-9][0-9]*$/.test(clipParam)) { setResolvedClip(clipParam); return; }
    let live = true;
    setResolvingClip(true);
    setResolvedClip('');
    api.get(`/api/v1/dives/${clipParam}`).then(response => {
      if (live && response.data?.id) setDives(current => current.some(d => d.id === response.data.id) ? current : [...current, response.data]);
    }).catch(() => {}).finally(() => { if (live) { setResolvingClip(false); setResolvedClip(clipParam); } });
    return () => { live = false; };
  }, [clipParam, loading, cacheKey]);

  const primaryId = divers.find((diver) => diver.is_primary_user)?.id;
  const filtered = useMemo(
    () =>
      dives.filter((dive) => {
        if (scope === "self") {
          if (user && !user.divers.some(binding => binding.access_kind === 'OWNER' && binding.diver_id === dive.diver_id)) return false;
          if (!user && primaryId && dive.diver_id !== primaryId) return false;
        }
        if (
          heightFilter &&
          normalizedHeight(dive.height) !== normalizedHeight(heightFilter)
        )
          return false;
        if (contextFilter === "sync" && !dive.is_sync) return false;
        if (contextFilter === "individual" && dive.is_sync) return false;
        if (performanceFilter && dive.performance !== performanceFilter)
          return false;
        const diveModifiers = modifiersFor(dive);
        if (
          modifiers.some(
            (modifier) =>
              !diveModifiers.includes(modifier as (typeof MODIFIERS)[number]),
          )
        )
          return false;
        if (
          parsed.code &&
          !dive.dive_code.toUpperCase().startsWith(parsed.code)
        )
          return false;
        if (
          parsed.height &&
          normalizedHeight(dive.height) !== normalizedHeight(parsed.height)
        )
          return false;
        if (parsed.sync !== null && dive.is_sync !== parsed.sync) return false;
        if (parsed.performance && dive.performance !== parsed.performance)
          return false;
        if (
          parsed.position &&
          divePositionCode(dive.position, dive.dive_code) !== parsed.position
        )
          return false;
        if (
          parsed.modifiers.some((modifier) => !diveModifiers.includes(modifier))
        )
          return false;
        if (
          parsed.text &&
          !`${dive.dive_code} ${dive.raw_caption || ""} ${dive.notes || ""}`
            .toUpperCase()
            .includes(parsed.text)
        )
          return false;
        return true;
      }),
    [
      dives,
      scope,
      primaryId,
      user,
      heightFilter,
      contextFilter,
      performanceFilter,
      modifiers,
      parsed,
    ],
  );
  useEffect(() => {
    setShown(48);
  }, [
    deferredQuery,
    scope,
    heightFilter,
    contextFilter,
    performanceFilter,
    modifiers.join(","),
  ]);

  // The viewer is derived from the URL: `clip` holds the selected attempt id.
  // Selection is only valid inside the current filtered result set, so a
  // filter change that excludes the clip closes the viewer automatically.
  const selected =
    clipParam && filtered.some((dive) => String(dive.id) === clipParam)
      ? filtered.find((dive) => String(dive.id) === clipParam) || null
      : null;

  // Extend the viewer's navigation window before it reaches a page boundary.
  useEffect(() => {
    if (selected && nextCursor && !loadingMore && filtered.findIndex(dive => dive.id === selected.id) >= filtered.length - 3) void loadMore();
  }, [selected?.id, nextCursor, filtered.length, loadingMore]);

  // Stale/invalid clip identity (bad id, removed attempt, direct stale link):
  // clear it non-destructively so the Library stays usable.
  useEffect(() => {
    if (!clipParam || loading || error || resolvingClip ||
        (!dives.some(dive => String(dive.id) === clipParam) && resolvedClip !== clipParam)) return;
    if (!filtered.some((dive) => String(dive.id) === clipParam)) {
      update({ clip: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipParam, loading, error, filtered, resolvingClip, resolvedClip]);

  // Deterministic Library scroll restoration for the review loop: the anchor
  // is captured when a clip is opened and restored when the viewer closes
  // (browser Back or the close control).
  useEffect(() => {
    if (selected) return;
    if (scrollAnchorRef.current !== null) {
      const anchor = scrollAnchorRef.current;
      scrollAnchorRef.current = null;
      requestAnimationFrame(() => window.scrollTo(0, anchor));
    }
  }, [selected]);

  // Focus lifecycle: return focus to the originating Library card when the
  // viewer closes, so keyboard users are not dropped at the document body.
  // If the originating card no longer exists (filters changed, attempt
  // removed), fall back to the Library search input — never scroll the
  // page unexpectedly.
  useEffect(() => {
    if (selected) return;
    const attemptId = viewerReturnAttemptRef.current;
    if (attemptId === null) return;
    viewerReturnAttemptRef.current = null;
    requestAnimationFrame(() => {
      // Grid mode renders both desktop cards and mobile tiles; pick the
      // one that is actually displayed.
      const matches = [
        ...document.querySelectorAll<HTMLElement>(
          `[data-attempt-id="${attemptId}"]`,
        ),
      ];
      const card =
        matches.find((element) => element.getClientRects().length > 0) ||
        matches[0];
      if (card) {
        card.focus({ preventScroll: true });
        return;
      }
      document
        .querySelector<HTMLInputElement>('input[data-dives-search]')
        ?.focus({ preventScroll: true });
    });
  }, [selected]);

  const openClip = (dive: Dive) => {
    if (scrollAnchorRef.current === null) {
      scrollAnchorRef.current = window.scrollY;
    }
    viewerReturnAttemptRef.current = dive.id;
    // Only local opens create a known Library entry to return to. Links from
    // profiles/messages and deep links keep their own history semantics.
    update({ clip: String(dive.id) }, { replace: false, state: {
      ...location.state,
      libraryViewerOrigin: location.pathname + (searchParams.size ? `?${searchParams}` : ''),
    } });
  };
  const openClipId = (id: number) => {
    const known = dives.find((dive) => dive.id === id);
    if (known) { openClip(known); return; }
    if (scrollAnchorRef.current === null) scrollAnchorRef.current = window.scrollY;
    viewerReturnAttemptRef.current = id;
    update({ clip: String(id) }, { replace: false, state: {
      ...location.state,
      libraryViewerOrigin: location.pathname + (searchParams.size ? `?${searchParams}` : ''),
    } });
  };
  const moveToClip = (dive: Dive) => {
    update({ clip: String(dive.id) });
  };
  const closeViewer = () => {
    const clean = new URLSearchParams(searchParams);
    clean.delete('clip');
    const libraryUrl = location.pathname + (clean.size ? `?${clean}` : '');
    if (location.state?.libraryViewerOrigin === libraryUrl) navigate(-1);
    else update({ clip: null }, { state: { ...location.state, libraryViewerOrigin: undefined } });
  };

  const visible = filtered.slice(0, shown);
  const heights = useMemo(
    () =>
      [...new Set(dives.map((dive) => dive.height))].sort(
        (a, b) => Number(a) - Number(b),
      ),
    [dives],
  );
  const activeFilters = [
    heightFilter,
    contextFilter,
    performanceFilter,
    ...modifiers,
    deferredQuery,
  ].filter(Boolean).length;
  const reset = () =>
    update({
      q: null,
      height: null,
      context: null,
      performance: null,
      modifiers: null,
    });

  return (
    <div className="mx-auto max-w-[1440px] pb-10">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-3 border-b border-app pb-3 sm:flex-nowrap sm:items-end sm:gap-4 sm:pb-5">
        <h1 className="min-w-0 flex-1 text-3xl font-semibold tracking-tight text-app-text sm:text-4xl">
          {t("nav.dives")}
        </h1>
        <MobileShellActions />
        <div className="basis-full sm:hidden" aria-hidden />
        <div className="flex h-11 flex-1 gap-1 border border-app bg-app-panel p-0.5 sm:hidden">
          {(
            [
              ["grid", t("dives.viewClips")],
              ["codes", t("dives.viewByCode")],
              ["progress", t("codeAnalysis.progressTab")],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => update({ view: value === "grid" ? null : value })}
              aria-pressed={value === "grid" ? !aggregated : view === value}
              className={`min-h-0 flex-1 border px-3 text-sm ${(value === "grid" ? !aggregated : view === value) ? "border-app-accent bg-app-panel-elevated text-app-accent" : "border-transparent text-app-muted"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-label={t("dives.refresh")}
          title={t("dives.refresh")}
          disabled={loading}
          onClick={() => { clearLibraryCache(); setReloadKey(key => key + 1); }}
          className="touch-target inline-flex shrink-0 items-center justify-center border border-app bg-app-panel text-app-muted hover:text-app-text disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
        <div className="basis-full sm:hidden" aria-hidden />
        <AddVideos onAdded={() => { clearLibraryCache(); setReloadKey(key => key + 1); }} />
      </header>
      <PendingBanner />
      <section className="mt-4 space-y-2" aria-label={t("dives.filtersAria")}>
        <div className="flex flex-wrap items-center gap-2">
          <div className={`${filtersOpen ? "flex" : "hidden"} order-last h-11 w-full gap-1 border border-app bg-app-panel p-1 sm:order-none sm:flex sm:w-auto sm:shrink-0`}>
            {(
              [
                ["self", t("dives.myDives")],
                ["all", t("dives.community")],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => update({ scope: value })}
                aria-pressed={scope === value}
                className={`min-h-0 flex-1 whitespace-nowrap border px-3 text-sm ${scope === value ? "border-app-accent bg-app-panel-elevated text-app-accent" : "border-transparent text-app-muted"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="relative block min-w-0 flex-1 sm:min-w-[14rem]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-app-muted" />
            <input
              value={query}
              onChange={(event) => update({ q: event.target.value })}
              className="app-input h-11 w-full !pl-10 pr-4 text-sm"
              placeholder={t("dives.searchPlaceholder")}
              aria-label={t("dives.searchAria")}
              data-dives-search
            />
          </label>
          <button
            type="button"
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            className={`touch-target relative inline-flex items-center justify-center border sm:hidden ${filtersOpen ? "border-app-accent text-app-accent" : "border-app text-app-muted"}`}
            aria-label={t("dives.filters")}
          >
            <SlidersHorizontal className="h-4 w-4" />
            {activeFilters - (deferredQuery ? 1 : 0) + (scope !== "self" ? 1 : 0) > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-app-accent px-1 text-[10px] font-semibold text-black">
                {activeFilters - (deferredQuery ? 1 : 0) + (scope !== "self" ? 1 : 0)}
              </span>
            )}
          </button>
          <div className="hidden shrink-0 items-center gap-1 sm:flex">
            <button
              type="button"
              onClick={() => update({ view: "grid" })}
              className={`touch-target inline-flex items-center justify-center border p-0 ${view === "grid" ? "border-app-accent text-app-accent" : "border-app text-app-muted"}`}
              aria-label={t("dives.gridView")}
              title={t("dives.gridView")}
              aria-pressed={view === "grid"}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => update({ view: "list" })}
              className={`touch-target inline-flex items-center justify-center border p-0 ${view === "list" ? "border-app-accent text-app-accent" : "border-app text-app-muted"}`}
              aria-label={t("dives.listView")}
              title={t("dives.listView")}
              aria-pressed={view === "list"}
            >
              <List className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => update({ view: "codes" })}
              className={`touch-target inline-flex items-center justify-center border p-0 ${view === "codes" ? "border-app-accent text-app-accent" : "border-app text-app-muted"}`}
              aria-label={t("dives.codeView")}
              title={t("dives.codeView")}
              aria-pressed={view === "codes"}
            >
              <Hash className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => update({ view: "progress" })}
              className={`touch-target inline-flex items-center justify-center border p-0 ${view === "progress" ? "border-app-accent text-app-accent" : "border-app text-app-muted"}`}
              aria-label={t("codeAnalysis.progressTab")}
              title={t("codeAnalysis.progressTab")}
              aria-pressed={view === "progress"}
            >
              <TrendingUp className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className={`${filtersOpen ? "grid" : "hidden"} grid-cols-2 items-center gap-2 sm:flex sm:flex-wrap`}>
          <select
            aria-label={t("dives.heightFilter")}
            value={heightFilter}
            onChange={(event) => update({ height: event.target.value })}
            className="app-input h-11 w-full py-0 text-sm sm:w-auto"
          >
            <option value="">{t("dives.allHeights")}</option>
            {heights.map((height) => (
              <option key={height} value={height}>
                {height}
              </option>
            ))}
          </select>
          <select
            aria-label={t("dives.contextFilter")}
            value={contextFilter}
            onChange={(event) => update({ context: event.target.value })}
            className="app-input h-11 w-full py-0 text-sm sm:w-auto"
          >
            <option value="">{t("dives.contextAll")}</option>
            <option value="individual">{t("dives.contextIndividual")}</option>
            <option value="sync">{t("dives.contextSync")}</option>
          </select>
          <select
            aria-label={t("dives.ratingFilter")}
            value={performanceFilter}
            onChange={(event) => update({ performance: event.target.value })}
            className="app-input h-11 w-full py-0 text-sm sm:w-auto"
          >
            <option value="">{t("dives.allRatings")}</option>
            {PERFORMANCE.map((item) => (
              <option key={item} value={item}>
                {item} · {performanceLabel(item)}
              </option>
            ))}
          </select>
          <div
            role="group"
            aria-label={t("dives.modifiers")}
            className="flex h-11 gap-1 border border-app bg-app-panel p-1"
          >
            {MODIFIERS.map((modifier) => (
              <button
                key={modifier}
                type="button"
                onClick={() =>
                  update({
                    modifiers: modifiers.includes(modifier)
                      ? modifiers
                          .filter((item) => item !== modifier)
                          .join(",") || null
                      : [...modifiers, modifier].join(","),
                  })
                }
                aria-pressed={modifiers.includes(modifier)}
                title={t(`dives.modifierDescriptions.${modifier}`)}
                className={`min-h-0 min-w-10 flex-1 border px-2 text-xs ${modifiers.includes(modifier) ? "border-app-accent bg-app-panel-elevated text-app-accent" : "border-transparent text-app-muted"}`}
              >
                {modifier}
              </button>
            ))}
          </div>
          <details className="relative col-span-2 justify-self-start sm:col-span-1">
            <summary aria-label={t("dives.modifierHelp")} title={t("dives.modifierHelp")} className="touch-target flex cursor-pointer list-none items-center justify-center border border-app bg-app-panel text-app-muted hover:text-app-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-app-accent [&::-webkit-details-marker]:hidden">
              <HelpCircle className="h-4 w-4" aria-hidden="true" />
            </summary>
            <dl className="absolute left-0 top-full z-20 mt-2 w-80 max-w-[calc(100vw-2rem)] space-y-3 border border-app bg-app-panel-elevated p-4 text-sm shadow-lg sm:left-auto sm:right-0">
              {MODIFIERS.map(modifier => <div key={modifier}>
                <dt className="font-semibold text-app-text">{modifier} · {t(`dives.modifierNames.${modifier}`)}</dt>
                <dd className="mt-1 text-app-muted">{t(`dives.modifierDescriptions.${modifier}`)}</dd>
              </div>)}
            </dl>
          </details>
          <button
            type="button"
            onClick={reset}
            disabled={!activeFilters}
            className="touch-target col-span-2 inline-flex items-center justify-center gap-2 px-2 text-sm text-app-muted hover:text-app-text disabled:hidden"
          >
            <SlidersHorizontal className="h-4 w-4" />
            {t("dives.resetFilters")}
          </button>
        </div>
      </section>
      {loading && <PageLoading />}
      {error && (
        <div
          className="mt-6 border border-red-300/40 bg-red-300/10 p-4 text-sm text-red-100"
          role="alert"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={() => { clearLibraryCache(); setReloadKey((key) => key + 1); }}
            className="touch-target mt-3 inline-flex items-center gap-2 border border-red-300/50 bg-black/30 px-3 text-sm text-red-50"
          >
            {t("common.retry")}
          </button>
        </div>
      )}
      {!loading && (!error || dives.length > 0) && (
        <section className="mt-3 border-t border-app pt-3 sm:mt-5 sm:pt-5">
          {filtered.length === 0 && !sharedSessions.length ? (
            <div className="border-b border-app py-16 text-center" role="status">
              <p className="font-medium text-app-text">
                {t("dives.noMatches")}
              </p>
              {(activeFilters > 0) && (
                <button
                  type="button"
                  onClick={reset}
                  className="touch-target mt-4 inline-flex items-center gap-2 border border-app-accent bg-app-panel px-4 text-sm text-app-accent"
                >
                  <SlidersHorizontal className="h-4 w-4" />
                  {t("dives.clearFilters")}
                </button>
              )}
            </div>
          ) : (
            aggregated ? (
              codeSummaries ? (
                view === "codes" ? (
                  <CodeCards codes={codeSummaries.codes} sort={codeSort} onSort={(sort) => update({ sort: sort === "recent" ? null : sort })} onOpenClip={openClipId} />
                ) : (
                  <ProgressHub data={codeSummaries} />
                )
              ) : codeSummaryError ? (
                <div className="border border-red-300/40 bg-red-300/10 p-4 text-sm text-red-100" role="alert">{t("dives.errorLoad")}</div>
              ) : (
                <PageLoading />
              )
            ) : (
              <>
                {view === "grid" ? (
                  <LibraryCardGrid sessions={sharedSessions} attempts={visible} onOpen={openClip} showDiver={scope === "all"} />
                ) : (
                  <div className="border border-app bg-app-panel">
                    {mergeSessionsAndDives(sharedSessions, visible).map((entry) => (
                      entry.kind === "session" ? (
                        <SessionRow key={`session-${entry.session.session_id}`} session={entry.session} />
                      ) : (
                        <AttemptRow
                          key={entry.dive.id}
                          dive={entry.dive}
                          showDiver={scope === "all"}
                          onOpen={() => openClip(entry.dive)}
                        />
                      )
                    ))}
                  </div>
                )}
                {shown < filtered.length && (
                  <div className="mt-5 text-center">
                    <button
                      type="button"
                      onClick={() => setShown((count) => count + 48)}
                      className="touch-target border border-app bg-app-panel px-5 text-sm text-app-text"
                    >
                      {t("dives.showMoreAttempts")}
                    </button>
                  </div>
                )}
              </>
            )
          )}
        </section>
      )}
      {sessionsCursor && <button className="touch-target" onClick={async()=>{const d=await trainingSessions(sessionsCursor);setSharedSessions(s=>[...s,...d.items]);setSessionsCursor(d.next_cursor)}}>Plus de séances</button>}
      {!loading && nextCursor && !aggregated && (
        <div className="mt-5 text-center">
          <button type="button" disabled={loadingMore} onClick={() => void loadMore()}
            className="touch-target border border-app bg-app-panel px-5 text-sm text-app-text disabled:opacity-50">
            {loadingMore ? t('common.loading') : t('dives.loadMore')}
          </button>
        </div>
      )}
      {selected && (
        <Suspense fallback={<PageLoading message={t("dives.openingVideo")} />}>
          <ClipViewer
          attempt={selected}
          attempts={filtered}
          onClose={closeViewer}
          onMove={moveToClip}
          playbackRate={playbackRate}
          onPlaybackRateChange={setPlaybackRate}
          onUpdate={updated => { clearLibraryCache(); setDives(current => current.map(dive => dive.id === updated.id ? updated as Dive : dive)); }}
          onDelete={() => { clearLibraryCache(); setDives(current => current.filter(dive => dive.id !== selected.id)); closeViewer(); }}
          />
        </Suspense>
      )}
    </div>
  );
}
