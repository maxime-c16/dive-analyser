import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { format, parseISO } from "date-fns";
import { appLocale } from "../utils/dateLocale";
import DiveThumbnail from "./DiveThumbnail";
import { diveCodeName } from "../i18n/diveNames";
import { attemptScore, modifiersFor, type Attempt } from "../utils/attemptPresentation";

/** Height, context and modifiers; the springboard/platform word is implied by the height. */
function attemptFacts(attempt: Attempt) {
  return [
    attempt.height,
    attempt.is_sync ? "SYNC" : null,
    ...modifiersFor(attempt),
    attempt.official_dd ? `DD ${attempt.official_dd.toFixed(1)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Library rating colours, shared with the code cards. */
const RATING_BADGE: Record<string, string> = {
  P: "bg-emerald-400",
  G: "bg-app-accent",
  M: "bg-amber-300",
  B: "bg-orange-400",
  F: "bg-red-400",
};

function groupByDay(attempts: Attempt[]) {
  const groups: Array<{ key: string; label: string; items: Attempt[] }> = [];
  for (const attempt of attempts) {
    const key = attempt.dive_datetime.slice(0, 10);
    const last = groups[groups.length - 1];
    if (last?.key === key) last.items.push(attempt);
    else
      groups.push({
        key,
        label: format(parseISO(attempt.dive_datetime), "EEEE d MMMM yyyy", { locale: appLocale() }),
        items: [attempt],
      });
  }
  return groups;
}

function LibraryCard({
  attempt,
  name,
  onOpen,
  showDiver,
  thumbnail,
}: {
  attempt: Attempt;
  name: string;
  onOpen: () => void;
  showDiver: boolean;
  thumbnail?: (attempt: Attempt) => React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onOpen}
      data-attempt-id={attempt.id}
      className="group flex h-full min-w-0 flex-col text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-app-accent"
      aria-label={[
        t("dives.openAttemptAria", {
          code: attempt.dive_code,
          date: format(parseISO(attempt.dive_datetime), "d MMM yyyy", { locale: appLocale() }),
        }),
        showDiver && attempt.person_name,
      ]
        .filter(Boolean)
        .join(" · ")}
    >
      <div className="relative aspect-[9/16] w-full overflow-hidden rounded-xl border border-app transition-colors group-hover:border-app-strong">
        {thumbnail ? thumbnail(attempt) : <DiveThumbnail dive={attempt} compact />}
        <span className={`absolute bottom-1.5 left-1.5 rounded-full px-1.5 py-px text-xs font-bold tabular-nums text-black/80 ${RATING_BADGE[attempt.performance] ?? "bg-app-muted"}`}>
          {attemptScore(attempt).toFixed(1)}
        </span>
      </div>
      <span className="mt-1.5 px-0.5 font-mono text-sm font-semibold tracking-tight text-app-text">{attempt.dive_code}</span>
      {showDiver && attempt.person_name && (
        <p className="truncate px-0.5 text-xs text-app-text" title={attempt.person_name}>
          {attempt.person_name}
        </p>
      )}
      {name && <p className="mt-0.5 px-0.5 text-[11px] leading-snug text-app-muted">{name}</p>}
      <p className="mt-auto px-0.5 pt-1 text-[10px] leading-snug text-app-muted opacity-70">{attemptFacts(attempt)}</p>
    </button>
  );
}

/**
 * Library grid: one section per day, portrait cards (the clips are filmed
 * upright, so previews play uncropped) with the score on the thumbnail, the
 * dive code, its full localized name and the facts that differ between attempts.
 * Rows stretch so every card in a row shares the same height.
 */
export function LibraryCardGrid({
  attempts,
  onOpen,
  showDiver = false,
  thumbnail,
}: {
  attempts: Attempt[];
  onOpen: (attempt: Attempt) => void;
  showDiver?: boolean;
  /** Replaces the Library thumbnail, for rows that carry their own media URLs. */
  thumbnail?: (attempt: Attempt) => React.ReactNode;
}) {
  const { i18n } = useTranslation();
  const lang = i18n.language?.startsWith("fr") ? "fr" : "en";
  const groups = useMemo(() => groupByDay(attempts), [attempts]);
  return (
    <div>
      {groups.map((group) => (
        <section key={group.key} className="mt-7 first:mt-0" aria-label={group.label}>
          <div className="mb-2 flex items-baseline gap-3">
            <h2 className="text-sm font-semibold text-app-text first-letter:uppercase">{group.label}</h2>
            <span className="text-xs tabular-nums text-app-muted">{group.items.length}</span>
            <span className="h-px flex-1 self-center bg-app-border" aria-hidden="true" />
          </div>
          <div className="grid grid-cols-4 gap-x-2 gap-y-4 sm:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8">
            {group.items.map((attempt) => {
              const name = diveCodeName(attempt.dive_code, lang);
              return (
                <LibraryCard
                  key={attempt.id}
                  attempt={attempt}
                  name={name === attempt.dive_code ? "" : name}
                  onOpen={() => onOpen(attempt)}
                  showDiver={showDiver}
                  thumbnail={thumbnail}
                />
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
