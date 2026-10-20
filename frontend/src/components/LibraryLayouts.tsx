import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { appLocale } from "../utils/dateLocale";
import { format, parseISO } from "date-fns";
import DiveThumbnail from "./DiveThumbnail";
import { divePositionName } from "../utils/divePosition";
import {
  PERFORMANCE,
  attemptScore,
  performanceLabel,
  type Attempt,
} from "../utils/attemptPresentation";

export const ratingDot: Record<string, string> = {
  P: "bg-emerald-400",
  G: "bg-app-accent",
  M: "bg-amber-300",
  B: "bg-orange-400",
  F: "bg-red-400",
};
const ratingText: Record<string, string> = {
  P: "text-emerald-300",
  G: "text-app-accent",
  M: "text-amber-200",
  B: "text-orange-300",
  F: "text-red-300",
};

function average(attempts: Attempt[]) {
  return attempts.reduce((sum, a) => sum + attemptScore(a), 0) / attempts.length;
}

function RatingBar({ attempts }: { attempts: Attempt[] }) {
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-app-panel-elevated">
      {PERFORMANCE.map((p) => {
        const n = attempts.filter((a) => a.performance === p).length;
        return n ? (
          <div
            key={p}
            className={ratingDot[p]}
            style={{ width: `${(n / attempts.length) * 100}%` }}
            title={`${performanceLabel(p)}: ${n}`}
          />
        ) : null;
      })}
    </div>
  );
}

/* ---------- By code: one row per dive, attempt history as squares ---------- */

export function CodesLayout({
  attempts,
  onOpen,
  showDiver = false,
}: {
  attempts: Attempt[];
  onOpen: (a: Attempt) => void;
  showDiver?: boolean;
}) {
  const { t } = useTranslation();
  const codes = useMemo(() => {
    const map = new Map<string, Attempt[]>();
    attempts.forEach((a) => map.set(a.dive_code, [...(map.get(a.dive_code) || []), a]));
    return [...map.entries()];
  }, [attempts]);
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      {codes.map(([code, items]) => {
        const recent = items.slice(0, 30);
        const best = Math.max(...items.map(attemptScore));
        return (
          <section key={code} className="border border-app bg-app-panel p-3 sm:p-4">
            <div className="flex items-start gap-3">
              <button
                type="button"
                onClick={() => onOpen(items[0])}
                className="h-16 w-16 shrink-0 overflow-hidden border border-app sm:h-20 sm:w-20"
                aria-label={t('dives.openLatestAttempt', { code })}
              >
                <DiveThumbnail dive={items[0]} compact />
              </button>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-xl font-semibold text-app-text">{code}</span>
                  <span className="text-sm tabular-nums text-app-text">
                    <span className="text-app-muted">{t('dives.avg')} </span>
                    <strong>{average(items).toFixed(1)}</strong>
                    <span className="text-app-muted"> · {t('dives.best')} </span>
                    <strong>{best.toFixed(1)}</strong>
                  </span>
                </div>
                <div className="mt-0.5 truncate text-xs text-app-muted">
                  {divePositionName(items[0].position, code)} · {t('dives.attemptsCount', { count: items.length })} · {t('dives.last')}{" "}
                  {format(parseISO(items[0].dive_datetime), "d MMM", { locale: appLocale() })}
                </div>
                <div className="mt-2">
                  <RatingBar attempts={items} />
                </div>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1" aria-label={t('dives.recentAttemptsFor', { code })}>
              {recent.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => onOpen(a)}
                  data-attempt-id={a.id}
                  title={`${showDiver && a.person_name ? `${a.person_name} · ` : ""}${format(parseISO(a.dive_datetime), "d MMM HH:mm", { locale: appLocale() })} · ${attemptScore(a).toFixed(1)}`}
                  aria-label={[t('dives.openAttemptFrom', { code, date: format(parseISO(a.dive_datetime), "d MMM HH:mm", { locale: appLocale() }) }), showDiver && a.person_name].filter(Boolean).join(' · ')}
                  className={`flex h-6 min-h-0 min-w-6 items-center justify-center px-1 text-[10px] font-semibold tabular-nums text-black/80 hover:ring-2 hover:ring-white/60 ${ratingDot[a.performance]}`}
                >
                  {attemptScore(a).toFixed(0)}
                </button>
              ))}
              {items.length > recent.length && (
                <span className="flex h-6 items-center px-1 text-xs text-app-muted">
                  +{items.length - recent.length}
                </span>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
