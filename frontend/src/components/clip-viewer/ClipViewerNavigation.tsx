import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

export const PLAYBACK_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2] as const;

/** Phone footer: previous / position / next. Speed lives in the transport row. */
export default function ClipViewerNavigation({
  index,
  total,
  onPrevious,
  onNext,
}: {
  index: number;
  total: number;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="clip-nav-row">
      <button
        type="button"
        onClick={onPrevious}
        disabled={index <= 0}
        className="clip-hud-button"
        aria-label={t("clipNav.previous")}
        title={`${t("clipNav.previous")} (Shift+←)`}
      >
        <ChevronLeft size={20} />
      </button>
      <p className="clip-nav-count" aria-live="polite">
        <b>{index + 1}</b> / {total}
      </p>
      <button
        type="button"
        onClick={onNext}
        disabled={index >= total - 1}
        className="clip-hud-button"
        aria-label={t("clipNav.next")}
        title={`${t("clipNav.next")} (Shift+→)`}
      >
        <ChevronRight size={20} />
      </button>
    </div>
  );
}
