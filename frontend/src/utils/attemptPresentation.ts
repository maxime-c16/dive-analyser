import { format, parseISO } from "date-fns";
import i18n from "../i18n";
import { appLocale } from "./dateLocale";
import { performanceScore10 } from "./performanceScoring";
import { divePositionName } from "./divePosition";

export type Attempt = {
  thumbhash?: string | null;
  animated_url?: string | null;
  thumb_url?: string | null;
  person_name?: string | null;
  visibility?: "public" | "private";
  federate_enabled?: boolean;
  evaluation_request?: import("../services/evaluationApi").EvaluationRequestSummary | null;
  can_manage?: boolean;
  id: number;
  dive_code: string;
  performance: string;
  performance_numeric: number;
  height: string;
  dive_datetime: string;
  session_id: number;
  is_lineup: boolean;
  is_sync: boolean;
  is_smack?: boolean;
  platform_type: string;
  position?: string | null;
  official_dd: number | null;
  phase1_performance?: string | null;
  phase2_performance?: string | null;
  raw_caption?: string | null;
  notes?: string | null;
  video_uuid?: string | null;
  diver_id?: number | null;
};

export const MODIFIERS = ["DB", "SD", "HU"] as const;
export const PERFORMANCE = ["P", "G", "M", "B", "F"] as const;

/**
 * Performance letters are the app's own F/B/M/G/P scale (also FINA entry
 * codes); their display names are localized:
 * P = Perfect/Parfait, G = Good/Bon, M = Medium/Moyen, B = Below target,
 * F = Failed/Manqué.
 */
export function performanceLabel(performance: string): string {
  const key: Record<string, string> = { P: "P", G: "G", M: "M", B: "B", F: "F" };
  const suffix = key[performance];
  return suffix ? i18n.t(`performance.${suffix}`) : performance;
}
export const performanceClass: Record<string, string> = {
  P: "border-emerald-400/45 bg-emerald-400/10 text-emerald-200",
  G: "border-app-accent bg-app-panel-elevated text-app-accent",
  M: "border-amber-300/40 bg-amber-300/10 text-amber-100",
  B: "border-orange-300/40 bg-orange-300/10 text-orange-100",
  F: "border-red-300/40 bg-red-300/10 text-red-100",
};

export function modifiersFor(attempt: Attempt) {
  return MODIFIERS.filter((modifier) =>
    new RegExp(`\\b${modifier}\\b`, "i").test(attempt.raw_caption || ""),
  );
}

export function attemptScore(attempt: Attempt) {
  return performanceScore10(
    attempt.performance,
    attempt.phase1_performance || undefined,
    attempt.phase2_performance || undefined,
  );
}

export function attemptDate(attempt: Attempt, pattern = "d MMM yyyy") {
  return format(parseISO(attempt.dive_datetime), pattern, { locale: appLocale() });
}

/** platform_type arrives as "springboard"/"platform" — display localized. */
export function platformTypeName(platformType: string): string {
  if (platformType === "springboard") return i18n.t("jargon.springboard")
  if (platformType === "platform") return i18n.t("jargon.platform")
  return platformType
}

export function attemptSummary(attempt: Attempt) {
  const phases =
    attempt.phase1_performance && attempt.phase2_performance
      ? `${attempt.phase1_performance} / ${attempt.phase2_performance}`
      : null;
  const modifiers = modifiersFor(attempt);
  return [
    attempt.height,
    platformTypeName(attempt.platform_type),
    phases,
    modifiers.join(" ") || null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function attemptDetailRows(attempt: Attempt): Array<[string, string]> {
  const score = attemptScore(attempt);
  const label = (key: string) => i18n.t(`attemptDetail.${key}`);
  return [
    [label("score"), `${score.toFixed(1)} / 10 · ${attempt.performance}`],
    [label("officialDD"), attempt.official_dd?.toFixed(1) || i18n.t("attemptDetail.notDefined")],
    [
      label("phases"),
      attempt.phase1_performance && attempt.phase2_performance
        ? `${attempt.phase1_performance} / ${attempt.phase2_performance}`
        : i18n.t("attemptDetail.singleRating"),
    ],
    [label("height"), attempt.height],
    [label("platform"), platformTypeName(attempt.platform_type)],
    [i18n.t("analysis.position"), divePositionName(attempt.position, attempt.dive_code)],
    [i18n.t("analysis.context"), attempt.is_sync ? "SYNC" : i18n.t("analysis.individual")],
    [i18n.t("analysis.modifiers"), modifiersFor(attempt).join(", ") || i18n.t("analysis.none")],
    [i18n.t("dashboard.date"), attemptDate(attempt, "d MMMM yyyy")],
    [i18n.t("attemptDetail.rawCaption"), attempt.raw_caption || i18n.t("attemptDetail.notPreserved")],
  ];
}
