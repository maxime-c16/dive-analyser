import { useLocation, useNavigate, type NavigateOptions } from 'react-router-dom'
import React, { lazy, Suspense, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { appLocale } from "../utils/dateLocale";
import { ChevronRight, Hash, LayoutGrid, List, RefreshCw, Search, SlidersHorizontal } from "lucide-react";
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
import DiveThumbnail from "../components/DiveThumbnail";
import { CodesLayout, WallLayout } from "../components/LibraryLayouts";
import { Link } from "react-router-dom";
import { Gift } from "lucide-react";
import { listPendingBatches } from "../services/depositsApi";

const ClipViewer = lazy(() => import("../components/clip-viewer/ClipViewer"));

type Dive = Attempt;
type Diver = { id: number; display_name: string; is_primary_user: boolean };
type Scope = "self" | "all";
type View = "grid" | "list" | "codes";

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

function AttemptCard({
  dive,
  onOpen,
  compact = false,
}: {
  dive: Dive;
  onOpen: () => void;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const score = attemptScore(dive);
  return (
    <button
      type="button"
      onClick={onOpen}
      data-attempt-id={dive.id}
      className={`group min-w-0 overflow-hidden border border-app bg-app-panel text-left transition-colors hover:border-app-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-app-accent ${compact ? "w-[13.5rem] shrink-0 sm:w-[15rem]" : ""}`}
      aria-label={t("dives.openAttemptAria", { code: dive.dive_code, date: format(parseISO(dive.dive_datetime), "d MMM yyyy", { locale: appLocale() }) })}
    >
      <DiveThumbnail dive={dive} />
      <div className="p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="font-mono text-lg font-semibold tracking-tight text-app-text">
              {dive.dive_code}
            </div>
            <p className="mt-1 truncate text-xs text-app-muted">
              {format(parseISO(dive.dive_datetime), "d MMM yyyy · HH:mm", { locale: appLocale() })}
            </p>
          </div>
          <ScoreBadge dive={dive} />
        </div>
        <p className="mt-3 truncate text-xs text-app-muted">
          {dive.person_name ? `${dive.person_name} · ` : ""}{attemptSummary(dive)}
        </p>
        {!compact && (
          <div className="mt-3 flex items-center justify-between border-t border-app pt-3 text-xs">
            <span className="text-app-muted">{t("dives.score")}</span>
            <span className="font-semibold text-app-text">
              {score.toFixed(1)} / 10
            </span>
          </div>
        )}
      </div>
    </button>
  );
}

function AttemptRow({ dive, onOpen }: { dive: Dive; onOpen: () => void }) {
  const { t } = useTranslation();
  const score = attemptScore(dive);
  return (
    <button
      type="button"
      onClick={onOpen}
      data-attempt-id={dive.id}
      className="grid w-full grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-app px-3 py-3 text-left hover:bg-app-panel-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent sm:grid-cols-[7rem_minmax(0,1fr)_7rem_8rem] sm:px-4"
      aria-label={t("dives.openAttemptAria", { code: dive.dive_code, date: "" })}
    >
      <div className="aspect-video overflow-hidden border border-app">
        <DiveThumbnail dive={dive} compact />
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-base font-semibold text-app-text">
            {dive.dive_code}
          </span>
          <ScoreBadge dive={dive} />
        </div>
        <p className="mt-1 truncate text-xs text-app-muted">
          {dive.person_name ? `${dive.person_name} · ` : ""}{attemptSummary(dive)}
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
  const height = tokens.find((token) => /^\d{1,2}M$/.test(token)) || "";
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

function PendingBanner() {
  const { t } = useTranslation();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    listPendingBatches()
      .then((rows) => {
        if (live) setCount(rows.reduce((sum, row) => sum + (row.pending || 0), 0));
      })
      .catch(() => {
        if (live) setCount(0);
      });
    return () => {
      live = false;
    };
  }, []);
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
  const cacheKey = libraryKey(user);
  const cached = useMemo(() => readLibraryCache(cacheKey), [cacheKey]);
  const [dives, setDives] = useState<Dive[]>(cached?.dives ?? []);
  const [divers, setDivers] = useState<Diver[]>(cached?.divers ?? []);
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [shown, setShown] = useState(48);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const scrollAnchorRef = useRef<number | null>(null);
  const viewerReturnAttemptRef = useRef<number | null>(null);
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
    const snapshot = readLibraryCache(cacheKey);
    setDives(snapshot?.dives ?? []);
    setDivers(snapshot?.divers ?? []);
    setLoading(!snapshot);
    setError(null);
    loadLibraryCache(cacheKey, async () => {
      const [diveResponse, diverResponse] = await Promise.all([
        api.get("/api/v1/dives", {
          params: { limit: 5000, exclude_lineup: true, diver_scope: "all" },
        }),
        api.get("/api/v1/divers"),
      ]);
      return { dives: diveResponse.data, divers: diverResponse.data };
    })
      .then(({ dives, divers }) => {
        if (active) {
          setDives(dives);
          setDivers(divers);
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
  }, [reloadKey, cacheKey]);

  const primaryId = divers.find((diver) => diver.is_primary_user)?.id;
  const parsed = useMemo(() => parseSearch(deferredQuery), [deferredQuery]);
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

  // Stale/invalid clip identity (bad id, removed attempt, direct stale link):
  // clear it non-destructively so the Library stays usable.
  useEffect(() => {
    if (!clipParam || loading || error) return;
    if (!filtered.some((dive) => String(dive.id) === clipParam)) {
      update({ clip: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipParam, loading, error, filtered]);

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
  const codeCount = new Set(filtered.map((dive) => dive.dive_code)).size;
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
      scope: "self",
      view: null,
    });

  return (
    <div className="mx-auto max-w-[1440px] pb-10">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-app pb-3 sm:flex-nowrap sm:pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-app-text sm:text-4xl">
            {t("nav.dives")}
          </h1>
          <p className="mt-0.5 text-xs text-app-muted sm:hidden">
            <strong className="text-app-text">{filtered.length}</strong> {t("dives.attempts")} ·{" "}
            <strong className="text-app-text">{codeCount}</strong> {t("dives.codes")}
          </p>
        </div>
        <button
          type="button"
          aria-label={t("dives.refresh")}
          title={t("dives.refresh")}
          disabled={loading}
          onClick={() => { clearLibraryCache(); setReloadKey(key => key + 1); }}
          className="touch-target ml-auto inline-flex shrink-0 items-center justify-center border border-app bg-app-panel text-app-muted hover:text-app-text disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
        <div className="flex h-9 gap-1 border border-app bg-app-panel p-0.5 sm:hidden">
          {(
            [
              ["grid", t("dives.viewClips")],
              ["codes", t("dives.viewByCode")],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => update({ view: value === "grid" ? null : value })}
              aria-pressed={(view === "codes") === (value === "codes")}
              className={`min-h-0 border px-3 text-xs ${(view === "codes") === (value === "codes") ? "border-app-accent bg-app-panel-elevated text-app-accent" : "border-transparent text-app-muted"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="hidden gap-2 text-sm sm:flex">
          <div className="border border-app bg-app-panel px-3 py-2">
            <span className="text-app-muted">{t("dives.attempts")} </span>
            <strong className="ml-1 text-app-text">{filtered.length}</strong>
          </div>
          <div className="border border-app bg-app-panel px-3 py-2">
            <span className="text-app-muted">{t("dives.codes")} </span>
            <strong className="ml-1 text-app-text">{codeCount}</strong>
          </div>
        </div>
      </header>
      <PendingBanner />
      <div className="mt-3"><AddVideos onAdded={() => { clearLibraryCache(); setReloadKey(key => key + 1); }} /></div>
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
                className={`min-h-0 flex-1 border px-3 text-sm ${scope === value ? "border-app-accent bg-app-panel-elevated text-app-accent" : "border-transparent text-app-muted"}`}
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
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => update({ view: "list" })}
              className={`touch-target inline-flex items-center justify-center border p-0 ${view === "list" ? "border-app-accent text-app-accent" : "border-app text-app-muted"}`}
              aria-label={t("dives.listView")}
            >
              <List className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => update({ view: "codes" })}
              className={`touch-target inline-flex items-center justify-center border p-0 ${view === "codes" ? "border-app-accent text-app-accent" : "border-app text-app-muted"}`}
              aria-label={t("dives.codeView")}
            >
              <Hash className="h-4 w-4" />
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
                className={`min-h-0 min-w-10 flex-1 border px-2 text-xs ${modifiers.includes(modifier) ? "border-app-accent bg-app-panel-elevated text-app-accent" : "border-transparent text-app-muted"}`}
              >
                {modifier}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={reset}
            disabled={!activeFilters && scope === "self"}
            className="touch-target col-span-2 inline-flex items-center justify-center gap-2 px-2 text-sm text-app-muted hover:text-app-text disabled:hidden disabled:opacity-35 sm:disabled:inline-flex"
          >
            <SlidersHorizontal className="h-4 w-4" />
            {t("common.reset")}
          </button>
        </div>
      </section>
      {loading && (
        <div
          className="border-y border-app py-20 text-center text-sm text-app-muted"
          role="status"
        >
          {t("common.loading")}
        </div>
      )}
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
          {filtered.length === 0 ? (
            <div className="border-b border-app py-16 text-center" role="status">
              <p className="font-medium text-app-text">
                {t("dives.noMatches")}
              </p>
              {(activeFilters > 0 || scope !== "self") && (
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
            view === "codes" ? (
              <CodesLayout attempts={filtered} onOpen={openClip} />
            ) : (
              <>
                {view === "grid" ? (
                  <>
                    <div className="hidden gap-3 sm:grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                      {visible.map((dive) => (
                        <AttemptCard
                          key={dive.id}
                          dive={dive}
                          onOpen={() => openClip(dive)}
                        />
                      ))}
                    </div>
                    <div className="sm:hidden">
                      <WallLayout attempts={visible} onOpen={openClip} />
                    </div>
                  </>
                ) : (
                  <div className="border border-app bg-app-panel">
                    {visible.map((dive) => (
                      <AttemptRow
                        key={dive.id}
                        dive={dive}
                        onOpen={() => openClip(dive)}
                      />
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
      {selected && (
        <Suspense fallback={<p role="status" className="py-4 text-app-muted">{t("dives.openingVideo")}</p>}>
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
